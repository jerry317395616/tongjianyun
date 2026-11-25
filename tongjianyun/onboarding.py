import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

STEP_TYPE_MAP = {
	"欢迎页": "welcome",
	"单选题": "single",
	"多选题": "multiple",
	"资料页": "profile",
	"报告页": "report",
}


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("请先登录"), frappe.AuthenticationError)


def _parse_object(value, label):
	if value in (None, ""):
		return {}
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			frappe.throw(_("{0}不是有效的 JSON").format(label))
	if not isinstance(value, dict):
		frappe.throw(_("{0}必须是对象").format(label))
	return value


def _json_value(value, fallback):
	if not value:
		return fallback
	try:
		parsed = json.loads(value) if isinstance(value, str) else value
		return parsed if isinstance(parsed, type(fallback)) else fallback
	except (TypeError, ValueError):
		return fallback


def _get_active_flow():
	name = frappe.db.get_value(
		"I-ONE Onboarding Flow",
		{"status": "已发布", "is_default": 1},
		"name",
		order_by="modified desc",
	)
	if not name:
		name = frappe.db.get_value(
			"I-ONE Onboarding Flow",
			{"status": "已发布"},
			"name",
			order_by="is_default desc, modified desc",
		)
	if not name:
		frappe.throw(_("尚未发布手机端引导流程"))
	return frappe.get_doc("I-ONE Onboarding Flow", name)


def _serialize_flow(flow):
	options_by_step = {}
	for option in sorted(flow.options, key=lambda row: (row.sequence or 0, row.idx or 0)):
		options_by_step.setdefault(option.step_code, []).append(
			{
				"code": option.option_code,
				"label": option.label,
				"icon": option.icon or "",
				"description": option.description or "",
			}
		)

	steps = []
	for step in sorted(flow.steps, key=lambda row: (row.sequence or 0, row.idx or 0)):
		steps.append(
			{
				"code": step.step_code,
				"type": STEP_TYPE_MAP.get(step.step_type, "single"),
				"title": step.title,
				"description": step.description or "",
				"required": bool(step.required),
				"multiple": bool(step.multiple_select),
				"options": options_by_step.get(step.step_code, []),
			}
		)

	return {
		"code": flow.flow_code,
		"name": flow.flow_name,
		"version": flow.version,
		"welcome": {
			"badge": flow.welcome_badge or "I-ONE AI 智能经营系统",
			"title": flow.welcome_title,
			"description": flow.welcome_description or "",
		},
		"start_button_label": flow.start_button_label or "开始建立档案",
		"completion_button_label": flow.completion_button_label or "进入工作台",
		"steps": steps,
	}


def _record_for_user(flow, create=False):
	name = frappe.db.get_value(
		"I-ONE Onboarding Record",
		{"user": frappe.session.user, "flow": flow.name},
		"name",
	)
	if name:
		return frappe.get_doc("I-ONE Onboarding Record", name)
	if not create:
		return None
	return frappe.get_doc(
		{
			"doctype": "I-ONE Onboarding Record",
			"user": frappe.session.user,
			"flow": flow.name,
			"flow_version": flow.version,
			"status": "未开始",
			"current_step": "welcome",
		}
	).insert(ignore_permissions=True)


def _answers_from_record(record):
	if not record:
		return {}
	answers = {}
	for row in record.answers:
		selected = _json_value(row.selected_values_json, [])
		answers[row.step_code] = selected if selected else row.answer_text or ""
	return answers


def _align_record_with_flow(flow, record):
	if not record or cint(record.flow_version) == cint(flow.version):
		return record

	answers = _answers_from_record(record)
	steps_with_options = {row.step_code for row in flow.options}
	for step in sorted(flow.steps, key=lambda row: (row.sequence or 0, row.idx or 0)):
		if STEP_TYPE_MAP.get(step.step_type) not in {"single", "multiple"}:
			continue
		if step.step_code not in steps_with_options or answers.get(step.step_code):
			continue
		record.flow_version = flow.version
		record.status = "进行中"
		record.current_step = step.step_code
		record.completed_at = None
		break

	return record


def _profile_from_record(record):
	if not record:
		return {
			"company_name": "",
			"display_name": "",
			"user_role": "",
			"city": "",
			"skipped_info": False,
		}
	return {
		"company_name": record.company_name or "",
		"display_name": record.display_name or "",
		"user_role": record.user_role or "",
		"city": record.city or "",
		"skipped_info": bool(record.skipped_info),
	}


def _report_from_record(record):
	if not record or not record.report_json:
		return None
	return _json_value(record.report_json, {}) or None


def _serialize_state(flow, record):
	return {
		"flow": _serialize_flow(flow),
		"progress": {
			"record": record.name if record else None,
			"status": record.status if record else "未开始",
			"completed": bool(record and record.status == "已完成"),
			"current_step": record.current_step if record else "welcome",
			"answers": _answers_from_record(record),
			"profile": _profile_from_record(record),
			"report": _report_from_record(record),
		},
	}


def _normalize_answers(flow, raw_answers, require_complete=False):
	answers = _parse_object(raw_answers, _("引导答案"))
	steps = {row.step_code: row for row in flow.steps}
	options = {}
	for row in flow.options:
		options.setdefault(row.step_code, {})[row.option_code] = row

	normalized = {}
	for step_code, value in answers.items():
		if step_code not in steps:
			continue
		step = steps[step_code]
		if STEP_TYPE_MAP.get(step.step_type) not in {"single", "multiple"}:
			continue
		values = value if isinstance(value, list) else [value]
		values = [str(item).strip() for item in values if str(item).strip()]
		if not step.multiple_select and len(values) > 1:
			frappe.throw(_("步骤“{0}”只能选择一项").format(step.title))
		invalid = [item for item in values if item not in options.get(step_code, {})]
		if invalid:
			frappe.throw(_("步骤“{0}”包含无效选项").format(step.title))
		normalized[step_code] = values

	if require_complete:
		for step in flow.steps:
			if step.required and STEP_TYPE_MAP.get(step.step_type) in {"single", "multiple"}:
				if not normalized.get(step.step_code):
					frappe.throw(_("请完成“{0}”").format(step.title))
	return normalized


def _normalize_profile(raw_profile):
	profile = _parse_object(raw_profile, _("经营档案"))
	aliases = {
		"company_name": "companyName",
		"display_name": "userName",
		"user_role": "userRole",
		"city": "city",
		"skipped_info": "skippedInfo",
	}
	result = {}
	for fieldname, alias in aliases.items():
		value = profile.get(fieldname, profile.get(alias))
		if fieldname == "skipped_info":
			result[fieldname] = cint(value)
		else:
			result[fieldname] = str(value or "").strip()[:140]
	return result


def _write_answers(record, answers):
	record.set("answers", [])
	for step_code, values in answers.items():
		record.append(
			"answers",
			{
				"step_code": step_code,
				"selected_values_json": json.dumps(values, ensure_ascii=False),
			},
		)


def _option_for(flow, step_code, option_code):
	for row in flow.options:
		if row.step_code == step_code and row.option_code == option_code:
			return row
	return None


def _option_label(flow, step_code, option_code, fallback=""):
	option = _option_for(flow, step_code, option_code)
	return option.label if option else fallback


def _build_report(flow, answers, profile):
	advantage = (answers.get("advantage") or [None])[0]
	preset = _option_for(flow, "advantage", advantage) if advantage else None
	industry_code = (answers.get("industry") or [None])[0]
	industry = _option_label(flow, "industry", industry_code, "通用")
	report_type = (preset.report_type if preset else None) or flow.default_report_type or "综合经营型"
	description = (
		(preset.report_description if preset else None)
		or flow.default_report_description
		or "根据你的经营档案生成了适合当前阶段的协作方案。"
	)
	role = profile.get("user_role") or "创始人/总经理"
	return {
		"type": report_type,
		"description": description,
		"strengths": _json_value(
			preset.strengths_json if preset else None,
			_json_value(flow.default_strengths_json, []),
		),
		"team": _json_value(preset.team_json if preset else None, _json_value(flow.default_team_json, [])),
		"automation": _json_value(
			preset.automation_json if preset else None,
			_json_value(flow.default_automation_json, []),
		),
		"manual": _json_value(
			preset.manual_json if preset else None,
			_json_value(flow.default_manual_json, []),
		),
		"role": f"{role} · 业务决策与客户维护",
		"industry": industry,
	}


@frappe.whitelist()
def get_mobile_onboarding():
	_require_login()
	flow = _get_active_flow()
	record = _align_record_with_flow(flow, _record_for_user(flow))
	return _serialize_state(flow, record)


@frappe.whitelist(methods=["POST"])
def save_mobile_onboarding_progress(current_step=None, answers=None, profile=None):
	_require_login()
	flow = _get_active_flow()
	normalized_answers = _normalize_answers(flow, answers)
	normalized_profile = _normalize_profile(profile)
	record = _record_for_user(flow, create=True)
	record.flow_version = flow.version
	record.current_step = current_step or record.current_step or "welcome"
	if record.status != "已完成":
		record.status = "进行中"
		record.started_at = record.started_at or now_datetime()
	_write_answers(record, normalized_answers)
	for fieldname, value in normalized_profile.items():
		setattr(record, fieldname, value)
	record.save(ignore_permissions=True)
	return _serialize_state(flow, record)


@frappe.whitelist(methods=["POST"])
def prepare_mobile_onboarding_report(answers=None, profile=None):
	_require_login()
	flow = _get_active_flow()
	normalized_answers = _normalize_answers(flow, answers, require_complete=True)
	normalized_profile = _normalize_profile(profile)
	record = _record_for_user(flow, create=True)
	report = _build_report(flow, normalized_answers, normalized_profile)
	record.flow_version = flow.version
	record.status = "进行中"
	record.current_step = "report"
	record.started_at = record.started_at or now_datetime()
	record.report_type = report["type"]
	record.report_description = report["description"]
	record.report_json = json.dumps(report, ensure_ascii=False)
	_write_answers(record, normalized_answers)
	for fieldname, value in normalized_profile.items():
		setattr(record, fieldname, value)
	record.save(ignore_permissions=True)
	return _serialize_state(flow, record)


@frappe.whitelist(methods=["POST"])
def complete_mobile_onboarding(answers=None, profile=None):
	_require_login()
	flow = _get_active_flow()
	normalized_answers = _normalize_answers(flow, answers, require_complete=True)
	normalized_profile = _normalize_profile(profile)
	record = _record_for_user(flow, create=True)
	report = _build_report(flow, normalized_answers, normalized_profile)
	record.flow_version = flow.version
	record.status = "已完成"
	record.current_step = "report"
	record.started_at = record.started_at or now_datetime()
	record.completed_at = now_datetime()
	record.report_type = report["type"]
	record.report_description = report["description"]
	record.report_json = json.dumps(report, ensure_ascii=False)
	_write_answers(record, normalized_answers)
	for fieldname, value in normalized_profile.items():
		setattr(record, fieldname, value)
	record.save(ignore_permissions=True)
	return _serialize_state(flow, record)


@frappe.whitelist(methods=["POST"])
def reset_mobile_onboarding():
	_require_login()
	flow = _get_active_flow()
	record = _record_for_user(flow)
	if record:
		record.delete(ignore_permissions=True)
	return _serialize_state(flow, None)
