from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _

POLICY_DOCTYPE = "I-ONE Flow Execution Policy"

MODE_CONFIRM = "始终确认"
MODE_SELECTED = "指定工具自动执行"
MODE_ALL = "全部自动执行"

CHANNEL_DESK = "Desk Flow"
CHANNEL_AI_EMPLOYEE = "AI 员工"


@dataclass(frozen=True)
class ExecutionDecision:
	policy: str | None = None
	department: str | None = None
	mode: str = MODE_CONFIRM
	auto_tools: frozenset[str] = field(default_factory=frozenset)

	@property
	def auto_approve_all(self) -> bool:
		return self.mode == MODE_ALL

	def as_dict(self) -> dict[str, Any]:
		return {
			"policy": self.policy,
			"department": self.department,
			"mode": self.mode,
			"auto_tools": sorted(self.auto_tools),
			"auto_approve_all": self.auto_approve_all,
		}


def resolve_execution_policy(
	*,
	user: str | None = None,
	department: str | None = None,
	channel: str = CHANNEL_DESK,
) -> ExecutionDecision:
	if not frappe.db.exists("DocType", POLICY_DOCTYPE):
		return ExecutionDecision(department=department)

	department = department or _user_department(user or frappe.session.user)
	candidates = _department_candidates(department)
	if not candidates:
		return ExecutionDecision(department=department)

	apply_field = "apply_to_ai_employees" if channel == CHANNEL_AI_EMPLOYEE else "apply_to_desk"
	rows = frappe.get_all(
		POLICY_DOCTYPE,
		filters={
			"enabled": 1,
			apply_field: 1,
			"department": ["in", candidates],
		},
		fields=["name", "department", "execution_mode"],
	)
	by_department = {row.department: row for row in rows}
	for candidate in candidates:
		row = by_department.get(candidate)
		if not row:
			continue
		tools = frappe.get_all(
			"I-ONE Agent Tool",
			filters={
				"parent": row.name,
				"parenttype": POLICY_DOCTYPE,
				"parentfield": "auto_approved_tools",
			},
			pluck="tool",
		)
		return ExecutionDecision(
			policy=row.name,
			department=row.department,
			mode=row.execution_mode or MODE_CONFIRM,
			auto_tools=frozenset(tool for tool in tools if tool),
		)

	return ExecutionDecision(department=department)


def prepare_session_execution(
	session: Any,
	*,
	user: str | None = None,
	department: str | None = None,
	channel: str = CHANNEL_DESK,
	fallback_auto_approve: bool = False,
	force_confirmation: bool = False,
) -> tuple[bool, ExecutionDecision]:
	decision = resolve_execution_policy(user=user, department=department, channel=channel)
	if force_confirmation:
		return False, decision
	if not decision.policy:
		return fallback_auto_approve, decision
	return apply_runtime_policy(session, decision), decision


def apply_runtime_policy(session: Any, decision: ExecutionDecision) -> bool:
	if decision.auto_approve_all:
		return True
	if decision.mode != MODE_SELECTED or not decision.auto_tools:
		return False

	runtime = getattr(session, "_runtime", None)
	for tool in getattr(runtime, "tools", []):
		if tool.name in decision.auto_tools:
			tool.requires_confirmation = False
	return False


@frappe.whitelist()
def get_current_execution_policy(agent: str | None = None) -> dict[str, Any]:
	decision = resolve_execution_policy(user=frappe.session.user, channel=CHANNEL_DESK)
	result = decision.as_dict()
	result["user"] = frappe.session.user
	result["agent"] = agent
	return result


@frappe.whitelist()
def start_run(
	input: str,
	agent: str | None = None,
	session: str | None = None,
	model: str | None = None,
	attachments: list[str] | str | None = None,
	stream: bool | str = False,
):
	"""Flow's Desk entry point with an optional department execution policy."""
	if not isinstance(input, str) or not input.strip():
		frappe.throw(_("Input is required."), title=_("Invalid Input"))

	from flow.api import api as flow_api
	from flow.lib.session import load_session, new_session
	from tongjianyun.flow_batch import (
		apply_batch_execution_guard,
		append_batch_policy,
		prepare_continuation_prompt,
	)
	from tongjianyun.flow_stream import install_flow_stream_heartbeat, keepalive_events

	install_flow_stream_heartbeat()
	stream = flow_api._is_truthy(stream)
	files = flow_api._parse_attachments(attachments)
	conversation = (
		load_session(session, agent=agent, model=model) if session else new_session(agent, model=model)
	)
	apply_batch_execution_guard(conversation._runtime)
	prepare_continuation_prompt(
		conversation,
		input,
		current_date=frappe.utils.today(),
	)
	if session:
		_sync_session_batch_policy(session, append_batch_policy)
	auto_approve, _decision = prepare_session_execution(
		conversation,
		user=frappe.session.user,
		channel=CHANNEL_DESK,
	)
	output = conversation.chat(
		input,
		attachments=files,
		auto_approve=auto_approve,
		stream=stream,
	)
	if not stream:
		return flow_api._summarize(output)

	response = flow_api._sse_response(keepalive_events(output))
	response.headers["Cache-Control"] = "no-cache, no-transform"
	response.headers["Content-Encoding"] = "identity"
	return response


def _sync_session_batch_policy(session: str, policy_builder: Any) -> None:
	"""Bring existing sessions forward without requiring users to start a new chat."""
	row = frappe.db.get_value(
		"Flow Session Message",
		{"parent": session, "role": "system"},
		["name", "content"],
		order_by="idx asc",
		as_dict=True,
	)
	if not row:
		return

	content = policy_builder(row.content)
	if content != row.content:
		frappe.db.set_value("Flow Session Message", row.name, "content", content)


def _user_department(user: str | None) -> str | None:
	if not user or user == "Guest" or not frappe.db.exists("DocType", "Department"):
		return None

	if frappe.db.exists("DocType", "Employee"):
		department = frappe.db.get_value(
			"Employee",
			{"user_id": user, "status": "Active"},
			"department",
			order_by="modified desc",
		)
		if department:
			return department

	department = frappe.defaults.get_user_default("Department")
	if department and frappe.db.exists("Department", department):
		return department

	permissions = frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": "Department", "is_default": 1},
		pluck="for_value",
		limit=2,
	)
	return permissions[0] if len(permissions) == 1 else None


def _department_candidates(department: str | None) -> list[str]:
	if not frappe.db.exists("DocType", "Department"):
		return []

	if department and frappe.db.exists("Department", department):
		node = frappe.db.get_value("Department", department, ["lft", "rgt"], as_dict=True)
		if node and node.lft is not None and node.rgt is not None:
			return frappe.get_all(
				"Department",
				filters={
					"disabled": 0,
					"lft": ["<=", node.lft],
					"rgt": [">=", node.rgt],
				},
				pluck="name",
				order_by="lft desc",
			)
		return [department]

	return frappe.get_all(
		"Department",
		filters={"disabled": 0, "is_group": 1, "parent_department": ["in", ["", None]]},
		pluck="name",
		order_by="lft asc",
	)
