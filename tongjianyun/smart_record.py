import base64
import binascii
import hashlib
import json
import os
import re
from urllib.parse import quote

import frappe
from frappe.utils import getdate, now_datetime, nowdate
from frappe.utils.file_manager import save_file

from tongjianyun.ai import _log, call_openai_compatible


MAX_FILE_BYTES = 10 * 1024 * 1024
INPUT_TYPES = {"文字", "语音", "图片", "文件"}
RECORD_TYPES = {"待办事项", "CRM 跟进", "客户工单", "财务草稿", "文件归档", "综合事项", "其他"}
ACTION_TARGETS = {
	"创建待办": ("Frappe", "ToDo", "创建记录"),
	"创建客户": ("ERPNext", "Customer", "创建记录"),
	"创建销售线索": ("CRM", "CRM Lead", "创建记录"),
	"创建客户工单": ("Helpdesk", "HD Ticket", "创建记录"),
	"创建请假": ("Frappe HR", "Leave Application", "创建草稿"),
	"创建财务草稿": ("ERPNext", None, "创建草稿"),
	"归档文件": ("Drive", "File", "归档文件"),
	"仅记录": ("I-ONE AI", None, "仅记录"),
}
CAPABILITY_SPECS = (
	{
		"action_type": "创建待办",
		"label": "创建待办",
		"source": "Frappe",
		"doctype": "ToDo",
		"placeholder": "输入事项内容、截止日期和优先级",
	},
	{
		"action_type": "创建客户",
		"label": "创建客户",
		"source": "ERPNext",
		"doctype": "Customer",
		"placeholder": "输入客户名称、客户类型和联系方式",
	},
	{
		"action_type": "创建销售线索",
		"label": "销售线索",
		"source": "CRM",
		"doctype": "CRM Lead",
		"placeholder": "输入联系人、企业和联系方式",
	},
	{
		"action_type": "创建客户工单",
		"label": "客户工单",
		"source": "Helpdesk",
		"doctype": "HD Ticket",
		"placeholder": "输入工单主题、问题描述和客户邮箱",
	},
	{
		"action_type": "创建请假",
		"label": "提交请假",
		"source": "Frappe HR",
		"doctype": "Leave Application",
		"placeholder": "输入请假类型、开始日期、结束日期和原因",
	},
	{
		"action_type": "创建财务草稿",
		"label": "记录收支",
		"source": "ERPNext",
		"doctype": "Journal Entry",
		"placeholder": "输入收支方向、金额、往来单位、日期和说明",
	},
)
ALLOWED_CONTENT_TYPES = {
	"image/jpeg",
	"image/png",
	"image/webp",
	"application/pdf",
	"text/plain",
	"text/csv",
	"application/vnd.ms-excel",
	"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	"application/msword",
	"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw("请先登录", frappe.AuthenticationError)


def _can_create(doctype, user):
	return bool(
		frappe.db.exists("DocType", doctype)
		and frappe.has_permission(doctype, "create", user=user)
	)


def _available_capabilities(user):
	return [dict(spec) for spec in CAPABILITY_SPECS if _can_create(spec["doctype"], user)]


@frappe.whitelist()
def get_smart_record_capabilities():
	_require_login()
	settings = frappe.get_single("I-ONE Settings")
	provider = settings.provider or "OpenClaw"
	return {
		"provider": provider,
		"actions": [
			{key: value for key, value in spec.items() if key != "doctype"}
			for spec in _available_capabilities(frappe.session.user)
		],
	}


def _parse_json(value, fallback=None):
	if value in (None, ""):
		return fallback
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return fallback


def _clean_filename(filename):
	filename = os.path.basename(str(filename or "附件"))
	filename = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]", "_", filename)
	return filename[:140] or "附件"


def _decode_file(file_content, content_type):
	if not file_content:
		return None
	if content_type not in ALLOWED_CONTENT_TYPES:
		frappe.throw("暂不支持该文件类型")
	encoded = str(file_content)
	if encoded.startswith("data:"):
		encoded = encoded.split(",", 1)[-1]
	try:
		content = base64.b64decode(encoded, validate=True)
	except (binascii.Error, ValueError):
		frappe.throw("附件内容不是有效的 Base64 数据")
	if not content:
		frappe.throw("附件内容为空")
	if len(content) > MAX_FILE_BYTES:
		frappe.throw("单个附件不能超过 10 MB")
	return content


def _safe_percent(value):
	try:
		number = float(value or 0)
	except (TypeError, ValueError):
		return 0
	if 0 < number <= 1:
		number *= 100
	return max(0, min(100, number))


def _extract_model_json(content):
	text = str(content or "").strip()
	if text.startswith("```"):
		text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
		text = re.sub(r"\s*```$", "", text)
	start = text.find("{")
	end = text.rfind("}")
	if start < 0 or end <= start:
		raise ValueError("模型没有返回结构化 JSON")
	result = json.loads(text[start : end + 1])
	if not isinstance(result, dict):
		raise ValueError("模型返回的分析结果格式不正确")
	return result


def _normalize_action(item, index, allowed_actions=None):
	item = item if isinstance(item, dict) else {}
	requested_action = item.get("action_type")
	action_type = requested_action if requested_action in ACTION_TARGETS else "仅记录"
	if allowed_actions is not None and action_type not in allowed_actions:
		action_type = "仅记录"
	target_app, target_doctype, operation = ACTION_TARGETS[action_type]
	payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
	risk_level = item.get("risk_level") if item.get("risk_level") in {"低", "中", "高", "关键"} else "低"
	approval_required = bool(item.get("approval_required")) or risk_level in {"高", "关键"}
	if action_type == "创建财务草稿":
		approval_required = True
	return {
		"action_index": index,
		"title": str(item.get("title") or action_type)[:140],
		"action_type": action_type,
		"target_app": target_app,
		"target_doctype": target_doctype,
		"operation": operation,
		"payload_json": json.dumps(payload, ensure_ascii=False, indent=2),
		"confidence": _safe_percent(item.get("confidence")),
		"risk_level": risk_level,
		"approval_required": approval_required,
		"status": "待确认",
	}


def _serialize_record(doc):
	actions = []
	for action in doc.record_actions:
		actions.append(
			{
				"name": action.name,
				"action_index": action.action_index,
				"title": action.title,
				"action_type": action.action_type,
				"target_app": action.target_app,
				"target_doctype": action.target_doctype,
				"operation": action.operation,
				"payload": _parse_json(action.payload_json, {}),
				"confidence": float(action.confidence or 0),
				"risk_level": action.risk_level,
				"approval_required": bool(action.approval_required),
				"status": action.status,
				"target_name": action.target_name,
				"target_route": action.target_route,
				"result_message": action.result_message,
			}
		)
	return {
		"name": doc.name,
		"title": doc.title,
		"input_type": doc.input_type,
		"preferred_action": doc.preferred_action,
		"status": doc.status,
		"raw_text": doc.raw_text,
		"attachment": doc.attachment,
		"file_name": doc.file_name,
		"content_type": doc.content_type,
		"summary": doc.summary,
		"record_type": doc.record_type,
		"confidence": float(doc.confidence or 0),
		"analysis_task": doc.analysis_task,
		"execution_task": doc.execution_task,
		"approval": doc.approval,
		"error_message": doc.error_message,
		"confirmed_at": str(doc.confirmed_at or ""),
		"completed_at": str(doc.completed_at or ""),
		"creation": str(doc.creation or ""),
		"modified": str(doc.modified or ""),
		"actions": actions,
	}


def _analysis_prompt(record):
	capabilities = _available_capabilities(record.submitted_by)
	allowed_actions = [spec["action_type"] for spec in capabilities]
	if record.attachment:
		allowed_actions.append("归档文件")
	allowed_actions.append("仅记录")
	allowed_action_options = "|".join(allowed_actions)
	return f"""请分析下面这条企业业务记录，并只返回一个 JSON 对象，不要输出 Markdown 或解释。

当前日期：{nowdate()}
输入方式：{record.input_type}
用户选择的业务操作：{record.preferred_action or "未指定，由你判断"}
附件名称：{record.file_name or "无"}
附件类型：{record.content_type or "无"}
用户原始内容：
{record.raw_text or "用户只上传了附件"}

返回格式：
{{
  "summary": "不超过80字的业务摘要",
  "record_type": "待办事项|CRM 跟进|客户工单|财务草稿|文件归档|综合事项|其他",
  "confidence": 0到100,
  "actions": [
    {{
      "title": "动作标题",
      "action_type": "{allowed_action_options}",
      "payload": {{}},
      "confidence": 0到100,
      "risk_level": "低|中|高|关键",
      "approval_required": false
    }}
  ]
}}

动作参数约定：
- 创建待办：payload 使用 description、date(YYYY-MM-DD)、priority(High|Medium|Low)。
- 创建客户：payload 使用 customer_name、customer_type(Company|Individual)、mobile_no、email_id、customer_group、territory。
- 创建销售线索：payload 使用 first_name、last_name、organization、email、mobile_no、notes。
- 创建客户工单：payload 使用 subject、description、raised_by、priority。
- 创建请假：payload 使用 employee、leave_type、from_date(YYYY-MM-DD)、to_date(YYYY-MM-DD)、description；employee 可留空，由系统按当前用户匹配。
- 创建财务草稿：payload 使用 direction(收入|支出)、amount、party、date、description、currency；只形成草稿，不直接记账。
- 归档文件：payload 使用 description。
- 只允许使用 action_type 列表中提供的动作，不得输出当前用户无权创建的业务类型。
- 信息不足时不要编造，保留空值并在 payload 中加入 missing_fields 数组。
- 一条原始记录可以生成多个动作。财务、删除或高风险动作必须 approval_required=true。"""


def _new_task(record, title, prompt, task_type, approval_required=False, risk_level="低"):
	return frappe.get_doc(
		{
			"doctype": "I-ONE AI Task",
			"owner": record.owner,
			"title": title,
			"task_type": task_type,
			"priority": "普通",
			"status": "待审批" if approval_required else "已排队",
			"requested_by": record.submitted_by,
			"approval_required": approval_required,
			"risk_level": risk_level,
			"prompt": prompt,
			"source_doctype": "I-ONE Smart Record",
			"source_name": record.name,
		}
	).insert(ignore_permissions=True)


def _queue_analysis(record):
	task = _new_task(record, f"分析智能记录：{record.title}", _analysis_prompt(record), "智能录入")
	record.db_set({"analysis_task": task.name, "status": "分析中", "error_message": None})
	job = frappe.enqueue(
		"tongjianyun.smart_record.analyze_smart_record_job",
		queue="long",
		enqueue_after_commit=True,
		job_name=f"ione-smart-analysis-{record.name}",
		record_name=record.name,
		task_name=task.name,
	)
	task.db_set("queue_job_id", getattr(job, "id", None), update_modified=False)
	return task


@frappe.whitelist()
def get_csrf_token():
	_require_login()
	return frappe.sessions.get_csrf_token()


@frappe.whitelist()
def create_smart_record(
	title=None,
	raw_text=None,
	input_type="文字",
	preferred_action=None,
	file_name=None,
	content_type=None,
	file_content=None,
):
	_require_login()
	if input_type not in INPUT_TYPES:
		frappe.throw("无效的输入方式")
	raw_text = str(raw_text or "").strip()
	content = _decode_file(file_content, content_type) if file_content else None
	if not raw_text and not content:
		frappe.throw("请输入内容或选择附件")
	if not frappe.has_permission("I-ONE Smart Record", "create"):
		frappe.throw("您没有创建智能记录的权限", frappe.PermissionError)
	allowed_actions = {spec["action_type"] for spec in _available_capabilities(frappe.session.user)}
	preferred_action = preferred_action if preferred_action in allowed_actions else None

	clean_name = _clean_filename(file_name) if content else None
	hash_input = raw_text.encode("utf-8") + (content or b"")
	record = frappe.get_doc(
		{
			"doctype": "I-ONE Smart Record",
			"title": str(title or raw_text[:50] or clean_name or "智能记录")[:140],
			"input_type": input_type,
			"preferred_action": preferred_action,
			"status": "草稿",
			"submitted_by": frappe.session.user,
			"raw_text": raw_text,
			"file_name": clean_name,
			"content_type": content_type if content else None,
			"content_hash": hashlib.sha256(hash_input).hexdigest(),
		}
	).insert()

	if content:
		file_doc = save_file(clean_name, content, record.doctype, record.name, is_private=1)
		record.db_set("attachment", file_doc.file_url)

	_queue_analysis(record)
	record.reload()
	return _serialize_record(record)


@frappe.whitelist()
def list_smart_records(limit=20):
	_require_login()
	limit = max(1, min(int(limit or 20), 50))
	roles = set(frappe.get_roles())
	filters = {} if {"System Manager", "I-ONE Manager", "I-ONE AI Operator"}.intersection(roles) else {
		"submitted_by": frappe.session.user
	}
	rows = frappe.get_all(
		"I-ONE Smart Record",
		filters=filters,
		fields=["name", "title", "input_type", "status", "record_type", "confidence", "summary", "file_name", "creation", "modified"],
		order_by="modified desc",
		limit_page_length=limit,
	)
	return [dict(row) for row in rows]


@frappe.whitelist()
def get_smart_record(record_name):
	_require_login()
	record = frappe.get_doc("I-ONE Smart Record", record_name)
	record.check_permission("read")
	return _serialize_record(record)


def analyze_smart_record_job(record_name, task_name):
	record = frappe.get_doc("I-ONE Smart Record", record_name)
	task = frappe.get_doc("I-ONE AI Task", task_name)
	if record.status == "已取消":
		return

	task.db_set({"status": "执行中", "progress": 10, "started_at": now_datetime()}, update_modified=True)
	record.db_set({"status": "分析中", "error_message": None}, update_modified=True)
	_log(task, "任务开始", "开始分析智能记录")
	frappe.db.commit()

	try:
		content, raw = call_openai_compatible(
			_analysis_prompt(record),
			system_prompt="你是通过 OpenClaw 运行的 I-ONE 企业业务操作分析器。必须忠于用户原文，只输出要求的 JSON，不得编造缺失信息。",
			temperature=0.1,
		)
		result = _extract_model_json(content)
		actions = result.get("actions") if isinstance(result.get("actions"), list) else []
		if not actions:
			actions = [{"title": "保存业务记录", "action_type": "仅记录", "payload": {"description": record.raw_text}}]
		allowed_actions = {spec["action_type"] for spec in _available_capabilities(record.submitted_by)}
		if record.attachment:
			allowed_actions.add("归档文件")
		allowed_actions.add("仅记录")

		record.summary = str(result.get("summary") or record.title)[:500]
		record.record_type = result.get("record_type") if result.get("record_type") in RECORD_TYPES else "其他"
		record.confidence = _safe_percent(result.get("confidence"))
		record.status = "待确认"
		record.error_message = None
		record.set("record_actions", [])
		for index, action in enumerate(actions[:10], start=1):
			record.append("record_actions", _normalize_action(action, index, allowed_actions))
		record.save(ignore_permissions=True)

		task.db_set(
			{
				"status": "已完成",
				"progress": 100,
				"result_summary": record.summary,
				"result_json": json.dumps({"analysis": result, "provider_response": raw}, ensure_ascii=False),
				"completed_at": now_datetime(),
				"error_message": None,
			},
			update_modified=True,
		)
		_log(task, "任务完成", f"生成 {len(record.record_actions)} 个待确认动作")
	except Exception as exc:
		message = str(exc)[:2000]
		record.db_set({"status": "失败", "error_message": message}, update_modified=True)
		task.db_set({"status": "执行失败", "error_message": message, "completed_at": now_datetime()}, update_modified=True)
		_log(task, "执行失败", message, level="错误")
		frappe.log_error(title=f"I-ONE Smart Record {record.name}", message=frappe.get_traceback())
	finally:
		frappe.db.commit()


def _apply_action_updates(record, actions):
	updates = _parse_json(actions, [])
	if not updates:
		return
	if not isinstance(updates, list):
		frappe.throw("业务动作格式不正确")
	by_name = {row.name: row for row in record.record_actions}
	by_index = {int(row.action_index or 0): row for row in record.record_actions}
	for item in updates:
		if not isinstance(item, dict):
			continue
		row = by_name.get(item.get("name")) or by_index.get(int(item.get("action_index") or 0))
		if not row:
			continue
		if item.get("title"):
			row.title = str(item["title"])[:140]
		payload = item.get("payload")
		if payload is not None:
			if not isinstance(payload, dict):
				frappe.throw("业务参数必须是对象")
			row.payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
		if item.get("approval_required"):
			row.approval_required = 1


def _required_payload_fields(action_type, payload, user, has_attachment):
	if action_type == "创建待办":
		return ["description"] if not str(payload.get("description") or "").strip() else []
	if action_type == "创建客户":
		return ["customer_name"] if not str(payload.get("customer_name") or "").strip() else []
	if action_type == "创建销售线索":
		if not str(payload.get("first_name") or "").strip() and not str(payload.get("organization") or "").strip():
			return ["first_name 或 organization"]
		return []
	if action_type == "创建客户工单":
		return [field for field in ("subject", "description") if not str(payload.get(field) or "").strip()]
	if action_type == "创建请假":
		missing = [field for field in ("leave_type", "from_date", "to_date") if not str(payload.get(field) or "").strip()]
		if not payload.get("employee") and not frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name"):
			missing.append("employee")
		return missing
	if action_type == "创建财务草稿":
		missing = [field for field in ("direction", "amount", "date", "description") if not str(payload.get(field) or "").strip()]
		try:
			if payload.get("amount") and float(payload["amount"]) <= 0:
				missing.append("amount 必须大于 0")
		except (TypeError, ValueError):
			missing.append("amount 必须是数字")
		return missing
	if action_type == "归档文件" and not has_attachment:
		return ["attachment"]
	return []


def _validate_record_actions(record):
	issues = []
	for action in record.record_actions:
		payload = _parse_json(action.payload_json, {})
		missing = _required_payload_fields(action.action_type, payload, record.submitted_by, bool(record.attachment))
		if missing:
			issues.append(f"{action.title}：请补充 {', '.join(missing)}")
	if issues:
		frappe.throw("；".join(issues))


@frappe.whitelist()
def confirm_smart_record(record_name, actions=None):
	_require_login()
	record = frappe.get_doc("I-ONE Smart Record", record_name)
	record.check_permission("write")
	if record.status != "待确认":
		frappe.throw("该记录当前不能确认执行")
	_apply_action_updates(record, actions)
	_validate_record_actions(record)

	requires_approval = any(bool(action.approval_required) for action in record.record_actions)
	risk_level = "高" if requires_approval else "低"
	task = _new_task(
		record,
		f"执行智能记录：{record.title}",
		f"执行智能记录 {record.name} 中已经由用户确认的结构化动作。",
		"业务执行",
		approval_required=requires_approval,
		risk_level=risk_level,
	)
	approval = frappe.db.get_value("I-ONE AI Task", task.name, "approval")
	record.execution_task = task.name
	record.approval = approval
	record.confirmed_at = now_datetime()
	record.status = "待审批" if requires_approval else "执行中"
	for action in record.record_actions:
		action.status = "待审批" if requires_approval else "执行中"
	record.save()

	if not requires_approval:
		job = frappe.enqueue(
			"tongjianyun.smart_record.execute_smart_record_job",
			queue="long",
			enqueue_after_commit=True,
			job_name=f"ione-smart-execution-{record.name}",
			record_name=record.name,
			task_name=task.name,
		)
		task.db_set("queue_job_id", getattr(job, "id", None), update_modified=False)

	record.reload()
	return _serialize_record(record)


def _ensure_create_permission(doctype, user):
	if not frappe.has_permission(doctype, "create", user=user):
		frappe.throw(f"用户没有创建 {doctype} 的权限", frappe.PermissionError)


def _execute_todo(payload, user):
	_ensure_create_permission("ToDo", user)
	description = str(payload.get("description") or "").strip()
	if not description:
		frappe.throw("待办事项内容不能为空")
	priority = payload.get("priority") if payload.get("priority") in {"High", "Medium", "Low"} else "Medium"
	try:
		date = getdate(payload.get("date")) if payload.get("date") else getdate(nowdate())
	except Exception:
		date = getdate(nowdate())
	doc = frappe.get_doc(
		{
			"doctype": "ToDo",
			"description": description[:2000],
			"allocated_to": user,
			"priority": priority,
			"date": date,
			"status": "Open",
		}
	).insert()
	return doc, f"/app/todo/{quote(doc.name)}"


def _execute_customer(payload, user):
	_ensure_create_permission("Customer", user)
	customer_name = str(payload.get("customer_name") or "").strip()
	if not customer_name:
		frappe.throw("客户名称不能为空")
	customer_group = payload.get("customer_group") or frappe.db.get_single_value("Selling Settings", "customer_group")
	if not customer_group:
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="lft asc")
	territory = payload.get("territory") or frappe.db.get_single_value("Selling Settings", "territory")
	if not territory:
		territory = frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft asc")
	if not customer_group or not territory:
		frappe.throw("ERPNext 尚未配置默认客户组或地区")
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name[:140],
			"customer_type": payload.get("customer_type") if payload.get("customer_type") in {"Company", "Individual"} else "Company",
			"customer_group": customer_group,
			"territory": territory,
			"mobile_no": str(payload.get("mobile_no") or "")[:50],
			"email_id": str(payload.get("email_id") or "")[:140],
		}
	).insert()
	return doc, f"/app/customer/{quote(doc.name)}"


def _execute_crm_lead(payload, user):
	_ensure_create_permission("CRM Lead", user)
	first_name = str(payload.get("first_name") or "").strip()
	organization = str(payload.get("organization") or "").strip()
	if not first_name and not organization:
		frappe.throw("联系人或企业名称至少填写一项")
	status = payload.get("status")
	if not status or not frappe.db.exists("CRM Lead Status", status):
		status = frappe.db.get_value("CRM Lead Status", {}, "name", order_by="position asc, creation asc")
	if not status:
		frappe.throw("CRM 尚未配置销售线索状态")
	doc = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": (first_name or organization)[:140],
			"last_name": str(payload.get("last_name") or "")[:140],
			"organization": organization[:140],
			"email": str(payload.get("email") or "")[:140],
			"mobile_no": str(payload.get("mobile_no") or "")[:50],
			"status": status,
		}
	).insert()
	return doc, f"/crm/leads/{quote(doc.name)}"


def _execute_hd_ticket(payload, user):
	_ensure_create_permission("HD Ticket", user)
	subject = str(payload.get("subject") or "").strip()
	description = str(payload.get("description") or "").strip()
	if not subject or not description:
		frappe.throw("工单主题和问题描述不能为空")
	doc = frappe.get_doc(
		{
			"doctype": "HD Ticket",
			"subject": subject[:140],
			"description": description[:5000],
			"raised_by": str(payload.get("raised_by") or user)[:140],
		}
	).insert()
	return doc, f"/helpdesk/tickets/{quote(doc.name)}"


def _execute_leave_application(payload, user):
	_ensure_create_permission("Leave Application", user)
	employee = payload.get("employee") or frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	leave_type = str(payload.get("leave_type") or "").strip()
	from_date = payload.get("from_date")
	to_date = payload.get("to_date")
	if not employee or not leave_type or not from_date or not to_date:
		frappe.throw("请假员工、请假类型和起止日期不能为空")
	if not frappe.db.exists("Employee", employee):
		frappe.throw("未找到对应员工")
	if not frappe.db.exists("Leave Type", leave_type):
		frappe.throw("未找到对应请假类型")
	doc = frappe.get_doc(
		{
			"doctype": "Leave Application",
			"employee": employee,
			"leave_type": leave_type,
			"from_date": getdate(from_date),
			"to_date": getdate(to_date),
			"description": str(payload.get("description") or "")[:1000],
			"status": "Open",
		}
	).insert()
	return doc, f"/app/leave-application/{quote(doc.name)}"


def _execute_action(record, action, user):
	payload = _parse_json(action.payload_json, {})
	if action.action_type == "创建待办":
		doc, route = _execute_todo(payload, user)
	elif action.action_type == "创建客户":
		doc, route = _execute_customer(payload, user)
	elif action.action_type == "创建销售线索":
		doc, route = _execute_crm_lead(payload, user)
	elif action.action_type == "创建客户工单":
		doc, route = _execute_hd_ticket(payload, user)
	elif action.action_type == "创建请假":
		doc, route = _execute_leave_application(payload, user)
	elif action.action_type == "归档文件":
		if not record.attachment:
			frappe.throw("该记录没有可归档的附件")
		file_name = frappe.db.get_value("File", {"file_url": record.attachment, "attached_to_name": record.name}, "name")
		action.target_name = file_name
		action.target_route = f"/app/file/{quote(file_name)}" if file_name else None
		action.result_message = "附件已作为私有文件归档"
		return
	elif action.action_type == "创建财务草稿":
		action.result_message = "财务草稿已结构化保存，等待补充会计科目后进入 ERPNext"
		return
	else:
		action.result_message = "业务信息已保存至智能记录"
		return
	action.target_doctype = doc.doctype
	action.target_name = doc.name
	action.target_route = route
	action.result_message = f"已创建 {doc.doctype} {doc.name}"


def execute_smart_record_job(record_name, task_name):
	record = frappe.get_doc("I-ONE Smart Record", record_name)
	task = frappe.get_doc("I-ONE AI Task", task_name)
	if record.status in {"已完成", "已取消"}:
		return
	request_user = record.submitted_by
	original_user = frappe.session.user
	failed = 0
	executed = 0

	try:
		frappe.set_user(request_user)
		task.db_set({"status": "执行中", "progress": 10, "started_at": now_datetime()}, update_modified=True)
		record.db_set("status", "执行中", update_modified=True)
		_log(task, "任务开始", "开始执行用户确认的业务动作")
		for action in record.record_actions:
			action.status = "执行中"
			try:
				_execute_action(record, action, request_user)
				action.status = "已执行"
				executed += 1
			except Exception as exc:
				action.status = "执行失败"
				action.result_message = str(exc)[:500]
				failed += 1

		record.status = "已完成" if failed == 0 else ("部分完成" if executed else "失败")
		record.completed_at = now_datetime()
		record.error_message = f"{failed} 个动作执行失败" if failed else None
		record.save(ignore_permissions=True)
		task.db_set(
			{
				"status": "已完成" if executed or not failed else "执行失败",
				"progress": 100,
				"result_summary": f"已执行 {executed} 个动作，失败 {failed} 个动作",
				"completed_at": now_datetime(),
				"error_message": record.error_message,
			},
			update_modified=True,
		)
		_log(task, "任务完成", f"执行完成：成功 {executed}，失败 {failed}", level="警告" if failed else "信息")
	except Exception as exc:
		message = str(exc)[:2000]
		record.db_set({"status": "失败", "error_message": message, "completed_at": now_datetime()}, update_modified=True)
		task.db_set({"status": "执行失败", "error_message": message, "completed_at": now_datetime()}, update_modified=True)
		_log(task, "执行失败", message, level="错误")
		frappe.log_error(title=f"I-ONE Smart Record Execute {record.name}", message=frappe.get_traceback())
	finally:
		frappe.set_user(original_user)
		frappe.db.commit()


@frappe.whitelist()
def retry_smart_record(record_name):
	_require_login()
	record = frappe.get_doc("I-ONE Smart Record", record_name)
	record.check_permission("write")
	if record.status != "失败":
		frappe.throw("只有失败的记录可以重新分析")
	record.set("record_actions", [])
	record.status = "分析中"
	record.error_message = None
	record.summary = None
	record.record_type = None
	record.confidence = 0
	record.save()
	_queue_analysis(record)
	record.reload()
	return _serialize_record(record)


@frappe.whitelist()
def cancel_smart_record(record_name):
	_require_login()
	record = frappe.get_doc("I-ONE Smart Record", record_name)
	record.check_permission("write")
	if record.status in {"执行中", "已完成", "部分完成"}:
		frappe.throw("该记录当前不能取消")
	record.db_set("status", "已取消", update_modified=True)
	return _serialize_record(frappe.get_doc("I-ONE Smart Record", record_name))
