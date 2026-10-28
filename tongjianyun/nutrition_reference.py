"""Manual reference values from DB4403/T489-2024 table5; no compliance decision."""

OFFICIAL_SOURCE = "DB4403/T 489—2024《0岁～6岁儿童营养配餐指南》"

REFERENCE_NUTRIENTS = (
	"energy",
	"protein",
	"calcium",
	"iron",
	"zinc",
	"vitamin_a",
	"vitamin_b1",
	"vitamin_b2",
	"vitamin_c",
)

FULL_DAY_REFERENCE = {
	"2": {
		"男": dict(energy=1100, protein=25, calcium=500, iron=10, zinc=4.0, vitamin_a=340, vitamin_b1=0.6, vitamin_b2=0.7, vitamin_c=40),
		"女": dict(energy=1000, protein=25, calcium=500, iron=10, zinc=4.0, vitamin_a=330, vitamin_b1=0.6, vitamin_b2=0.6, vitamin_c=40),
	},
	"3": {
		"男": dict(energy=1250, protein=30, calcium=500, iron=10, zinc=4.0, vitamin_a=340, vitamin_b1=0.6, vitamin_b2=0.7, vitamin_c=40),
		"女": dict(energy=1150, protein=30, calcium=500, iron=10, zinc=4.0, vitamin_a=330, vitamin_b1=0.6, vitamin_b2=0.6, vitamin_c=40),
	},
	"4": {
		"男": dict(energy=1300, protein=30, calcium=600, iron=10, zinc=5.5, vitamin_a=390, vitamin_b1=0.9, vitamin_b2=0.9, vitamin_c=50),
		"女": dict(energy=1250, protein=30, calcium=600, iron=10, zinc=5.5, vitamin_a=380, vitamin_b1=0.9, vitamin_b2=0.8, vitamin_c=50),
	},
	"5": {
		"男": dict(energy=1400, protein=30, calcium=600, iron=10, zinc=5.5, vitamin_a=390, vitamin_b1=0.9, vitamin_b2=0.9, vitamin_c=50),
		"女": dict(energy=1300, protein=30, calcium=600, iron=10, zinc=5.5, vitamin_a=380, vitamin_b1=0.9, vitamin_b2=0.8, vitamin_c=50),
	},
	"6": {
		"男": dict(energy=1600, protein=35, calcium=600, iron=10, zinc=5.5, vitamin_a=390, vitamin_b1=0.9, vitamin_b2=0.9, vitamin_c=50),
		"女": dict(energy=1450, protein=35, calcium=600, iron=10, zinc=5.5, vitamin_a=380, vitamin_b1=0.9, vitamin_b2=0.8, vitamin_c=50),
	},
}

NUTRIENT_UNITS = {
    "energy": "kcal",
    "protein": "g",
    "fat": "g",
    "carbohydrate": "g",
    "calcium": "mg",
    "vitamin_a": "μg RAE",
    "vitamin_b1": "mg",
    "vitamin_b2": "mg",
    "vitamin_c": "mg",
    "vitamin_e": "mg α-TE",
    "niacin": "mg NE",
    "potassium": "mg",
    "magnesium": "mg",
    "iron": "mg",
    "zinc": "mg",
    "phosphorus": "mg",
    "selenium": "μg",
    "carotene": "μg",
    "fiber": "g",
    "cholesterol": "mg",
}
