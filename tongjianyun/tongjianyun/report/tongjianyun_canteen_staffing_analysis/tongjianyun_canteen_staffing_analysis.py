from tongjianyun.canteen_staffing import execute as run_report
from tongjianyun.canteen_ops.desk_labels import report_labels


def execute(filters=None):
    return report_labels(run_report(filters))
