"""Use the same permission-checked ERP data as the central weekly report."""
from ione_core.meal_planning import weekly_report_data


def execute(filters=None):
    return weekly_report_data(filters)
