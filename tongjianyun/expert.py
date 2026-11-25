import re

import frappe
from frappe.utils import cint, now_datetime

from tongjianyun.ai import call_openai_compatible
from tongjianyun.permissions import _is_operator

MAX_QUESTION_CHARS = 12000
MAX_REPLY_CHARS = 100000
CONVERSATION_DOCTYPE = "I-ONE Expert Conversation"
MESSAGE_DOCTYPE = "I-ONE Expert Message"


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw("请先登录", frappe.AuthenticationError)


def _clean_text(value, maximum, field_label):
	text = re.sub(r"\r\n?", "\n", str(value or "")).strip()
	if not text:
		frappe.throw(f"{field_label}不能为空")
	if len(text) > maximum:
		frappe.throw(f"{field_label}不能超过 {maximum} 个字符")
	return text


def _assert_owned(doc):
	user = frappe.session.user
	if _is_operator(user):
		return
	owner_user = getattr(doc, "user", None) or doc.owner
	if owner_user != user and doc.owner != user:
		frappe.throw("无权访问该专家对话", frappe.PermissionError)


def _get_conversation(name):
	doc = frappe.get_doc(CONVERSATION_DOCTYPE, name)
	_assert_owned(doc)
	return doc


def _get_message(name):
	doc = frappe.get_doc(MESSAGE_DOCTYPE, name)
	_assert_owned(doc)
	conversation = _get_conversation(doc.conversation)
	return doc, conversation


def _serialize_message(doc):
	created_at = str(doc.creation or "")
	return {
		"id": doc.name,
		"role": "user" if doc.role == "用户" else "assistant",
		"content": doc.content or "",
		"status": doc.status,
		"source": "deepseek-web" if doc.role == "专家" else "user",
		"oracleJobId": doc.oracle_job_id or "",
		"error": doc.error_message or "",
		"timestamp": created_at,
		"createdAt": created_at,
		"completedAt": str(doc.completed_at or ""),
	}


def _serialize_conversation(doc, message_count=None):
	if message_count is None:
		message_count = frappe.db.count(MESSAGE_DOCTYPE, {"conversation": doc.name})
	return {
		"id": doc.name,
		"topic": doc.title,
		"summary": doc.title,
		"scenario": "general",
		"status": doc.status,
		"provider": doc.provider or "DeepSeek Web",
		"messageCount": cint(message_count),
		"createdAt": str(doc.creation or ""),
		"updatedAt": str(doc.last_message_at or doc.modified or ""),
	}


@frappe.whitelist()
def create_expert_request(question, conversation_id=None):
	_require_login()
	question = _clean_text(question, MAX_QUESTION_CHARS, "问题")
	now = now_datetime()

	if conversation_id:
		conversation = _get_conversation(conversation_id)
		if conversation.status == "已归档":
			frappe.throw("该专家对话已经归档")
	else:
		conversation = frappe.get_doc(
			{
				"doctype": CONVERSATION_DOCTYPE,
				"title": question[:80],
				"user": frappe.session.user,
				"status": "活动",
				"provider": "DeepSeek Web",
				"last_message_at": now,
			}
		).insert(ignore_permissions=True)

	user_message = frappe.get_doc(
		{
			"doctype": MESSAGE_DOCTYPE,
			"conversation": conversation.name,
			"role": "用户",
			"content": question,
			"status": "已发送",
			"source": "手机端",
		}
	).insert(ignore_permissions=True)
	assistant_message = frappe.get_doc(
		{
			"doctype": MESSAGE_DOCTYPE,
			"conversation": conversation.name,
			"role": "专家",
			"content": "",
			"status": "排队中",
			"source": "DeepSeek Web",
		}
	).insert(ignore_permissions=True)
	conversation.db_set(
		{"status": "等待回复", "last_message_at": now, "last_error": None},
		update_modified=True,
	)
	return {
		"conversation": _serialize_conversation(conversation, message_count=2),
		"userMessage": _serialize_message(user_message),
		"assistantMessage": _serialize_message(assistant_message),
	}


@frappe.whitelist()
def submit_expert_request(question, conversation_id=None):
	"""Create and execute an expert request entirely inside the Frappe app."""
	result = create_expert_request(question, conversation_id)
	assistant = result["assistantMessage"]
	job = frappe.enqueue(
		"tongjianyun.expert.run_expert_request",
		queue="long",
		timeout=900,
		job_name=f"ione-expert-{assistant['id']}",
		message_id=assistant["id"],
		question=question,
	)
	result["conversationId"] = result["conversation"]["id"]
	result["jobId"] = assistant["id"]
	result["queueJobId"] = getattr(job, "id", None)
	result["status"] = assistant["status"]
	return result


def run_expert_request(message_id, question):
	message = frappe.get_doc(MESSAGE_DOCTYPE, message_id)
	conversation = frappe.get_doc(CONVERSATION_DOCTYPE, message.conversation)
	if message.status not in {"排队中", "处理中"}:
		return

	message.db_set("status", "处理中", update_modified=True)
	try:
		reply, _raw = call_openai_compatible(
			question,
			system_prompt=(
				"你是 I-ONE 企业专家。请结合中国企业经营环境，给出准确、审慎、"
				"可以落地执行的中文建议。涉及法律、医疗或财税风险时必须提示用户进行专业复核。"
			),
			temperature=0.3,
		)
		completed_at = now_datetime()
		message.db_set(
			{
				"content": _clean_text(reply, MAX_REPLY_CHARS, "专家回复"),
				"status": "已完成",
				"source": "I-ONE 模型服务",
				"completed_at": completed_at,
				"error_message": None,
			},
			update_modified=True,
		)
		conversation.db_set(
			{
				"provider": "I-ONE 模型服务",
				"status": "活动",
				"last_message_at": completed_at,
				"last_error": None,
			},
			update_modified=True,
		)
	except Exception as exc:
		error = str(exc)[:4000] or "专家模型调用失败"
		completed_at = now_datetime()
		message.db_set(
			{"status": "失败", "error_message": error, "completed_at": completed_at},
			update_modified=True,
		)
		conversation.db_set(
			{"status": "服务异常", "last_error": error, "last_message_at": completed_at},
			update_modified=True,
		)
		frappe.log_error(frappe.get_traceback(), f"I-ONE expert request {message_id}")


@frappe.whitelist()
def link_expert_job(message_id, oracle_job_id):
	_require_login()
	message, conversation = _get_message(message_id)
	if message.role != "专家":
		frappe.throw("只能为专家回复关联任务")
	job_id = _clean_text(oracle_job_id, 140, "Oracle 任务编号")
	message.db_set({"oracle_job_id": job_id, "status": "排队中"}, update_modified=True)
	conversation.db_set("status", "等待回复", update_modified=True)
	return _serialize_message(message)


@frappe.whitelist()
def mark_expert_running(message_id):
	_require_login()
	message, _conversation = _get_message(message_id)
	if message.status in {"排队中", "处理中"}:
		message.db_set("status", "处理中", update_modified=True)
	return _serialize_message(message)


@frappe.whitelist()
def complete_expert_request(message_id, reply, deepseek_conversation_url=None):
	_require_login()
	message, conversation = _get_message(message_id)
	reply = _clean_text(reply, MAX_REPLY_CHARS, "专家回复")
	completed_at = now_datetime()
	message.db_set(
		{
			"content": reply,
			"status": "已完成",
			"completed_at": completed_at,
			"error_message": None,
		},
		update_modified=True,
	)
	updates = {
		"status": "活动",
		"last_message_at": completed_at,
		"last_error": None,
	}
	if deepseek_conversation_url:
		url = str(deepseek_conversation_url).strip()
		if url.startswith("https://chat.deepseek.com/"):
			updates["deepseek_conversation_url"] = url[:500]
	conversation.db_set(updates, update_modified=True)
	return _serialize_message(message)


@frappe.whitelist()
def fail_expert_request(message_id, error_message):
	_require_login()
	message, conversation = _get_message(message_id)
	error = _clean_text(error_message, 4000, "错误信息")
	completed_at = now_datetime()
	message.db_set(
		{"status": "失败", "error_message": error, "completed_at": completed_at},
		update_modified=True,
	)
	conversation.db_set(
		{"status": "服务异常", "last_error": error, "last_message_at": completed_at},
		update_modified=True,
	)
	return _serialize_message(message)


@frappe.whitelist()
def cancel_expert_request(message_id):
	_require_login()
	message, conversation = _get_message(message_id)
	if message.status != "排队中":
		frappe.throw("只有排队中的问题可以取消")
	message.db_set(
		{"status": "已取消", "completed_at": now_datetime()}, update_modified=True
	)
	conversation.db_set("status", "活动", update_modified=True)
	return _serialize_message(message)


@frappe.whitelist()
def get_expert_job(message_id):
	_require_login()
	message, _conversation = _get_message(message_id)
	return _serialize_message(message)


@frappe.whitelist()
def list_expert_conversations(limit=30):
	_require_login()
	limit = max(1, min(cint(limit or 30), 100))
	filters = {}
	if not _is_operator(frappe.session.user):
		filters["user"] = frappe.session.user
	rows = frappe.get_all(
		CONVERSATION_DOCTYPE,
		filters=filters,
		fields=["name", "title", "user", "status", "provider", "last_message_at", "creation", "modified"],
		order_by="last_message_at desc, modified desc",
		limit_page_length=limit,
	)
	if not rows:
		return []
	counts = {
		row.conversation: row.message_count
		for row in frappe.get_all(
			MESSAGE_DOCTYPE,
			filters={"conversation": ["in", [row.name for row in rows]]},
			fields=["conversation", "count(name) as message_count"],
			group_by="conversation",
		)
	}
	return [_serialize_conversation(row, counts.get(row.name, 0)) for row in rows]


@frappe.whitelist()
def get_expert_conversation(conversation_id):
	_require_login()
	conversation = _get_conversation(conversation_id)
	messages = frappe.get_all(
		MESSAGE_DOCTYPE,
		filters={"conversation": conversation.name},
		fields=[
			"name",
			"conversation",
			"role",
			"content",
			"status",
			"source",
			"oracle_job_id",
			"error_message",
			"creation",
			"completed_at",
		],
		order_by="creation asc",
		limit_page_length=500,
	)
	return {**_serialize_conversation(conversation, len(messages)), "messages": [_serialize_message(row) for row in messages]}


@frappe.whitelist()
def get_expert_service_access():
	_require_login()
	return {
		"provider": "I-ONE 模型服务",
		"canManage": bool(_is_operator(frappe.session.user)),
		"loggedIn": True,
		"requiresLogin": False,
		"requiresMobileVerification": False,
		"blocked": False,
		"busy": bool(
			frappe.db.exists(MESSAGE_DOCTYPE, {"status": ["in", ["排队中", "处理中"]]})
		),
		"queueDepth": frappe.db.count(
			MESSAGE_DOCTYPE, {"status": ["in", ["排队中", "处理中"]]}
		),
	}


@frappe.whitelist(methods=["POST"])
def save_expert_evidence(content, conversation_id=None):
	_require_login()
	content = _clean_text(content, MAX_REPLY_CHARS, "专家内容")
	if not frappe.has_permission("I-ONE Evidence", "create"):
		frappe.throw("您没有创建经营档案的权限", frappe.PermissionError)
	doc = frappe.get_doc(
		{
			"doctype": "I-ONE Evidence",
			"title": content[:120],
			"source_type": "AI 推理",
			"confidence": 80,
			"source_doctype": CONVERSATION_DOCTYPE if conversation_id else None,
			"source_name": conversation_id,
			"summary": content[:500],
			"excerpt": content,
		}
	).insert()
	return {"name": doc.name, "route": f"/app/i-one-evidence/{doc.name}"}


@frappe.whitelist(methods=["POST"])
def add_expert_growth_plan(content, conversation_id=None):
	_require_login()
	content = _clean_text(content, MAX_REPLY_CHARS, "专家内容")
	if not frappe.has_permission("I-ONE Growth Plan", "create"):
		frappe.throw("您没有创建成长计划的权限", frappe.PermissionError)
	doc = frappe.get_doc(
		{
			"doctype": "I-ONE Growth Plan",
			"title": content[:120],
			"category": "公司战略",
			"owner_user": frappe.session.user,
			"status": "草稿",
			"objective": content,
			"notes": f"来源专家对话：{conversation_id}" if conversation_id else "",
		}
	).insert()
	return {"name": doc.name, "route": f"/app/i-one-growth-plan/{doc.name}"}
