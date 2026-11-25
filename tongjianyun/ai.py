import json
from urllib.request import Request, urlopen

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime, nowdate


def _log(task, event_type, message, level="信息", payload=None, duration_ms=None):
	frappe.get_doc(
		{
			"doctype": "I-ONE AI Run Log",
			"owner": task.owner,
			"task": task.name,
			"agent": task.assigned_agent,
			"event_type": event_type,
			"level": level,
			"message": message,
			"payload_json": json.dumps(payload, ensure_ascii=False) if payload is not None else None,
			"duration_ms": duration_ms,
		}
	).insert(ignore_permissions=True)


def _settings():
	return frappe.get_single("I-ONE Settings")


def call_openai_compatible(prompt, system_prompt=None, temperature=0.2):
	settings = _settings()
	base_url = (settings.llm_base_url or "").rstrip("/")
	if not base_url:
		frappe.throw("请先在 I-ONE 设置中配置模型服务地址")

	payload = {
		"model": settings.model_name or "qwen",
		"messages": [
			{
				"role": "system",
				"content": system_prompt or "你是 I-ONE 企业智能助理。输出准确、可执行，并使用中文回答。",
			},
			{"role": "user", "content": prompt},
		],
		"temperature": temperature,
	}
	headers = {"Content-Type": "application/json", "Accept": "application/json"}
	api_key = settings.get_password("api_key", raise_exception=False)
	if api_key:
		headers["Authorization"] = f"Bearer {api_key}"

	request = Request(
		f"{base_url}/chat/completions",
		data=json.dumps(payload).encode("utf-8"),
		headers=headers,
		method="POST",
	)
	with urlopen(request, timeout=300) as response:
		data = json.loads(response.read().decode("utf-8"))
	return data["choices"][0]["message"]["content"], data


def _call_openai_compatible(task, settings=None):
	return call_openai_compatible(task.prompt)


def _default_agent():
	return frappe.db.get_value(
		"I-ONE Agent",
		{"status": ["in", ["试用", "在职", "启用"]]},
		"name",
		order_by="modified desc",
	)


def _employee_for_task(task):
	if not task.assigned_agent:
		return None
	if not frappe.db.exists("I-ONE Agent", task.assigned_agent):
		frappe.throw(_("执行 AI 员工 {0} 不存在。").format(task.assigned_agent))
	return frappe.get_doc("I-ONE Agent", task.assigned_agent)


def _should_auto_approve(task, employee):
	return bool(
		employee
		and employee.operating_mode == "自动"
		and task.risk_level == "低"
		and not task.approval_required
	)


def _json_value(value):
	if value in (None, ""):
		return None
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			return value
	return value


def _flow_result_payload(run):
	return {
		"flow_run": run.name,
		"flow_session": run.session,
		"status": run.status,
		"iterations": run.iterations,
		"tool_calls": _json_value(run.tool_calls),
		"questions": _json_value(run.questions),
		"usage": _json_value(run.usage),
	}


def _apply_flow_run(task, run):
	payload = _flow_result_payload(run)
	questions = payload["questions"]
	values = {
		"flow_session": run.session,
		"flow_run": run.name,
		"flow_questions": json.dumps(questions, ensure_ascii=False, indent=2) if questions else None,
		"result_json": json.dumps(payload, ensure_ascii=False, indent=2),
	}

	if run.status == "Completed":
		values.update(
			{
				"status": "已完成",
				"progress": 100,
				"result_summary": run.output or "",
				"error_message": None,
				"completed_at": now_datetime(),
			}
		)
	elif run.status == "Paused":
		values.update(
			{
				"status": "等待确认",
				"progress": 60,
				"result_summary": run.output or "Flow 正在等待人工确认后继续执行。",
				"error_message": None,
			}
		)
	elif run.status == "Failed":
		values.update(
			{
				"status": "执行失败",
				"error_message": run.error or "Flow 执行失败",
				"completed_at": now_datetime(),
			}
		)
	else:
		values.update({"status": "执行中", "progress": 30})

	task.db_set(values, update_modified=True)


def _execute_with_flow(task, employee):
	if employee.status not in {"试用", "在职"}:
		frappe.throw(_("AI 员工 {0} 当前不是可工作状态。").format(employee.agent_name))
	if not employee.flow_agent:
		frappe.throw(_("AI 员工 {0} 尚未发布 Flow Agent。").format(employee.agent_name))
	if not employee.service_user:
		frappe.throw(_("AI 员工 {0} 尚未创建服务用户。").format(employee.agent_name))

	from flow.lib.session import new_session

	from tongjianyun.flow_policy import CHANNEL_AI_EMPLOYEE, prepare_session_execution

	original_user = frappe.session.user
	try:
		frappe.set_user(employee.service_user)
		session = new_session(
			employee.flow_agent,
			title=f"{employee.agent_name}：{task.title}"[:80],
			source="Manual",
		)
		auto_approve, _decision = prepare_session_execution(
			session,
			department=employee.department,
			channel=CHANNEL_AI_EMPLOYEE,
			fallback_auto_approve=_should_auto_approve(task, employee),
			force_confirmation=bool(task.approval_required),
		)
		run = session.chat(
			task.prompt,
			source="Manual",
			reference_doctype=task.source_doctype,
			reference_name=task.source_name,
			auto_approve=auto_approve,
		)
	finally:
		frappe.set_user(original_user)

	_apply_flow_run(task, run)
	frappe.db.set_value(
		"I-ONE Agent",
		employee.name,
		"last_active",
		now_datetime(),
		update_modified=False,
	)
	return run


def execute_ai_task(task_name):
	task = frappe.get_doc("I-ONE AI Task", task_name)
	if task.status in {"已完成", "已取消"}:
		return

	task.db_set(
		{
			"status": "执行中",
			"progress": 10,
			"started_at": task.started_at or now_datetime(),
			"error_message": None,
		},
		update_modified=True,
	)
	_log(task, "任务开始", "后台工作器开始执行 AI 工作单")
	frappe.db.commit()

	try:
		employee = _employee_for_task(task)
		if employee and employee.flow_agent:
			run = _execute_with_flow(task, employee)
			if run.status == "Paused":
				_log(task, "等待确认", "Flow 工具调用正在等待人工确认", payload=_flow_result_payload(run))
			elif run.status == "Completed":
				_log(task, "任务完成", "Flow 已完成 AI 工作单", payload=_flow_result_payload(run))
			else:
				_log(task, "任务状态", f"Flow 返回状态：{run.status}", payload=_flow_result_payload(run))
		else:
			content, raw = _call_openai_compatible(task)
			task.db_set(
				{
					"status": "已完成",
					"progress": 100,
					"result_summary": content,
					"result_json": json.dumps(raw, ensure_ascii=False),
					"completed_at": now_datetime(),
					"error_message": None,
				},
				update_modified=True,
			)
			_log(task, "任务完成", "兼容模式模型返回结果并已保存")
	except Exception as exc:
		message = str(exc)[:2000]
		task.db_set(
			{
				"status": "执行失败",
				"error_message": message,
				"completed_at": now_datetime(),
			},
			update_modified=True,
		)
		_log(task, "执行失败", message, level="错误")
		frappe.log_error(title=f"I-ONE AI Task {task.name}", message=frappe.get_traceback())
	finally:
		frappe.db.commit()


def _check_daily_limit(agent_name):
	if not agent_name:
		return
	limit = frappe.db.get_value("I-ONE Agent", agent_name, "daily_task_limit") or 0
	if not limit:
		return
	count = frappe.db.count(
		"I-ONE AI Task",
		{
			"assigned_agent": agent_name,
			"creation": ["between", [f"{nowdate()} 00:00:00", f"{nowdate()} 23:59:59"]],
			"status": ["!=", "已取消"],
		},
	)
	if count >= limit:
		frappe.throw(_("AI 员工今日工作单已达到上限 {0}。").format(limit))


def _enqueue_task(task):
	job = frappe.enqueue(
		"tongjianyun.ai.execute_ai_task",
		queue="long",
		enqueue_after_commit=True,
		job_name=f"ione-ai-{task.name}",
		task_name=task.name,
	)
	task.db_set(
		{
			"status": "已排队",
			"queue_job_id": getattr(job, "id", None),
		},
		update_modified=True,
	)
	return {"name": task.name, "status": task.status}


@frappe.whitelist()
def queue_ai_task(title, prompt, assigned_agent=None, priority="普通", approval_required=0):
	if frappe.session.user == "Guest":
		frappe.throw("请先登录", frappe.AuthenticationError)

	assigned_agent = assigned_agent or _default_agent()
	if not assigned_agent:
		frappe.throw(_("请先创建并发布一个 AI 员工。"))
	_check_daily_limit(assigned_agent)
	requires_approval = bool(int(approval_required or 0))
	task = frappe.get_doc(
		{
			"doctype": "I-ONE AI Task",
			"title": title,
			"prompt": prompt,
			"assigned_agent": assigned_agent,
			"priority": priority,
			"requested_by": frappe.session.user,
			"approval_required": requires_approval,
			"status": "待审批" if requires_approval else "已排队",
		}
	).insert()

	if requires_approval:
		return {"name": task.name, "status": task.status}
	return _enqueue_task(task)


@frappe.whitelist()
def queue_existing_task(task_name):
	if frappe.session.user == "Guest":
		frappe.throw(_("请先登录"), frappe.AuthenticationError)
	task = frappe.get_doc("I-ONE AI Task", task_name)
	task.check_permission("write")
	if task.status not in {"草稿", "执行失败"}:
		frappe.throw(_("当前状态不能重新执行。"))
	if not task.assigned_agent:
		task.assigned_agent = _default_agent()
		if not task.assigned_agent:
			frappe.throw(_("请先选择一个已发布的 AI 员工。"))
		task.save()
	_check_daily_limit(task.assigned_agent)
	if task.approval_required:
		if not task.approval:
			frappe.throw(_("该工作单要求审批，请重新保存工作单以创建审批请求。"))
		approval_status = frappe.db.get_value("I-ONE Approval Request", task.approval, "status")
		if approval_status != "批准":
			task.db_set("status", "待审批")
			return {"name": task.name, "status": task.status}
	return _enqueue_task(task)


@frappe.whitelist()
def decide_approval(approval_name, decision, note=None):
	approval = frappe.get_doc("I-ONE Approval Request", approval_name)
	if approval.status != "待审批":
		frappe.throw("该审批已经处理")
	if frappe.session.user not in {approval.approver, "Administrator"} and "I-ONE Manager" not in frappe.get_roles():
		frappe.throw("您没有权限处理该审批", frappe.PermissionError)

	if decision not in {"批准", "拒绝"}:
		frappe.throw("无效的审批决定")
	approval.db_set(
		{
			"status": decision,
			"decision_note": note,
			"decided_at": now_datetime(),
		},
		update_modified=True,
	)

	if decision == "批准" and approval.task:
		task = frappe.get_doc("I-ONE AI Task", approval.task)
		task.db_set("status", "已排队")
		if task.source_doctype == "I-ONE Smart Record" and task.source_name:
			frappe.db.set_value("I-ONE Smart Record", task.source_name, "status", "执行中")
			frappe.enqueue(
				"tongjianyun.smart_record.execute_smart_record_job",
				queue="long",
				enqueue_after_commit=True,
				job_name=f"ione-smart-execution-{task.source_name}",
				record_name=task.source_name,
				task_name=task.name,
			)
		else:
			frappe.enqueue(
				"tongjianyun.ai.execute_ai_task",
				queue="long",
				enqueue_after_commit=True,
				job_name=f"ione-ai-{task.name}",
				task_name=task.name,
			)
	elif approval.task:
		task = frappe.get_doc("I-ONE AI Task", approval.task)
		frappe.db.set_value("I-ONE AI Task", task.name, "status", "已取消")
		if task.source_doctype == "I-ONE Smart Record" and task.source_name:
			frappe.db.set_value("I-ONE Smart Record", task.source_name, "status", "已取消")

	return {"name": approval.name, "status": decision}


def sync_task_from_flow_run(doc, method=None):
	task_name = frappe.db.get_value("I-ONE AI Task", {"flow_run": doc.name}, "name")
	if not task_name:
		return
	task = frappe.get_doc("I-ONE AI Task", task_name)
	_apply_flow_run(task, doc)


def expire_pending_approvals():
	if not frappe.db.exists("DocType", "I-ONE Approval Request"):
		return
	cutoff = now_datetime()
	for name in frappe.get_all(
		"I-ONE Approval Request",
		filters={"status": "待审批", "expires_at": ["<", cutoff]},
		pluck="name",
	):
		frappe.db.set_value(
			"I-ONE Approval Request",
			name,
			{"status": "已过期", "decided_at": cutoff},
			update_modified=False,
		)


def default_approval_expiry():
	return add_to_date(now_datetime(), hours=24)
