from __future__ import annotations

from typing import Any

from ione_core.mcp.audit import audited_tool
from ione_core.mcp.identity import as_verified_actor
from ione_core.mcp.runtime import ToolAnnotations
from ione_core.mcp.server import mcp

from tongjianyun.nutrition_rule_service import (
    create_rule_draft,
    list_rule_sets,
    preview_rule_set,
    publish_rule_set,
    rollback_rule_set,
    submit_rule_set,
)
from tongjianyun.nutrition_standard_service import (
    explain_nutrition_standard,
    get_weekly_nutrition_analysis_context,
)


READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_explain_tongjianyun_nutrition_standard", "解释营养标准计算")
def frappe_explain_tongjianyun_nutrition_standard(
    metric: str = "energy",
    recipe: str | None = None,
    standard_mode: str = "自动（按学生档案）",
    student_groups: list[str] | None = None,
    age_group: str = "4–6岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
    actor_token: str | None = None,
) -> dict[str, Any]:
    """解释童健云当前报表所用全日标准及园内目标的真实计算过程。

    自动模式会按食谱开始日逐名读取学生年龄、性别和官方参考值后求加权平均；
    手动模式会解释指定年龄段和性别的平均过程。应优先调用本工具，不要搜索
    Harness 自身源码或凭常识猜测。

    Args:
        metric: 指标键，热量使用 energy。
        recipe: 食谱编号；留空使用最新食谱。
        standard_mode: 自动（按学生档案）或手动估算。
        student_groups: 自动模式下可选的班级编号列表；留空统计全园启用学生。
        age_group: 手动模式的年龄范围。
        gender: 手动模式的性别范围。
        garden_ratio: 园内供给比例，30–100，默认80。
        actor_token: IONE Agent 自动注入的当前 Frappe 用户身份令牌。
    """
    return explain_nutrition_standard(
        metric,
        recipe,
        standard_mode,
        student_groups,
        age_group,
        gender,
        garden_ratio,
    )


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_get_tongjianyun_weekly_nutrition_analysis", "读取周食谱营养分析")
def frappe_get_tongjianyun_weekly_nutrition_analysis(
    recipe: str | None = None,
    standard_mode: str = "自动（按学生档案）",
    student_groups: list[str] | None = None,
    age_group: str = "4–6岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
    actor_token: str | None = None,
) -> dict[str, Any]:
    """按当前用户权限读取真实食谱、学生范围和当前规则，实时生成周营养分析。

    Args:
        recipe: 食谱编号；留空使用最新食谱。
        standard_mode: 自动（按学生档案）或手动估算。
        student_groups: 自动模式下可选的班级编号列表。
        age_group: 手动模式的年龄范围。
        gender: 手动模式的性别范围。
        garden_ratio: 园内供给比例，30–100，默认80。
        actor_token: IONE Agent 自动注入的当前 Frappe 用户身份令牌。
    """
    return get_weekly_nutrition_analysis_context(
        recipe,
        standard_mode,
        student_groups,
        age_group,
        gender,
        garden_ratio,
    )


DRAFT_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)
PUBLISH_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
)


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_list_tongjianyun_nutrition_rules", "读取营养规则")
def frappe_list_tongjianyun_nutrition_rules(
    status: str | None = None,
    limit: int = 20,
    actor_token: str | None = None,
) -> dict[str, Any]:
    """列出童健云营养计算规则及当前生效版本。

    Args:
        status: 可选状态筛选：草稿、待审核、已发布或已停用。
        limit: 最多返回的规则数量，范围为 1 到 100。
        actor_token: IONE Agent 自动注入的当前 Frappe 用户身份令牌。
    """
    return list_rule_sets(status=status, limit=limit)


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_create_tongjianyun_nutrition_rule_draft", "创建营养规则草稿")
def frappe_create_tongjianyun_nutrition_rule_draft(
    title: str,
    changes: dict[str, Any],
    base_rule_set: str | None = None,
    change_reason: str | None = None,
    actor_token: str | None = None,
) -> dict[str, Any]:
    """基于当前或指定版本创建营养计算规则草稿，不会影响线上报表。

    Args:
        title: 新规则草稿名称。
        changes: 结构化变更，只允许公式、比例、阈值、供能系数和目标字段。
        base_rule_set: 可选的基础规则编号；留空时使用当前生效规则。
        change_reason: 变更原因和业务依据。
        actor_token: IONE Agent 自动注入的当前 Frappe 用户身份令牌。
    """
    return create_rule_draft(title, changes, base_rule_set, change_reason)


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_preview_tongjianyun_nutrition_rule", "试算营养规则")
def frappe_preview_tongjianyun_nutrition_rule(
    rule_set: str,
    recipe: str | None = None,
    actor_token: str | None = None,
) -> dict[str, Any]:
    """使用一份真实食谱对比当前规则与候选规则的营养计算结果。

    Args:
        rule_set: 待试算的营养规则编号。
        recipe: 食谱编号；留空时使用最新食谱。
        actor_token: IONE Agent 自动注入的当前 Frappe 用户身份令牌。
    """
    return preview_rule_set(rule_set, recipe)


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_submit_tongjianyun_nutrition_rule", "提交营养规则审核")
def frappe_submit_tongjianyun_nutrition_rule(
    rule_set: str,
    actor_token: str | None = None,
) -> dict[str, Any]:
    """将已试算的营养规则草稿提交审核，但不发布。

    Args:
        rule_set: 草稿规则编号。
        actor_token: IONE Agent 自动注入的当前 Frappe 用户身份令牌。
    """
    return submit_rule_set(rule_set)


@mcp.tool(annotations=PUBLISH_WRITE)
@as_verified_actor
@audited_tool("frappe_publish_tongjianyun_nutrition_rule", "发布营养规则")
def frappe_publish_tongjianyun_nutrition_rule(
    rule_set: str,
    confirmation: str,
    actor_token: str | None = None,
) -> dict[str, Any]:
    """发布待审核营养规则，仅管理员可执行，并需要明确二次确认。

    Args:
        rule_set: 待审核规则编号。
        confirmation: 必须精确填写“确认发布”。
        actor_token: IONE Agent 自动注入的当前 Frappe 用户身份令牌。
    """
    return publish_rule_set(rule_set, confirmation)


@mcp.tool(annotations=PUBLISH_WRITE)
@as_verified_actor
@audited_tool("frappe_rollback_tongjianyun_nutrition_rule", "回滚营养规则")
def frappe_rollback_tongjianyun_nutrition_rule(
    target_rule_set: str,
    confirmation: str,
    change_reason: str | None = None,
    actor_token: str | None = None,
) -> dict[str, Any]:
    """将历史营养规则复制为新版本并立即发布，仅管理员可执行。

    Args:
        target_rule_set: 要恢复的历史规则编号。
        confirmation: 必须精确填写“确认回滚”。
        change_reason: 回滚原因。
        actor_token: IONE Agent 自动注入的当前 Frappe 用户身份令牌。
    """
    return rollback_rule_set(target_rule_set, confirmation, change_reason)
