import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

ACTIVE_STATUSES = {"试用", "在职"}
PUBLISHER_ROLES = {"System Manager", "I-ONE Manager"}
PROTECTED_ROLES = {"Administrator", "System Manager"}


class IONEAgent(Document):
	def before_insert(self):
		self._set_defaults()

	def validate(self):
		self._set_defaults()
		self._validate_code()
		self._validate_limits()
		self._validate_schedule()
		self._validate_roles()

	def on_update(self):
		if self.flow_agent and self.service_user and not frappe.flags.in_migrate:
			self.sync_runtime_resources()

	def _set_defaults(self):
		self.status = {"启用": "在职", "停用": "离职"}.get(self.status, self.status or "草稿")
		self.operating_mode = self.operating_mode or "辅助"
		self.daily_task_limit = cint(self.daily_task_limit or 50)
		self.max_retries = cint(self.max_retries or 2)
		self.max_iterations = cint(self.max_iterations or 20)
		if not self.flow_model and _flow_available():
			self.flow_model = _default_flow_model()

	def _validate_code(self):
		self.agent_code = (self.agent_code or "").strip().lower()
		if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.agent_code):
			frappe.throw(_("员工编码只能包含小写字母、数字和短横线，且不能以短横线开头或结尾。"))

	def _validate_limits(self):
		if self.daily_task_limit < 1:
			frappe.throw(_("每日任务上限必须大于 0。"))
		if self.max_retries < 0:
			frappe.throw(_("失败重试次数不能小于 0。"))
		if self.max_iterations < 1:
			frappe.throw(_("单次最大推理轮数必须大于 0。"))

	def _validate_schedule(self):
		if self.schedule_enabled and (not self.cron_expression or not self.schedule_prompt):
			frappe.throw(_("启用定时任务后，必须填写 Cron 表达式和定时任务指令。"))

	def _validate_roles(self):
		roles = {row.role for row in self.roles if row.role}
		invalid = roles.intersection(PROTECTED_ROLES)
		if invalid:
			frappe.throw(_("AI 员工不能使用高权限角色：{0}").format("、".join(sorted(invalid))))

	def sync_runtime_resources(self):
		_assert_flow_available()
		if not self.flow_model:
			frappe.throw(_("请先为 AI 员工选择大模型。"))

		service_user = self._sync_service_user()
		flow_agent = self._sync_flow_agent()
		flow_trigger = self._sync_flow_trigger(flow_agent, service_user)

		updates = {}
		if self.service_user != service_user:
			updates["service_user"] = service_user
		if self.flow_agent != flow_agent:
			updates["flow_agent"] = flow_agent
		if (self.flow_trigger or None) != (flow_trigger or None):
			updates["flow_trigger"] = flow_trigger
		if updates:
			self.db_set(updates, update_modified=False)
			for fieldname, value in updates.items():
				self.set(fieldname, value)

	def _sync_service_user(self):
		email = (self.service_user_email or f"ai-{self.agent_code}@myyr.top").strip().lower()
		if email == "administrator":
			frappe.throw(_("AI 员工不能使用 Administrator 身份。"))

		if self.service_user and frappe.db.exists("User", self.service_user):
			user = frappe.get_doc("User", self.service_user)
		elif frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.new_doc("User")
			user.email = email
			user.send_welcome_email = 0
			user.user_type = "System User"

		user.first_name = self.agent_name
		user.enabled = int(self.status in ACTIVE_STATUSES)
		user.user_type = "System User"
		managed_roles = {"I-ONE AI Employee"}
		managed_roles.update(row.role for row in self.roles if row.role)
		user.set("roles", [{"role": role} for role in sorted(managed_roles)])
		user.save(ignore_permissions=True)
		frappe.db.delete(
			"Has Role",
			{
				"parent": user.name,
				"parenttype": "User",
				"role": ["not in", sorted(managed_roles)],
			},
		)
		frappe.db.set_value("User", user.name, "user_type", "System User", update_modified=False)
		frappe.clear_cache(user=user.name)

		if self.company and not frappe.db.exists(
			"User Permission",
			{"user": user.name, "allow": "Company", "for_value": self.company},
		):
			frappe.get_doc(
				{
					"doctype": "User Permission",
					"user": user.name,
					"allow": "Company",
					"for_value": self.company,
					"apply_to_all_doctypes": 1,
				}
			).insert(ignore_permissions=True)

		if self.service_user_email != email:
			self.db_set("service_user_email", email, update_modified=False)
			self.service_user_email = email
		return user.name

	def _sync_flow_agent(self):
		if self.flow_agent and frappe.db.exists("Flow Agent", self.flow_agent):
			flow_agent = frappe.get_doc("Flow Agent", self.flow_agent)
		else:
			title = f"I-ONE AI Employee - {self.agent_code}"
			flow_agent = (
				frappe.get_doc("Flow Agent", title)
				if frappe.db.exists("Flow Agent", title)
				else frappe.new_doc("Flow Agent")
			)
			flow_agent.title = title

		flow_agent.enabled = int(self.status in ACTIVE_STATUSES)
		flow_agent.model = self.flow_model
		flow_agent.max_iterations = self.max_iterations
		flow_agent.instructions = self.build_flow_instructions()
		tools = [row.tool for row in self.tools if row.tool]
		if not tools:
			tools = [
				slug
				for slug in ("describe", "read", "execute")
				if frappe.db.exists("Flow Tool", slug)
			]
		flow_agent.set("tools", [{"tool": tool} for tool in tools])
		flow_agent.set(
			"knowledge_bases",
			[{"knowledge_base": row.knowledge_base} for row in self.knowledge_bases if row.knowledge_base],
		)
		flow_agent.save(ignore_permissions=True)
		return flow_agent.name

	def _sync_flow_trigger(self, flow_agent, service_user):
		if not self.schedule_enabled:
			if self.flow_trigger and frappe.db.exists("Flow Trigger", self.flow_trigger):
				trigger = frappe.get_doc("Flow Trigger", self.flow_trigger)
				if trigger.enabled:
					trigger.enabled = 0
					trigger.save(ignore_permissions=True)
			return self.flow_trigger

		if self.flow_trigger and frappe.db.exists("Flow Trigger", self.flow_trigger):
			trigger = frappe.get_doc("Flow Trigger", self.flow_trigger)
		else:
			title = f"I-ONE Schedule - {self.agent_code}"
			trigger = (
				frappe.get_doc("Flow Trigger", title)
				if frappe.db.exists("Flow Trigger", title)
				else frappe.new_doc("Flow Trigger")
			)
			trigger.title = title

		trigger.enabled = int(self.status in ACTIVE_STATUSES)
		trigger.agent = flow_agent
		trigger.event = "Scheduled"
		trigger.auto_approve = int(self.operating_mode == "自动")
		trigger.run_as = service_user
		trigger.cron_expression = self.cron_expression
		trigger.prompt_template = self.schedule_prompt
		trigger.save(ignore_permissions=True)
		return trigger.name

	def build_flow_instructions(self):
		modules = _split_lines(self.allowed_modules)
		doctypes = _split_lines(self.allowed_doctypes)
		parts = [
			f"你是 I-ONE 中的企业 AI 员工“{self.agent_name}”（员工编码：{self.agent_code}）。",
			f"岗位类型：{self.agent_type or '自定义岗位'}。",
			f"所属公司：{self.company or '未限定'}。",
			f"所属部门：{self.department or '未限定'}。",
			f"工作模式：{self.operating_mode}。",
			"所有操作必须遵守当前服务用户在 Frappe 中的真实权限，不得规避权限、伪造结果或声称完成未完成的操作。",
			"遇到信息不足、权限不足、关键业务写入或不可逆操作时，必须明确说明并等待人工确认。",
		]
		if self.responsibilities:
			parts.append(f"岗位职责：\n{self.responsibilities}")
		if modules:
			parts.append(f"允许访问的应用或模块：{', '.join(modules)}。")
		if doctypes:
			parts.append(f"允许访问的单据类型：{', '.join(doctypes)}。")
		if self.instructions:
			parts.append(f"补充工作指令：\n{self.instructions}")
		return "\n\n".join(parts)


def _split_lines(value):
	return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _flow_available():
	return "flow" in frappe.get_installed_apps() and frappe.db.exists("DocType", "Flow Agent")


def _assert_flow_available():
	if not _flow_available():
		frappe.throw(_("当前站点尚未安装并启用 Frappe Flow。"))


def _default_flow_model():
	return frappe.db.get_value("Flow Model", {"enabled": 1}, "name", order_by="creation asc")


def _assert_can_publish():
	if not PUBLISHER_ROLES.intersection(frappe.get_roles()):
		frappe.throw(_("只有 I-ONE 管理员或系统管理员可以发布 AI 员工。"), frappe.PermissionError)


@frappe.whitelist()
def publish_ai_employee(name):
	_assert_can_publish()
	employee = frappe.get_doc("I-ONE Agent", name)
	employee.check_permission("write")
	if employee.status in {"草稿", "暂停", "离职"}:
		employee.status = "试用"
	employee.sync_runtime_resources()
	employee.db_set(
		{
			"status": employee.status,
			"published_at": now_datetime(),
		},
		update_modified=True,
	)
	frappe.db.commit()
	return {
		"name": employee.name,
		"status": employee.status,
		"service_user": employee.service_user,
		"flow_agent": employee.flow_agent,
		"flow_trigger": employee.flow_trigger,
	}


@frappe.whitelist()
def queue_trial_task(name, prompt):
	_assert_can_publish()
	employee = frappe.get_doc("I-ONE Agent", name)
	employee.check_permission("read")
	if not employee.flow_agent:
		frappe.throw(_("请先发布 AI 员工。"))
	if employee.status not in ACTIVE_STATUSES:
		frappe.throw(_("只有试用或在职状态的 AI 员工可以执行任务。"))

	from tongjianyun.ai import queue_ai_task

	return queue_ai_task(
		title=f"{employee.agent_name}试运行",
		prompt=prompt,
		assigned_agent=employee.name,
		priority="普通",
		approval_required=0,
	)
