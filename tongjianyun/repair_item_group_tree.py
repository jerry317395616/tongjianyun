"""Explicit, site-scoped repair of legacy Item Group business records, not schema."""
import argparse
import json
import uuid

import frappe
from frappe.utils.nestedset import rebuild_tree_for_doctype

ROOT = "Fee Component"
DETACHED = {"干货", "水果", "蔬菜", "调味品", "肉禽水产", "粮油及主食", "蛋奶及豆制品", "包装及低值耗材"}


def snapshot():
    groups = frappe.get_list("Item Group", fields=["name", "parent_item_group", "is_group", "lft", "rgt"],
                             order_by="name", limit_page_length=0)
    configuration = {}
    for row in groups:
        doc = frappe.get_doc("Item Group", row.name)
        doc.check_permission("read")
        configuration[row.name] = {"defaults": [d.as_dict() for d in doc.item_group_defaults],
                                    "taxes": [d.as_dict() for d in doc.taxes]}
    items = frappe.get_list("Item", fields=["name", "item_group", "modified"], order_by="name", limit_page_length=0)
    return {"groups": groups, "configuration": configuration, "items": items}


def check(after, before):
    groups = {g.name: g for g in after["groups"]}
    assert set(groups) == {g.name for g in before["groups"]}
    assert after["items"] == before["items"]
    assert after["configuration"] == before["configuration"]
    assert [g.name for g in groups.values() if not g.parent_item_group] == [ROOT]
    assert groups[ROOT].is_group == 1
    indices = []
    for group in groups.values():
        indices.extend([group.lft, group.rgt])
        assert group.lft < group.rgt
        if group.parent_item_group:
            parent = groups[group.parent_item_group]
            assert parent.is_group and parent.lft < group.lft < group.rgt < parent.rgt
    assert sorted(indices) == list(range(1, 2 * len(groups) + 1))
    for old in before["groups"]:
        expected_parent = ROOT if old.name in DETACHED else old.parent_item_group
        assert (groups[old.name].parent_item_group or "") == (expected_parent or "")


def run(apply=False):
    frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
    frappe.connect()
    frappe.set_user("Administrator")
    before = None
    try:
        before = snapshot()
        if len(before["groups"]) != 14 or len(before["items"]) != 70:
            raise RuntimeError("Scope changed; inspect again before repair")
        detached = {g.name for g in before["groups"] if not g.parent_item_group and g.name != ROOT}
        if detached != DETACHED:
            raise RuntimeError("Unexpected tree state; do not repeat an already completed repair")
        # Rebuild the malformed forest first, so standard moves operate on valid intervals.
        rebuild_tree_for_doctype("Item Group")
        for name in sorted(DETACHED):
            doc = frappe.get_doc("Item Group", name)
            doc.parent_item_group = ROOT
            doc.save()
        root = frappe.get_doc("Item Group", ROOT)
        root.is_group = 1
        root.save()
        rebuild_tree_for_doctype("Item Group")
        after = snapshot()
        check(after, before)
        # Confirm standard insertion of a new leaf works without keeping a test group.
        frappe.db.savepoint("group_creation_check")
        probe = frappe.get_doc({"doctype": "Item Group", "item_group_name": "TJY-VERIFY-" + uuid.uuid4().hex[:10],
                               "parent_item_group": ROOT, "is_group": 0}).insert()
        probe_name = probe.name
        assert probe.lft < probe.rgt
        frappe.db.rollback(save_point="group_creation_check")
        assert not frappe.db.exists("Item Group", probe_name)
        check(snapshot(), before)
        if apply:
            root.add_comment("Info", "经授权整理物料组层级：保留现有名称及物料归属，将8个无父级中文分类挂到Fee Component，根节点设为父级，并通过标准树重建接口校验。")
            frappe.db.commit()
        else:
            frappe.db.rollback()
            assert snapshot() == before
        frappe.clear_document_cache("Item Group")
        print(json.dumps({"applied": apply, "groups_reparented": len(DETACHED), "root_group_flag_updated": 1,
            "groups_total": 14, "item_links_preserved": 70, "default_and_tax_rows_preserved": True,
            "tree_intervals_verified": True, "standard_group_creation_verified": True,
            "probe_removed_by_rollback": True, "schema_changes": 0}, ensure_ascii=False))
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.db.auto_commit_on_many_writes = 0
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    run(parser.parse_args().apply)
