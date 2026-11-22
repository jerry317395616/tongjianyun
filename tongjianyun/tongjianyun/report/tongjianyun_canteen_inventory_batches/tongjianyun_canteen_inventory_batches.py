from tongjianyun.canteen_ops.reports import run


def execute(filters=None):
    return run("Canteen Inventory Batches", filters)
