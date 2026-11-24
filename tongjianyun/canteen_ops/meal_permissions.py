from tongjianyun.canteen_ops.meal_operations import TYPES, permission_query

for doctype in TYPES:
    globals()[doctype.lower().replace(" ", "_")] = permission_query(doctype)
