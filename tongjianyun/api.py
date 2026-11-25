from urllib.parse import quote
import base64
import hashlib
import hmac
import json
import time

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_first_day, getdate, nowdate, strip_html


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("请先登录"), frappe.AuthenticationError)
	return frappe.session.user


_CODEX_PROJECT_ISSUER = "child.myyr.top"
_CODEX_PROJECT_AUDIENCE = "codex-project.myyr.top"
_CODEX_PROJECT_WS_URL = "wss://codex-project.myyr.top"
_CODEX_PROJECT_ROLES = {"Administrator", "System Manager", "I-ONE Agent Manager", "I-ONE Manager"}


def _base64url(value):
	return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _codex_project_jwt(user):
	secret = str(frappe.conf.get("codex_project_ws_secret") or "").strip()
	if len(secret) < 32:
		frappe.throw(_("项目 Codex 尚未完成服务端配置。"), frappe.ValidationError)
	now = int(time.time())
	header = _base64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
	payload = _base64url(
		json.dumps(
			{
				"iss": _CODEX_PROJECT_ISSUER,
				"aud": _CODEX_PROJECT_AUDIENCE,
				"sub": user,
				"scope": ["project:write"],
				"iat": now,
				"exp": now + 600,
			},
			separators=(",", ":"),
		).encode()
	)
	signing_input = f"{header}.{payload}".encode("ascii")
	signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
	return f"{header}.{payload}.{_base64url(signature)}", now + 600


@frappe.whitelist()
def get_codex_project_token():
	user = _require_login()
	if not _CODEX_PROJECT_ROLES.intersection(set(frappe.get_roles(user))):
		frappe.throw(_("您没有项目 Codex 的权限。"), frappe.PermissionError)
	token, expires_at = _codex_project_jwt(user)
	return {
		"token": token,
		"expires_at": expires_at,
		"user": user,
		"ws_url": _CODEX_PROJECT_WS_URL,
		"project": "/home/zyd/frappe/native-bench",
	}


def _call_permission(method_path):
	if not method_path:
		return True
	try:
		return bool(frappe.get_attr(method_path)())
	except Exception:
		return False


def _app_category(app_name):
	return {
		"erpnext": "经营管理",
		"crm": "经营管理",
		"lending": "经营管理",
		"hrms": "组织发展",
		"lms": "组织发展",
		"helpdesk": "服务协作",
		"gameplan": "服务协作",
		"drive": "服务协作",
		"insights": "数据分析",
		"builder": "建设工具",
		"frappe": "系统管理",
		"tongjianyun": "I-ONE",
	}.get(app_name, "其他")


@frappe.whitelist()
def has_app_permission():
	return frappe.session.user != "Guest" and bool(
		{"System Manager", "I-ONE User", "I-ONE Manager", "I-ONE AI Operator"}.intersection(
			frappe.get_roles()
		)
	)


@frappe.whitelist()
def get_app_registry():
	_require_login()
	installed = set(frappe.get_installed_apps())
	result = []
	for item in frappe.get_hooks("add_to_apps_screen", default=[]):
		app_name = item.get("name")
		if not app_name or app_name not in installed or not _call_permission(item.get("has_permission")):
			continue
		result.append(
			{
				"name": app_name,
				"title": item.get("title") or app_name,
				"route": item.get("route") or "/app",
				"logo": item.get("logo"),
				"category": _app_category(app_name),
				"sequence": item.get("sequence_id", 999),
			}
		)
	return sorted(result, key=lambda app: (app["category"], app["sequence"], app["title"]))


def _safe_count(doctype, filters=None):
	if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
		return None


def _safe_sum(doctype, fieldname, filters=None):
	if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
		return None
	try:
		rows = frappe.get_list(
			doctype,
			filters=filters or {},
			fields=[{"SUM": fieldname, "as": "value"}],
			limit_page_length=1,
		)
		return flt(rows[0].value) if rows else 0
	except Exception:
		return None


def _safe_rows(doctype, fields, filters=None, order_by="modified desc", limit=50):
	if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
		return []
	try:
		return [
			dict(row)
			for row in frappe.get_list(
				doctype,
				filters=filters or {},
				fields=fields,
				order_by=order_by,
				limit_page_length=max(1, min(int(limit or 50), 200)),
			)
		]
	except Exception:
		frappe.log_error(title=f"I-ONE Mobile {doctype}", message=frappe.get_traceback())
		return []
	try:
		rows = frappe.get_list(
			doctype,
			filters=filters or {},
			fields=[{"COUNT": "*", "as": "value"}],
			limit_page_length=1,
		)
		return int(rows[0].value or 0) if rows else 0
	except Exception:
		return None


def _metric(key, label, value, source, route):
	return {"key": key, "label": label, "value": value, "source": source, "route": route}


def _overview_metric(key, label, value, source, route, value_format="number", tone="primary", available=True):
	return {
		"key": key,
		"label": label,
		"value": value if available else None,
		"source": source,
		"route": route,
		"format": value_format,
		"tone": tone,
		"available": available,
	}


def _default_company():
	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company and frappe.db.exists("DocType", "Company"):
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	return company


def _can_view_finance():
	if not frappe.db.exists("DocType", "GL Entry") or not frappe.db.exists("DocType", "Account"):
		return False
	roles = set(frappe.get_roles())
	return frappe.has_permission("GL Entry", "read") or bool(
		{"System Manager", "Accounts User", "Accounts Manager", "I-ONE Manager"}.intersection(roles)
	)


def _sum_gl(root_type, company, from_date, to_date, use_permissions):
	accounts = frappe.get_all(
		"Account",
		filters={"root_type": root_type, "is_group": 0, "company": company},
		pluck="name",
	)
	if not accounts:
		return 0
	getter = frappe.get_list if use_permissions else frappe.get_all
	rows = getter(
		"GL Entry",
		filters={
			"company": company,
			"posting_date": ["between", [str(from_date), str(to_date)]],
			"is_cancelled": 0,
			"account": ["in", accounts],
		},
		fields=[{"SUM": "debit", "as": "debit"}, {"SUM": "credit", "as": "credit"}],
		limit_page_length=1,
	)
	row = rows[0] if rows else {}
	debit = flt(row.get("debit"))
	credit = flt(row.get("credit"))
	return credit - debit if root_type == "Income" else debit - credit


def _finance_summary(from_date, to_date, company):
	if not company or not _can_view_finance():
		return {"available": False, "income": None, "expense": None, "profit": None}
	use_permissions = frappe.has_permission("GL Entry", "read")
	try:
		income = _sum_gl("Income", company, from_date, to_date, use_permissions)
		expense = _sum_gl("Expense", company, from_date, to_date, use_permissions)
		return {
			"available": True,
			"income": income,
			"expense": expense,
			"profit": income - expense,
		}
	except Exception:
		frappe.log_error(title="I-ONE Dashboard Finance", message=frappe.get_traceback())
		return {"available": False, "income": None, "expense": None, "profit": None}


def _operating_target(company, month_start):
	if not company or not frappe.db.exists("DocType", "I-ONE Operating Target"):
		return None
	if not frappe.has_permission("I-ONE Operating Target", "read"):
		return None
	rows = frappe.get_list(
		"I-ONE Operating Target",
		filters={"company": company, "target_month": month_start, "enabled": 1},
		fields=["name", "currency", "revenue_target", "profit_target", "customer_target"],
		order_by="modified desc",
		limit_page_length=1,
	)
	return dict(rows[0]) if rows else None


@frappe.whitelist()
def get_unified_todos(limit=20):
	_require_login()
	limit = max(1, min(int(limit or 20), 50))
	items = []

	if frappe.db.exists("DocType", "ToDo") and frappe.has_permission("ToDo", "read"):
		for row in frappe.get_list(
			"ToDo",
			filters={"status": "Open", "allocated_to": frappe.session.user},
			fields=["name", "description", "priority", "date", "reference_type", "reference_name"],
			order_by="priority desc, date asc, modified desc",
			limit_page_length=limit,
		):
			items.append(
				{
					"id": f"todo:{row.name}",
					"title": row.description or row.reference_name or _("待办事项"),
					"source": "Frappe ToDo",
					"status": "待处理",
					"priority": row.priority or "Medium",
					"due_date": row.date,
					"route": f"/app/todo/{quote(row.name)}",
				}
			)

	if frappe.db.exists("DocType", "I-ONE AI Task") and frappe.has_permission("I-ONE AI Task", "read"):
		for row in frappe.get_list(
			"I-ONE AI Task",
			filters={"status": ["in", ["待审批", "已排队", "执行中", "等待确认"]]},
			fields=["name", "title", "priority", "status", "modified"],
			order_by="modified desc",
			limit_page_length=limit,
		):
			items.append(
				{
					"id": f"ione:{row.name}",
					"title": row.title,
					"source": "I-ONE AI",
					"status": row.status,
					"priority": row.priority,
					"due_date": None,
					"route": f"/app/i-one-ai-task/{quote(row.name)}",
				}
			)

	return items[:limit]


@frappe.whitelist()
def get_dashboard():
	_require_login()
	metrics = []

	leads_doctype = "CRM Lead" if frappe.db.exists("DocType", "CRM Lead") else "Lead"
	leads = _safe_count(leads_doctype)
	if leads is not None:
		metrics.append(_metric("leads", "销售线索", leads, "CRM", f"/app/{frappe.scrub(leads_doctype).replace('_', '-')}"))

	employees = _safe_count("Employee", {"status": "Active"})
	if employees is not None:
		metrics.append(_metric("employees", "在职员工", employees, "Frappe HR", "/app/employee"))

	tickets = _safe_count("HD Ticket", {"status": ["not in", ["Resolved", "Closed"]]})
	if tickets is not None:
		metrics.append(_metric("tickets", "未关闭工单", tickets, "Helpdesk", "/helpdesk"))

	today = getdate(nowdate())
	month_start = get_first_day(today)
	company = _default_company()
	currency = frappe.db.get_value("Company", company, "default_currency") if company else None
	currency = currency or frappe.db.get_single_value("Global Defaults", "default_currency") or "CNY"

	today_todos = _safe_count(
		"ToDo",
		{"status": "Open", "allocated_to": frappe.session.user, "date": ["<=", today]},
	)
	customers = _safe_count("Customer")
	pending_ai = _safe_count(
		"I-ONE AI Task",
		{"status": ["in", ["待审批", "已排队", "执行中", "等待确认"]]},
	)
	today_finance = _finance_summary(today, today, company)
	month_finance = _finance_summary(month_start, today, company)

	ledger_route = f"/app/query-report/General%20Ledger?from_date={today}&to_date={today}"
	profit_route = f"/app/query-report/Profit%20and%20Loss%20Statement?from_date={today}&to_date={today}"
	overview = [
		_overview_metric("today_todos", "今日待办", today_todos or 0, "Frappe ToDo", "/app/todo"),
		_overview_metric(
			"today_income", "今日收入", today_finance["income"], "ERPNext 总账", ledger_route,
			value_format="currency", tone="positive", available=today_finance["available"],
		),
		_overview_metric(
			"today_expense", "今日支出", today_finance["expense"], "ERPNext 总账", ledger_route,
			value_format="currency", tone="negative", available=today_finance["available"],
		),
		_overview_metric(
			"today_profit", "今日利润", today_finance["profit"], "ERPNext 总账", profit_route,
			value_format="currency", tone="positive", available=today_finance["available"],
		),
		_overview_metric(
			"customers", "客户数量", customers or 0, "ERPNext", "/app/customer",
			available=customers is not None,
		),
		_overview_metric(
			"ai_tasks", "AI 处理中", pending_ai or 0, "I-ONE AI", "/app/i-one-ai-task",
			available=pending_ai is not None,
		),
	]

	target = _operating_target(company, month_start)
	target_profit = flt(target.get("profit_target")) if target else None
	profit_progress = {
		"actual": month_finance["profit"] if month_finance["available"] else None,
		"target": target_profit,
		"percent": (
			(month_finance["profit"] / target_profit * 100)
			if month_finance["available"] and target_profit and target_profit > 0
			else None
		),
		"currency": currency,
		"route": f"/app/i-one-operating-target/{quote(target['name'])}" if target else "/app/i-one-operating-target",
	}

	return {
		"metrics": metrics,
		"overview": overview,
		"currency": currency,
		"company": company,
		"as_of_date": str(today),
		"profit_progress": profit_progress,
		"todos": get_unified_todos(8),
		"apps": get_app_registry(),
	}


@frappe.whitelist()
def get_bootstrap():
	_require_login()
	user = frappe.session.user
	user_info = frappe.db.get_value(
		"User",
		user,
		["full_name", "user_image", "language", "time_zone"],
		as_dict=True,
	) or {}
	return {
		"user": {
			"username": user,
			"full_name": user_info.get("full_name") or user,
			"user_image": user_info.get("user_image"),
			"language": user_info.get("language"),
			"time_zone": user_info.get("time_zone"),
			"roles": frappe.get_roles(user),
		},
		"site": frappe.local.site,
		"csrf_token": frappe.sessions.get_csrf_token(),
		"apps": get_app_registry(),
		"features": {
			"ai_employees": bool(frappe.db.exists("DocType", "I-ONE Agent")),
			"ai_tasks": bool(frappe.db.exists("DocType", "I-ONE AI Task")),
			"approvals": bool(frappe.db.exists("DocType", "I-ONE Approval Request")),
			"background_jobs": True,
		},
	}


@frappe.whitelist()
def get_mobile_settings():
	_require_login()
	if not frappe.has_permission("I-ONE Settings", "read"):
		return {
			"can_write": False,
			"provider": "",
			"model_name": "",
			"llm_base_url": "",
			"api_key_configured": False,
		}
	settings = frappe.get_single("I-ONE Settings")
	return {
		"can_write": frappe.has_permission("I-ONE Settings", "write"),
		"provider": settings.provider,
		"model_name": settings.model_name,
		"llm_base_url": settings.llm_base_url,
		"api_key_configured": bool(settings.get_password("api_key", raise_exception=False)),
		"require_confirmation_for_writes": bool(settings.require_confirmation_for_writes),
	}


@frappe.whitelist(methods=["POST"])
def update_mobile_settings(model_name=None, llm_base_url=None, api_key=None):
	_require_login()
	if not frappe.has_permission("I-ONE Settings", "write"):
		frappe.throw(_("您没有修改模型设置的权限。"), frappe.PermissionError)
	settings = frappe.get_single("I-ONE Settings")
	if model_name is not None:
		settings.model_name = str(model_name or "").strip()[:140] or "qwen"
	if llm_base_url is not None:
		base_url = str(llm_base_url or "").strip().rstrip("/")
		if not base_url.startswith(("http://", "https://")):
			frappe.throw(_("模型服务地址必须以 http:// 或 https:// 开头。"))
		settings.llm_base_url = base_url[:500]
	if api_key:
		settings.api_key = str(api_key)
	settings.save()
	return get_mobile_settings()


@frappe.whitelist(methods=["POST"])
def test_mobile_model():
	_require_login()
	if not frappe.has_permission("I-ONE Settings", "read"):
		frappe.throw(_("您没有查看模型设置的权限。"), frappe.PermissionError)
	from tongjianyun.ai import call_openai_compatible

	reply, _raw = call_openai_compatible(
		"只回复“连接正常”。",
		system_prompt="你正在执行 I-ONE 模型服务连接测试。",
		temperature=0,
	)
	return {"available": True, "reply": str(reply or "").strip()[:200]}


@frappe.whitelist()
def get_ai_task(name):
	_require_login()
	task = frappe.get_doc("I-ONE AI Task", name)
	task.check_permission("read")
	return {
		"name": task.name,
		"title": task.title,
		"status": task.status,
		"priority": task.priority,
		"progress": task.progress,
		"due_date": task.due_date,
		"modified": task.modified,
		"assigned_agent": task.assigned_agent,
		"prompt": task.prompt,
		"result_summary": task.result_summary,
		"error_message": task.error_message,
		"approval_required": task.approval_required,
		"risk_level": task.risk_level,
		"started_at": task.started_at,
		"completed_at": task.completed_at,
	}


def _task_count_for_agent(agent, statuses=None):
	filters = {"assigned_agent": agent}
	if statuses:
		filters["status"] = ["in", statuses]
	rows = frappe.get_list(
		"I-ONE AI Task",
		filters=filters,
		fields=[{"COUNT": "name", "as": "value"}],
		limit_page_length=1,
	)
	return int(rows[0].value or 0) if rows else 0


@frappe.whitelist()
def get_ai_employees(limit=50):
	_require_login()
	if not frappe.has_permission("I-ONE Agent", "read"):
		frappe.throw(_("您没有查看 AI 员工的权限。"), frappe.PermissionError)
	limit = max(1, min(int(limit or 50), 100))
	rows = frappe.get_list(
		"I-ONE Agent",
		fields=[
			"name",
			"agent_code",
			"agent_name",
			"agent_type",
			"status",
			"avatar",
			"company",
			"department",
			"designation",
			"operating_mode",
			"last_active",
		],
		order_by="status asc, modified desc",
		limit_page_length=limit,
	)
	result = []
	for row in rows:
		item = dict(row)
		item["open_tasks"] = _task_count_for_agent(
			row.name,
			["待审批", "已排队", "执行中", "等待确认"],
		)
		item["completed_tasks"] = _task_count_for_agent(row.name, ["已完成"])
		item["route"] = f"/app/i-one-agent/{quote(row.name)}"
		result.append(item)
	return result


@frappe.whitelist()
def get_ai_employee(name):
	_require_login()
	employee = frappe.get_doc("I-ONE Agent", name)
	employee.check_permission("read")
	tasks = frappe.get_list(
		"I-ONE AI Task",
		filters={"assigned_agent": employee.name},
		fields=[
			"name",
			"title",
			"status",
			"priority",
			"progress",
			"due_date",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=20,
	)
	return {
		"employee": {
			"name": employee.name,
			"agent_code": employee.agent_code,
			"agent_name": employee.agent_name,
			"agent_type": employee.agent_type,
			"status": employee.status,
			"avatar": employee.avatar,
			"company": employee.company,
			"department": employee.department,
			"designation": employee.designation,
			"supervisor": employee.supervisor,
			"description": employee.description,
			"responsibilities": employee.responsibilities,
			"operating_mode": employee.operating_mode,
			"last_active": employee.last_active,
		},
		"metrics": {
			"open": _task_count_for_agent(
				employee.name,
				["待审批", "已排队", "执行中", "等待确认"],
			),
			"completed": _task_count_for_agent(employee.name, ["已完成"]),
			"failed": _task_count_for_agent(employee.name, ["执行失败"]),
		},
		"tasks": [dict(task) for task in tasks],
	}


@frappe.whitelist()
def get_mobile_task_center(limit=30):
	"""Return the user's actionable work, growth plans, and earned achievements."""
	_require_login()
	limit = max(1, min(int(limit or 30), 100))
	plans = _safe_rows(
		"I-ONE Growth Plan",
		["name", "title", "category", "status", "progress", "start_date", "end_date", "objective", "modified"],
		filters={"owner_user": frappe.session.user},
		limit=limit,
	)
	for plan in plans:
		plan["route"] = f"/app/i-one-growth-plan/{quote(plan['name'])}"

	achievements = _safe_rows(
		"I-ONE Achievement",
		[
			"name",
			"achievement_code",
			"title",
			"achievement_type",
			"points",
			"gold",
			"awarded_at",
			"description",
		],
		filters={"user": frappe.session.user},
		order_by="awarded_at desc",
		limit=limit,
	)
	return {
		"todos": get_unified_todos(limit),
		"plans": plans,
		"achievements": achievements,
	}


def _account_balances(company, to_date, limit=20):
	if not company or not _can_view_finance():
		return []
	use_permissions = frappe.has_permission("GL Entry", "read")
	getter = frappe.get_list if use_permissions else frappe.get_all
	try:
		rows = getter(
			"GL Entry",
			filters={
				"company": company,
				"posting_date": ["<=", str(to_date)],
				"is_cancelled": 0,
			},
			fields=[
				"account",
				{"SUM": "debit", "as": "debit"},
				{"SUM": "credit", "as": "credit"},
			],
			group_by="account",
			order_by="modified desc",
			limit_page_length=200,
		)
	except Exception:
		return []

	accounts = {
		row.name: row
		for row in frappe.get_all(
			"Account",
			filters={"company": company, "is_group": 0},
			fields=["name", "account_number", "account_name", "root_type"],
		)
	}
	result = []
	for row in rows:
		account = accounts.get(row.account)
		if not account:
			continue
		balance = flt(row.credit) - flt(row.debit) if account.root_type in ("Income", "Liability", "Equity") else flt(row.debit) - flt(row.credit)
		if not balance:
			continue
		result.append(
			{
				"name": account.name,
				"code": account.account_number or "",
				"label": account.account_name or account.name,
				"root_type": account.root_type,
				"balance": balance,
				"route": f"/app/account/{quote(account.name)}",
			}
		)
	result.sort(key=lambda item: abs(item["balance"]), reverse=True)
	return result[: max(1, min(int(limit or 20), 50))]


@frappe.whitelist()
def get_mobile_finance():
	"""Return permission-aware ERPNext finance data for the mobile finance page."""
	_require_login()
	today = getdate(nowdate())
	month_start = get_first_day(today)
	company = _default_company()
	currency = frappe.db.get_value("Company", company, "default_currency") if company else None
	currency = currency or frappe.db.get_single_value("Global Defaults", "default_currency") or "CNY"

	available = bool(company and _can_view_finance())
	balance = {"assets": None, "liabilities": None, "equity": None}
	if available:
		try:
			balance = {
				"assets": _sum_gl("Asset", company, "1900-01-01", today, frappe.has_permission("GL Entry", "read")),
				"liabilities": -_sum_gl("Liability", company, "1900-01-01", today, frappe.has_permission("GL Entry", "read")),
				"equity": -_sum_gl("Equity", company, "1900-01-01", today, frappe.has_permission("GL Entry", "read")),
			}
		except Exception:
			available = False
			frappe.log_error(title="I-ONE Mobile Finance Balance", message=frappe.get_traceback())

	month = _finance_summary(month_start, today, company)
	receivable = _safe_sum(
		"Sales Invoice",
		"outstanding_amount",
		{"docstatus": 1, "company": company},
	)
	payable = _safe_sum(
		"Purchase Invoice",
		"outstanding_amount",
		{"docstatus": 1, "company": company},
	)
	receivable_count = _safe_count(
		"Sales Invoice",
		{"docstatus": 1, "company": company, "outstanding_amount": [">", 0]},
	)
	payable_count = _safe_count(
		"Purchase Invoice",
		{"docstatus": 1, "company": company, "outstanding_amount": [">", 0]},
	)

	weekly = []
	for offset in range(6, -1, -1):
		day = add_days(today, -offset)
		summary = _finance_summary(day, day, company)
		weekly.append(
			{
				"date": str(day),
				"income": summary["income"] if summary["available"] else None,
			}
		)

	return {
		"available": available,
		"company": company,
		"currency": currency,
		"as_of_date": str(today),
		"balance": balance,
		"month": month,
		"receivable": {"amount": receivable, "count": receivable_count},
		"payable": {"amount": payable, "count": payable_count},
		"weekly_income": weekly,
		"accounts": _account_balances(company, today),
		"routes": {
			"accounting": "/app/accounting",
			"receivable": "/app/query-report/Accounts%20Receivable",
			"payable": "/app/query-report/Accounts%20Payable",
		},
	}


@frappe.whitelist()
def get_mobile_activity(limit=40):
	"""Return live AI work and run logs instead of a simulated timeline."""
	_require_login()
	limit = max(1, min(int(limit or 40), 100))
	tasks = _safe_rows(
		"I-ONE AI Task",
		[
			"name",
			"title",
			"status",
			"priority",
			"progress",
			"assigned_agent",
			"started_at",
			"completed_at",
			"modified",
			"error_message",
		],
		order_by="modified desc",
		limit=limit,
	)
	logs = _safe_rows(
		"I-ONE AI Run Log",
		[
			"name",
			"task",
			"agent",
			"event_type",
			"level",
			"duration_ms",
			"message",
			"model_name",
			"creation",
		],
		order_by="creation desc",
		limit=limit,
	)
	for task in tasks:
		task["route"] = f"/app/i-one-ai-task/{quote(task['name'])}"
	return {
		"tasks": tasks,
		"logs": logs,
		"stats": {
			"total": len(tasks),
			"completed": sum(1 for task in tasks if task.get("status") == "已完成"),
			"running": sum(1 for task in tasks if task.get("status") in ("已排队", "执行中", "等待确认")),
			"failed": sum(1 for task in tasks if task.get("status") == "执行失败"),
		},
	}


@frappe.whitelist()
def get_mobile_profile():
	"""Return the signed-in user's company, application, and achievement profile."""
	_require_login()
	bootstrap = get_bootstrap()
	company_name = _default_company()
	company = {}
	if company_name and frappe.db.exists("DocType", "Company") and frappe.has_permission("Company", "read"):
		meta = frappe.get_meta("Company")
		candidate_fields = [
			"name",
			"company_name",
			"abbr",
			"default_currency",
			"country",
			"tax_id",
			"date_of_establishment",
			"domain",
		]
		fields = [field for field in candidate_fields if field == "name" or meta.has_field(field)]
		company = frappe.db.get_value("Company", company_name, fields, as_dict=True) or {}

	achievements = _safe_rows(
		"I-ONE Achievement",
		["name", "title", "achievement_type", "points", "gold", "awarded_at", "description"],
		filters={"user": frappe.session.user},
		order_by="awarded_at desc",
		limit=20,
	)
	return {
		"user": bootstrap["user"],
		"company": dict(company),
		"employee_count": _safe_count("Employee", {"status": "Active"}),
		"department_count": _safe_count("Department", {"is_group": 0}),
		"apps": bootstrap["apps"],
		"achievements": achievements,
		"totals": {
			"points": sum(int(item.get("points") or 0) for item in achievements),
			"gold": sum(int(item.get("gold") or 0) for item in achievements),
		},
	}


def _mobile_notification_log_items(limit):
    """Expose the user's Frappe Notification Log to the mobile client."""
    rows = _safe_rows(
        "Notification Log",
        [
            "name",
            "subject",
            "email_content",
            "type",
            "document_type",
            "document_name",
            "link",
            "read",
            "creation",
        ],
        filters={"for_user": frappe.session.user},
        order_by="creation desc",
        limit=limit,
    )
    items = []
    for row in rows:
        notification_id = str(row.get("name") or "").strip()
        if not notification_id:
            continue
        message = strip_html(row.get("email_content") or row.get("subject") or "收到新的站点通知")
        title = row.get("subject") or "child.myyr.top 通知"
        is_attendance = any(
            marker in f"{title} {message}"
            for marker in ("考勤", "签到", "打卡", "靠勤")
        )
        items.append(
            {
                # Attendance notifications use the attendance namespace so the
                # mobile client can surface a first-sync local notification.
                "id": (
                    f"attendance:notification:{notification_id}"
                    if is_attendance
                    else f"notification-log:{notification_id}"
                ),
                "title": title,
                "message": str(message),
                "priority": "High" if not row.get("read") else "Normal",
                "status": "未读" if not row.get("read") else "已读",
                "source": "靠勤/教师考勤" if is_attendance else "child.myyr.top",
                "route": row.get("link") or "",
                "created_at": row.get("creation"),
            }
        )
    return items


def _teacher_checkin_notification_items():
    """Return today's Employee Checkin result for the signed-in teacher."""
    doctype = "Employee Checkin"
    if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
        return []

    employee = frappe.db.get_value(
        "Employee",
        {"user_id": frappe.session.user, "status": "Active"},
        "name",
    )
    if not employee:
        return []

    day = nowdate()
    rows = _safe_rows(
        doctype,
        ["name", "time", "log_type", "device_id", "modified"],
        filters={
            "employee": employee,
            "time": ["between", [f"{day} 00:00:00", f"{add_days(day, 1)} 00:00:00"]],
        },
        order_by="time desc",
        limit=20,
    )
    if not rows:
        return []

    latest = rows[0]
    latest_time = str(latest.get("time") or "")
    latest_time = latest_time.replace("T", " ")
    if "." in latest_time:
        latest_time = latest_time.split(".", 1)[0]
    log_type = str(latest.get("log_type") or "").upper()
    direction = f"（{log_type}）" if log_type else ""
    return [
        {
            "id": f"attendance:{day}:{latest.get('name') or latest_time}",
            "title": "教师签到结果",
            "message": f"今日已记录 {len(rows)} 次考勤，最近签到：{latest_time}{direction}",
            "priority": "High",
            "status": "已签到",
            "source": "靠勤/教师考勤",
            "route": f"/app/employee-checkin/{quote(str(latest.get('name') or ''))}",
            "created_at": latest.get("modified") or latest.get("time"),
        }
    ]


@frappe.whitelist()
def get_mobile_notifications(limit=50):
	"""Return permission-filtered site, teacher check-in, ToDo and approval notifications."""
	_require_login()
	limit = max(1, min(int(limit or 50), 100))
	items = []
	items.extend(_mobile_notification_log_items(limit))
	items.extend(_teacher_checkin_notification_items())
	for row in _safe_rows(
		"ToDo",
		["name", "description", "status", "priority", "date", "reference_type", "reference_name", "modified"],
		filters={"allocated_to": frappe.session.user, "status": "Open"},
		order_by="date asc, modified desc",
		limit=limit,
	):
		items.append(
			{
				"id": f"todo:{row['name']}",
				"title": row.get("description") or row.get("reference_name") or "待办事项",
				"message": f"{row.get('reference_type') or 'Frappe'} 待办",
				"priority": row.get("priority") or "Medium",
				"status": "待处理",
				"due_date": row.get("date"),
				"source": "Frappe ToDo",
				"route": f"/app/todo/{quote(row['name'])}",
			}
		)

	for row in _safe_rows(
		"I-ONE Approval Request",
		["name", "request_summary", "risk_level", "status", "task", "expires_at", "modified"],
		filters={"approver": frappe.session.user, "status": "待审批"},
		order_by="modified desc",
		limit=limit,
	):
		items.append(
			{
				"id": f"approval:{row['name']}",
				"title": row.get("request_summary") or "AI 执行审批",
				"message": f"关联任务：{row.get('task') or '-'}",
				"priority": row.get("risk_level") or "中",
				"status": row.get("status"),
				"due_date": row.get("expires_at"),
				"source": "I-ONE 审批",
				"route": f"/app/i-one-approval-request/{quote(row['name'])}",
			}
		)
	return {"notifications": items[:limit]}


@frappe.whitelist()
def get_mobile_channels(limit=50):
	_require_login()
	channels = _safe_rows(
		"I-ONE Channel",
		[
			"name",
			"channel_name",
			"channel_type",
			"status",
			"account_name",
			"last_published_at",
			"modified",
		],
		limit=limit,
	)
	jobs = _safe_rows(
		"I-ONE Publish Job",
		["name", "title", "channel", "status", "scheduled_at", "published_at", "result_url", "modified"],
		limit=limit,
	)
	return {"channels": channels, "jobs": jobs}


@frappe.whitelist(methods=["POST"])
def create_mobile_channel(channel_name, channel_type, account_name=None):
	_require_login()
	if not frappe.has_permission("I-ONE Channel", "create"):
		frappe.throw(_("您没有创建渠道的权限。"), frappe.PermissionError)
	doc = frappe.get_doc(
		{
			"doctype": "I-ONE Channel",
			"channel_name": str(channel_name or "").strip(),
			"channel_type": str(channel_type or "").strip(),
			"account_name": str(account_name or "").strip(),
			"status": "启用",
		}
	)
	doc.insert()
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def create_mobile_publish_jobs(content, channels):
	_require_login()
	if not frappe.has_permission("I-ONE Publish Job", "create"):
		frappe.throw(_("您没有创建发布任务的权限。"), frappe.PermissionError)
	channel_names = frappe.parse_json(channels) if isinstance(channels, str) else channels
	if not isinstance(channel_names, list) or not channel_names:
		frappe.throw(_("请至少选择一个发布渠道。"))
	result = []
	for channel in channel_names[:20]:
		doc = frappe.get_doc(
			{
				"doctype": "I-ONE Publish Job",
				"title": str(content or "").strip()[:80] or _("移动端发布任务"),
				"channel": channel,
				"status": "待发布",
				"content": str(content or "").strip(),
			}
		)
		doc.insert()
		result.append(doc.name)
	return {"jobs": result}


def _evaluation_dimensions(value):
	try:
		data = frappe.parse_json(value) if value else {}
	except Exception:
		data = {}
	if not isinstance(data, dict):
		data = {}
	return [
		{"dimension": key, "score": flt(data.get(key))}
		for key in ("accuracy", "completeness", "speed", "satisfaction")
	]


@frappe.whitelist()
def get_mobile_evaluations(limit=100):
	_require_login()
	rows = _safe_rows(
		"I-ONE Evaluation",
		["name", "task", "agent", "evaluator", "score", "grade", "evaluated_at", "dimensions_json", "comments"],
		order_by="evaluated_at desc",
		limit=limit,
	)
	task_names = list({row.get("task") for row in rows if row.get("task")})
	agent_ids = list({row.get("agent") for row in rows if row.get("agent")})
	task_titles = {
		row["name"]: row.get("title")
		for row in _safe_rows(
			"I-ONE AI Task",
			fields=["name", "title"],
			filters={"name": ["in", task_names]},
			limit=len(task_names),
		)
	} if task_names else {}
	agent_names = {
		row["name"]: row.get("agent_name")
		for row in _safe_rows(
			"I-ONE Agent",
			fields=["name", "agent_name"],
			filters={"name": ["in", agent_ids]},
			limit=len(agent_ids),
		)
	} if agent_ids else {}
	for row in rows:
		row["task_title"] = task_titles.get(row.get("task")) or row.get("task")
		row["agent_name"] = agent_names.get(row.get("agent")) or row.get("agent") or "未分配"
		row["dimensions"] = _evaluation_dimensions(row.pop("dimensions_json", None))
	return {"evaluations": rows}


@frappe.whitelist()
def get_mobile_experiences(limit=50, category=None):
	_require_login()
	filters = {"status": "已发布"}
	if category:
		filters["category"] = category
	rows = _safe_rows(
		"I-ONE Experience",
		["name", "title", "category", "author_user", "status", "useful_count", "content", "tags", "modified"],
		filters=filters,
		limit=limit,
	)
	for row in rows:
		row["route"] = f"/app/i-one-experience/{quote(row['name'])}"
	return {"experiences": rows}


@frappe.whitelist(methods=["POST"])
def create_mobile_experience(title, content, category=None, tags=None):
	_require_login()
	if not frappe.has_permission("I-ONE Experience", "create"):
		frappe.throw(_("您没有发布经验的权限。"), frappe.PermissionError)
	doc = frappe.get_doc(
		{
			"doctype": "I-ONE Experience",
			"title": str(title or "").strip(),
			"content": str(content or "").strip(),
			"category": str(category or "").strip(),
			"tags": str(tags or "").strip(),
			"author_user": frappe.session.user,
			"status": "已发布",
		}
	)
	doc.insert()
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def mark_experience_useful(name):
	_require_login()
	doc = frappe.get_doc("I-ONE Experience", name)
	doc.check_permission("read")
	frappe.db.set_value("I-ONE Experience", doc.name, "useful_count", int(doc.useful_count or 0) + 1)
	return {"useful_count": int(doc.useful_count or 0) + 1}
