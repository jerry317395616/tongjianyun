"""Render Tongjianyun's weekly menu from the permission-checked ERP meal plans."""
from ione_core.meal_planning import weekly_report_data


def execute(filters=None):
    return weekly_report_data(filters)
