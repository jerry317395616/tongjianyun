"""Pure policy checks shared by Tongjianyun extension tooling and tests.

This module classifies a requested change.  It deliberately performs no Frappe
or database writes; actual extensions remain explicit, reviewable source files.
"""

from dataclasses import asdict, dataclass


EXTENSION_APP = "tongjianyun"

NON_STRUCTURAL_CHANGE_KINDS = frozenset(
	{
		"form-ui",
		"list-ui",
		"desk-page",
		"custom-page",
		"business-logic",
		"report",
		"workspace",
	}
)
STRUCTURAL_CHANGE_KINDS = frozenset({"add-field", "modify-field"})
FORBIDDEN_CHANGE_KINDS = frozenset({"add-doctype", "modify-upstream-doctype-json", "database-ddl"})


@dataclass(frozen=True)
class ExtensionDecision:
	"""Serializable decision returned before an extension is implemented."""

	change_kind: str
	owner_app: str
	structural_change: bool
	requires_explicit_confirmation: bool
	allowed: bool
	reason: str

	def as_dict(self) -> dict[str, object]:
		return asdict(self)


def evaluate_extension_change(change_kind: str, *, explicitly_confirmed: bool = False) -> ExtensionDecision:
	"""Classify one requested change without touching DocTypes or the database."""

	if change_kind in FORBIDDEN_CHANGE_KINDS:
		return ExtensionDecision(
			change_kind=change_kind,
			owner_app=EXTENSION_APP,
			structural_change=True,
			requires_explicit_confirmation=False,
			allowed=False,
			reason="该变更被部署策略永久禁止。",
		)

	if change_kind in STRUCTURAL_CHANGE_KINDS:
		return ExtensionDecision(
			change_kind=change_kind,
			owner_app=EXTENSION_APP,
			structural_change=True,
			requires_explicit_confirmation=True,
			allowed=explicitly_confirmed,
			reason=(
				"字段级影响已经明确确认，可以在 Tongjianyun fixture 中实施。"
				if explicitly_confirmed
				else "必须先预览目标字段、权限、数据迁移和回滚影响，并取得用户明确确认。"
			),
		)

	if change_kind not in NON_STRUCTURAL_CHANGE_KINDS:
		raise ValueError(f"未知的扩展变更类型：{change_kind}")

	return ExtensionDecision(
		change_kind=change_kind,
		owner_app=EXTENSION_APP,
		structural_change=False,
		requires_explicit_confirmation=False,
		allowed=True,
		reason="非结构业务扩展，只能在 Tongjianyun 应用内实施。",
	)
