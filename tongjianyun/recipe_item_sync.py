"""Permission-preserving, after-commit recipe ingredient master synchronization."""
import json

import frappe

from tongjianyun.ingredient_classification import request_classification, ClassificationUnavailable, validate_proposals
from tongjianyun.harness_ingredient_client import HarnessIngredientClient
from tongjianyun.ingredient_resolution import FILTERS, requires_product_confirmation
from tongjianyun.recipe_procurement import TRACE, _permission, _read, conversion, digest

KIND = "erp_recipe_auto_mapping"
INGREDIENT = "Tongjianyun Recipe Ingredient"


def source_snapshot(recipe):
    doc = _read("Tongjianyun Recipe", recipe)
    doc.check_permission("write")
    if doc.is_deleted:
        frappe.throw("食谱已删除。")
    raw = frappe.get_list(INGREDIENT, filters={"recipe": recipe},
        fields=["ingredient_name", "unit"], limit_page_length=0)
    if len(raw) != frappe.db.count(INGREDIENT, {"recipe": recipe}):
        frappe.throw("无法读取完整食材明细。", frappe.PermissionError)
    rows = {digest([r.ingredient_name, r.unit])[:24]: {
        "ingredient": r.ingredient_name, "unit": r.unit} for r in raw}
    if not 0 < len(rows) <= 200:
        frappe.throw("自动匹配支持 1 至 200 项不同食材。")
    source = [{"key": key, **row} for key, row in sorted(rows.items())]
    return {"recipe": recipe, "revision": digest(source), "ingredients": source}


def _cache_key(recipe):
    return "tjy-recipe-item-sync:" + digest([frappe.session.user, recipe])


def _state(recipe, value):
    try:
        frappe.cache.set_value(_cache_key(recipe), value, expires_in_sec=86400)
    except Exception:
        pass  # Cache health must not invalidate a saved recipe or successful ORM transaction.


def schedule_after_save(recipe):
    try:
        snapshot = source_snapshot(recipe)
        for dt, action in (("Item", "read"), (TRACE, "create"), (TRACE, "read")):
            _permission(dt, action)
    except Exception:
        return {"recipe": recipe, "status": "blocked", "message": "食谱已保存；账号权限或食材明细不满足自动建档条件，可联系管理员查看。"}
    actor = frappe.session.user

    def dispatch():
        if frappe.session.user != actor:
            return
        queued = {"status": "queued", "revision": snapshot["revision"], "message": "食材物料匹配已排队。"}
        _state(recipe, queued)
        try:
            frappe.enqueue("tongjianyun.recipe_item_sync.run_sync", queue="long", timeout=1800,
                recipe=recipe, revision=snapshot["revision"],
                job_id="recipe-item-sync-" + digest([recipe, snapshot["revision"], actor]), deduplicate=True)
        except Exception:
            _state(recipe, {"status": "failed", "revision": snapshot["revision"],
                "message": "食谱已保存，但后台队列暂不可用；请稍后重新保存食谱重试。"})
    frappe.db.after_commit.add(dispatch)
    return {"recipe": recipe, "status": "queued", "message": "食谱已保存，正在安排后台匹配食材物料。"}


def _match(row):
    if requires_product_confirmation(row["ingredient"]):
        return None, "菜品或汤粥需确认是否外购，不自动建档。"
    matches = frappe.get_list("Item", filters={**FILTERS, "item_name": row["ingredient"]},
        fields=["name", "stock_uom"], limit_page_length=2)
    if len(matches) > 1:
        return None, "存在多个同名物料，需人工核对规格。"
    if matches:
        item = _read("Item", matches[0].name)
        unit = _read("UOM", item.stock_uom)
        factor = conversion(row["unit"], item.stock_uom)
        if not unit.enabled or factor is None:
            return None, "库存单位停用或单位不可直接换算。"
        return {"item_code": item.name, "uom": item.stock_uom, "factor": factor}, ""
    if frappe.db.exists("Item", {"item_name": row["ingredient"]}):
        return None, "同名物料不可用于自动匹配，请联系管理员核对。"
    return None, ""


def classify_batches(client, pending, groups):
    """Validate each batch independently; never discard successful earlier batches."""
    proposals, failures, accepted = [], [], []
    for offset in range(0, len(pending), 20):
        batch = pending[offset:offset + 20]
        code = "service_unavailable"
        for attempt in range(2):
            try:
                rows = request_classification(client, batch, groups)
                # Preserve the overall new-group limit and parent consistency.
                validate_proposals({"rows": proposals + rows}, accepted + batch, groups)
                proposals.extend(rows)
                accepted.extend(batch)
                break
            except ClassificationUnavailable:
                code = "service_unavailable"
            except ValueError:
                code = "invalid_classification"
            except Exception:
                code = "unexpected_error"
        else:
            failures.append({"batch": offset // 20 + 1, "keys": [r["key"] for r in batch],
                             "code": code, "attempts": 2})
    return proposals, failures


def make_plan(recipe):
    _permission("Item", "read")
    _permission("Item Group", "read")
    plan = source_snapshot(recipe)
    pending = []
    for row in plan["ingredients"]:
        mapping, reason = _match(row)
        if mapping is None and not reason:
            pending.append(row)
    groups = [dict(row) for row in frappe.get_list("Item Group",
        fields=["name", "is_group", "parent_item_group"], limit_page_length=0)]
    plan["groups"] = groups
    plan["proposals"] = []
    plan["classification_failed"] = False
    plan["classification_errors"] = []
    plan["creation_blocked"] = bool(pending) and not frappe.has_permission("Item", ptype="create")
    if pending and frappe.has_permission("Item", ptype="create"):
        plan["proposals"], plan["classification_errors"] = classify_batches(HarnessIngredientClient(), pending, groups)
        plan["classification_failed"] = bool(plan["classification_errors"])
    return plan


def apply_plan(plan):
    """Caller owns transaction and serialization; no commits or permission bypasses here."""
    _permission("Item", "read")
    _permission(TRACE, "read")
    _permission(TRACE, "create")
    current = source_snapshot(plan["recipe"])
    if current["revision"] != plan["revision"]:
        frappe.throw("食材已改变，旧任务已停止，请重新保存。")
    # Revalidate model proposals against the original allowed catalog before interpreting them.
    from tongjianyun.ingredient_classification import validate_proposals
    proposals = plan["proposals"]
    if proposals:
        proposed_keys = {row["key"] for row in proposals}
        validate_proposals({"rows": proposals}, [r for r in current["ingredients"] if r["key"] in proposed_keys], plan["groups"])
    by_key = {row["key"]: row for row in proposals}
    result = {"recipe": current["recipe"], "revision": current["revision"], "mappings": {},
        "created_items": [], "created_groups": [], "unresolved": [], "actor": frappe.session.user,
        "classification_failed": plan["classification_failed"],
        "classification_errors": plan.get("classification_errors", [])}
    failed_keys = {key for error in result["classification_errors"] for key in error["keys"]}
    for index, row in enumerate(current["ingredients"]):
        savepoint = "ingredient_sync_" + str(index)
        frappe.db.savepoint(savepoint)
        group_created = None
        try:
            mapping, reason = _match(row)
            if not mapping and not reason:
                proposal = by_key.get(row["key"])
                if row["key"] in failed_keys:
                    reason = "本批分类服务调用或结果校验失败，已尝试 2 次；未创建物料，可重试。"
                elif plan.get("creation_blocked"):
                    reason = "当前账号没有创建物料权限，未创建物料。"
                elif not proposal:
                    reason = "分类结果缺失，未创建物料；请重试。"
                elif proposal["action"] == "review":
                    reason = "食材分类需人工核对，未自动创建物料。"
                else:
                    _permission("Item", "create")
                    # Only create UOM-independent Items when an existing enabled unit is an exact equivalence.
                    units = frappe.get_list("UOM", filters={"enabled": 1}, pluck="name", limit_page_length=0)
                    unit = next((u for u in [row["unit"], "g", "Gram", "Kg", "Millilitre", "Litre"]
                                 if u in units and conversion(row["unit"], u) == 1), None)
                    if not unit:
                        frappe.throw("没有可用的等价库存单位。")
                    group = proposal["group"]
                    if proposal["action"] == "new" and not frappe.db.exists("Item Group", group):
                        _permission("Item Group", "create")
                        parent = _read("Item Group", proposal["parent"])
                        if not parent.is_group:
                            frappe.throw("父级分类已改变。")
                        frappe.get_doc({"doctype": "Item Group", "item_group_name": group,
                            "parent_item_group": parent.name, "is_group": 0}).insert()
                        group_created = group
                    group_doc = _read("Item Group", group)
                    if group_doc.is_group or (proposal["action"] == "new" and group_doc.parent_item_group != proposal["parent"]):
                        frappe.throw("分类已改变，需重新核对。")
                    item = frappe.get_doc({"doctype": "Item", "item_code": "TJY-AUTO-" + digest([row["ingredient"], unit])[:20].upper(),
                        "item_name": row["ingredient"], "item_group": group, "stock_uom": unit,
                        "is_stock_item": 1, "is_purchase_item": 1, "is_sales_item": 0}).insert()
                    mapping = {"item_code": item.name, "uom": unit, "factor": 1}
                    result["created_items"].append(item.name)
                    if group_created:
                        result["created_groups"].append(group_created)
            if mapping:
                result["mappings"][row["key"]] = mapping
            else:
                result["unresolved"].append({**row, "reason": reason})
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            result["unresolved"].append({**row, "reason": "权限、分类或物料校验未通过，未创建该物料。"})
    summarize_result(result)
    key = KIND + "::" + digest(current["recipe"])[:32]
    receipt = _read(TRACE, key) if frappe.db.exists(TRACE, key) else frappe.get_doc({"doctype": TRACE, "data_key": key})
    receipt.update({"record_type": KIND, "record_id": current["revision"], "parent_id": current["recipe"],
        "title": "食谱食材自动匹配", "status": result["status"], "source": "Harness / ERPNext standard ORM",
        "record_json": json.dumps(result, ensure_ascii=False)})
    receipt.save() if not receipt.is_new() else receipt.insert()
    return result


def summarize_result(result):
    if not result["unresolved"]:
        result.update(status="completed", message="食材物料匹配完成。")
    elif result["mappings"]:
        result.update(status="partial", message="成功匹配已保留；其余项目请按原因处理。")
    elif result["classification_failed"]:
        result.update(status="failed", message="分类服务调用或结果校验失败，本次没有成功匹配物料；不是所有食材都需要人工分类。")
    else:
        result.update(status="needs_review", message="尚无成功匹配，请核对权限、单位及食材信息。")


def run_sync(recipe, revision):
    """RQ captures the initiating Frappe user. Never switch to Administrator."""
    try:
        _state(recipe, {"status": "running", "revision": revision, "message": "正在匹配食材物料。"})
        if source_snapshot(recipe)["revision"] != revision:
            _state(recipe, {"status": "stale", "message": "食材已更新，旧任务停止。"})
            return
        plan = make_plan(recipe)
        if plan["revision"] != revision:
            _state(recipe, {"status": "stale", "message": "食材已更新，旧任务停止。"})
            return
        # Discard the read snapshot after slow inference; all business writes happen below.
        frappe.db.rollback()
        actor = frappe.session.user
        frappe.clear_cache(user=actor)
        frappe.set_user(actor)  # Reset per-request permission caches without changing identity.
        if not frappe.db.get_value("User", actor, "enabled"):
            raise frappe.PermissionError()
        with frappe.cache.lock("tjy-ingredient-master-sync", timeout=180, blocking_timeout=10):
            result = apply_plan(plan)
            frappe.db.commit()  # Commit before releasing the cross-recipe creation lock.
        _state(recipe, result)
        return {"status": result["status"], "matched": len(result["mappings"])}
    except Exception:
        frappe.db.rollback()
        _state(recipe, {"status": "failed", "revision": revision,
            "message": "食材同步失败，食谱仍已保存。请核对权限、模型服务和单位后重新保存。"})
        return {"status": "failed"}


@frappe.whitelist()
def get_sync_status(recipe):
    from tongjianyun.recipe_storage import _get_recipe_name
    recipe = _get_recipe_name(recipe)
    _read("Tongjianyun Recipe", recipe)
    _permission("Item", "read")
    _permission(TRACE, "read")
    try:
        state = frappe.cache.get_value(_cache_key(recipe))
    except Exception:
        state = None
    if state:
        return state
    _permission(TRACE, "read")
    key = KIND + "::" + digest(recipe)[:32]
    if frappe.db.exists(TRACE, key):
        return json.loads(_read(TRACE, key).record_json)
    return {"status": "not_started", "message": "尚无自动匹配记录；保存食谱后将触发匹配。"}
