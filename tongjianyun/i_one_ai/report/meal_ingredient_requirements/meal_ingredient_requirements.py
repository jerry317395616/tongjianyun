from tongjianyun import meal_planning


def execute(filters=None):
	return meal_planning.ingredient_report_data(filters)
