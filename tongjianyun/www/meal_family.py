import frappe

from tongjianyun.canteen_ops.family_menu import public_view

no_cache = 1
sitemap = 0


def get_context(context):
    context.no_cache = 1
    context.menu = public_view(frappe.form_dict.get("key"))
    context.title = "本周食谱"
