"""Recipe execution coordinator using existing Comment audit records and RQ.

No new metadata. ERP documents and the successful audit record commit atomically.
Intermediate cache events explicitly describe uncommitted work, not completed facts.
"""
import base64
import json
import re
from html import unescape

import frappe
from frappe.utils import now_datetime

from tongjianyun import recipe_procurement as procurement
from tongjianyun.recipe_item_sync import source_snapshot

SUBJECT = "童健云食谱发布结算任务 v1"
STEPS = ["准备", "食材匹配", "校验人数与价格", "发布食谱", "采购需求", "采购订单", "收货", "发票", "付款", "完成"]


def _access(recipe, write=False):
    doc = procurement._read(procurement.RECIPE, recipe)
    if write:
        doc.check_permission("write")
        for dt in ("Material Request", "Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry"):
            for action in ("read", "create", "submit"):
                procurement._permission(dt, action)
        procurement._permission("Comment", "create")
        procurement._permission("Item", "read")
        procurement._permission("Item Price", "read")
    if doc.is_deleted or doc.workflow_status not in ("草稿", "已发布"):
        frappe.throw("仅能执行草稿或已发布食谱；待审核食谱必须先完成原审批。")
    return doc


def _key(recipe):
    return "tjy-recipe-execution:" + procurement.digest(recipe)


def _latest(recipe):
    rows = frappe.get_all("Comment", filters={"reference_doctype": procurement.RECIPE,
        "reference_name": recipe, "subject": SUBJECT, "comment_type": "Info"},
        fields=["name", "content"], order_by="creation desc", limit_page_length=1)
    if not rows:
        return None
    found = re.search(r"<pre>([A-Za-z0-9+/=]+)</pre>", rows[0].content or "")
    if not found:
        frappe.throw("食谱任务审计记录损坏，请管理员核对；不会重复创建采购。")
    return json.loads(base64.b64decode(found.group(1)))


def _record(state):
    state["updated_at"] = str(now_datetime())
    content = base64.b64encode(json.dumps(state, ensure_ascii=False, default=str).encode()).decode()
    frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "subject": SUBJECT,
        "reference_doctype": procurement.RECIPE, "reference_name": state["recipe"],
        "content": f"食谱执行：{state['status']}<pre>{content}</pre>"}).insert()
    saved = json.loads(json.dumps(state, default=str))
    frappe.db.after_commit.add(lambda: frappe.cache.set_value(_key(saved["recipe"]), saved, expires_in_sec=3600))


def _public(state):
    if not state:
        return {"status": "not_started", "steps": STEPS}
    result = {key: state.get(key) for key in ("status", "stage", "message", "updated_at", "result", "recipe")} | {"steps": STEPS}
    result["message"] = re.sub(r"<[^>]+>", " ", unescape(str(result.get("message") or "")))
    return result


@frappe.whitelist()
def inspect(recipe):
    """Read-only configuration: no publication or purchasing from opening the dialog."""
    _access(recipe, write=True)
    scope = procurement.default_scope(recipe)
    prepared = procurement.prepare(recipe, scope["company"], allow_draft=True)
    previous = _latest(recipe)
    current_revision = source_snapshot(recipe)["revision"]
    defaults = previous if previous and previous.get("revision") == current_revision else {}
    return {"scope": scope, "revision": source_snapshot(recipe)["revision"],
            "fallback_count": defaults.get("fallback_count"), "include_history": defaults.get("include_history", 0),
            "meals": prepared["meals"], "unmatched": sum(not row.get("item_code") for row in prepared["ingredients"]),
            "status": status(recipe)}


@frappe.whitelist()
def status(recipe):
    procurement._read(procurement.RECIPE, recipe)
    state = frappe.cache.get_value(_key(recipe)) or _latest(recipe)
    if state and state.get("status") in ("queued", "running"):
        from frappe.utils.background_jobs import is_job_enqueued
        if not is_job_enqueued(state["job_id"]):
            state = dict(state, status="interrupted", message="任务未在队列运行，可安全重试。采购事务未完成时不会标记结算成功。")
    return _public(state)


@frappe.whitelist(methods=["POST"])
def start(recipe, revision, confirmed=0, include_history=0, fallback_count=None):
    _access(recipe, write=True)
    if str(confirmed) != "1":
        frappe.throw("请确认实际收货、发票、付款事实及当前价格后执行。")
    if str(include_history) not in ("0", "1"):
        frappe.throw("历史补录选项无效。")
    if fallback_count not in (None, ""):
        fallback_count = procurement.number(fallback_count, zero=True, integer=True)
    else:
        fallback_count = None
    with frappe.cache.lock(_key(recipe) + ":lock", timeout=60, blocking_timeout=1):
        previous = _latest(recipe)
        if fallback_count is None and previous and previous.get("revision") == revision:
            fallback_count = previous.get("fallback_count")
        from frappe.utils.background_jobs import is_job_enqueued
        if previous and previous["status"] in ("queued", "running") and is_job_enqueued(previous["job_id"]):
            return _public(previous)
        current = source_snapshot(recipe)["revision"]
        if revision != current:
            frappe.throw("食谱已变更，请重新打开发布窗口。")
        if previous and previous["status"] == "completed":
            if previous["revision"] != current:
                frappe.throw("本食谱已有结算记录，请创建修订版，不会覆盖或重复采购。")
            return _public(previous)
        state = {"recipe": recipe, "revision": current, "actor": frappe.session.user,
                 "status": "queued", "stage": "准备", "message": "已排队，可关闭窗口，稍后重新查看进度。",
                 "include_history": int(include_history), "fallback_count": fallback_count,
                 "job_id": "tjy-recipe-cycle-" + procurement.digest(recipe)}
        _record(state)
        frappe.enqueue("tongjianyun.recipe_execution.run", queue="long", timeout=1800,
                       job_id=state["job_id"], deduplicate=True, enqueue_after_commit=True, state=state)
        # Persist the queued claim before releasing the per-recipe lock.
        frappe.db.commit()
    return _public(state)


def _progress(state, stage, message):
    state.update(status="running", stage=stage, message=message, updated_at=str(now_datetime()))
    frappe.cache.set_value(_key(state["recipe"]), state, expires_in_sec=3600)


def _assert_existing_request_matches(name, plan):
    """Never pay old or partially mapped demand based on new recipe inputs."""
    request = procurement._read("Material Request", name)
    def signature(rows):
        return sorted((str(r.get("schedule_date")), r.get("item_code"), r.get("uom"),
                       round(float(r.get("qty") or 0), 6), round(float(r.get("rate") or 0), 6)) for r in rows)
    if signature(request.items) != signature(plan["lines"]):
        frappe.throw("已有采购需求的数量、日期、单位或价格与当前食谱不同。请先核对原单或使用修订版，系统不会修改已提交单据。")


def _verify_settlement(result):
    request = procurement._read("Material Request", result["name"])
    if any(float(row.ordered_qty or 0) + 1e-6 < float(row.stock_qty or 0) for row in request.items):
        frappe.throw("已有订单未覆盖全部食谱需求，请核对剩余数量；不能标记整周结算完成。")
    for name in result["purchase_orders"]:
        order = procurement._read("Purchase Order", name)
        if float(order.per_received or 0) < 99.999 or float(order.per_billed or 0) < 99.999:
            frappe.throw("采购订单尚未全部收货或开票，不能标记结算完成。")
        invoices = procurement._linked_active_documents("Purchase Invoice Item",
            {"purchase_order": name, "parenttype": "Purchase Invoice"}, "Purchase Invoice")
        if not invoices or any(float(invoice.outstanding_amount or 0) > 0.005 for invoice in invoices):
            frappe.throw("存在尚未结清的关联发票，请核对，不能标记结算完成。")


def run(state):
    recipe = state["recipe"]
    try:
        # RQ restores the original identity; never elevate it for a retry.
        if frappe.session.user != state["actor"] or not frappe.db.get_value("User", state["actor"], "enabled"):
            raise frappe.PermissionError("发起人已停用或执行身份不匹配。")
        with frappe.cache.lock(_key(recipe) + ":lock", timeout=1900, blocking_timeout=5):
            _access(recipe, write=True)
            if source_snapshot(recipe)["revision"] != state["revision"]:
                frappe.throw("食谱已变更，旧任务停止，请重新发布。")
            _progress(state, "食材匹配", "正在复用物料匹配服务，必要时调用模型分类。")
            _record(state)
            frappe.db.commit()
            scope = procurement.default_scope(recipe)
            prepared = procurement.prepare(recipe, scope["company"], allow_draft=True)
            if any(not row.get("item_code") for row in prepared["ingredients"]):
                from tongjianyun.recipe_item_sync import run_sync
                run_sync(recipe, state["revision"])
                prepared = procurement.prepare(recipe, scope["company"], allow_draft=True)
            if any(not row.get("item_code") for row in prepared["ingredients"]):
                frappe.throw("部分食材尚未匹配。请使用下方“处理待确认食材”或“查看异常详情”，处理后点击“继续发布并结算”；不会猜测外购或自制。")
            # Release the old read snapshot, lock the recipe through the entire financial transaction.
            frappe.db.rollback()
            frappe.db.get_value(procurement.RECIPE, recipe, "name", for_update=True)
            doc = _access(recipe, write=True)
            if source_snapshot(recipe)["revision"] != state["revision"]:
                frappe.throw("食谱已变更，旧任务停止。")
            _progress(state, "校验人数与价格", "正在核对备餐人数、默认价格和单位。")
            prepared = procurement.prepare(recipe, scope["company"], allow_draft=True)
            mappings = {r["key"]: {k: r.get(k) for k in ("item_code", "uom", "factor")} for r in prepared["ingredients"]}
            meals = {r["key"]: r["count"] if r["count"] is not None else state["fallback_count"] for r in prepared["meals"]}
            plan = procurement._plan(recipe, scope["company"], scope["warehouse"], mappings, meals,
                                     state["include_history"], allow_draft=True)
            procurement._validate_plan_prices(plan)
            procurement._apply_plan_rates(plan)
            _progress(state, "发布食谱", "校验通过，正在发布（事务提交前不代表结算完成）。")
            if doc.workflow_status != "已发布":
                doc.workflow_status = "已发布"
                doc.save()
            _progress(state, "采购需求", "正在生成或校验已有采购需求。")
            result = procurement.create_request(recipe, scope["company"], scope["warehouse"], mappings,
                meals, plan["token"], confirmed=1, include_history=state["include_history"])
            _assert_existing_request_matches(result["name"], plan)
            stages = {"orders": "采购订单", "receipts": "收货", "invoices": "发票", "payments": "付款"}
            result = procurement.complete_purchase_cycle(result["name"],
                progress=lambda stage, message: _progress(state, stages[stage], message + "；整笔事务待提交"))
            _verify_settlement(result)
            state.update(status="completed", stage="完成", result=result,
                         message="本食谱采购结算已完成，可供财务关账核对。未执行公司级月结或关账，也未发起银行转账。")
            _record(state)
            frappe.db.commit()
    except Exception as error:
        frappe.db.rollback()
        state.update(status="failed", message=str(error)[:1000] + " 本次未提交的采购财务单据已回滚；已完成的食材匹配保留。")
        _record(state)
        frappe.db.commit()
    return _public(state)
