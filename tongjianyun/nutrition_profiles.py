"""Legacy category representative values; estimates, not verified food composition.

Only mass quantities may use these values. Unknown foods have no profile.
"""
import re

NUTRIENT_KEYS = (
    "energy", "protein", "fat", "carbohydrate", "calcium", "vitamin_a", "vitamin_b1",
    "vitamin_b2", "vitamin_c", "vitamin_e", "niacin", "potassium", "magnesium", "iron",
    "zinc", "phosphorus", "selenium", "carotene", "fiber", "cholesterol",
)

CATEGORY_PROFILES = {
    "fine_grain": dict(energy=350, protein=8, fat=1.2, carbohydrate=77, calcium=18, phosphorus=115, potassium=120, magnesium=35, iron=1.8, zinc=1.4, selenium=4, vitamin_b1=.15, vitamin_b2=.05, niacin=2, fiber=1.2),
    "coarse_grain": dict(energy=340, protein=9, fat=2.5, carbohydrate=70, calcium=25, phosphorus=220, potassium=280, magnesium=90, iron=3, zinc=2, selenium=5, vitamin_b1=.3, vitamin_b2=.12, niacin=2.5, fiber=5),
    "pastry": dict(energy=330, protein=8, fat=8, carbohydrate=58, calcium=35, phosphorus=100, potassium=110, magnesium=30, iron=1.5, zinc=.8, selenium=4, vitamin_b1=.1, vitamin_b2=.08, niacin=1, fiber=1.5),
    "dry_bean": dict(energy=360, protein=25, fat=16, carbohydrate=34, calcium=190, phosphorus=470, potassium=1500, magnesium=200, iron=8, zinc=3.3, selenium=6, vitamin_b1=.4, vitamin_b2=.2, niacin=2, fiber=15),
    "soy": dict(energy=105, protein=10, fat=5, carbohydrate=4, calcium=160, phosphorus=140, potassium=150, magnesium=65, iron=2, zinc=1, selenium=2, vitamin_b1=.08, vitamin_b2=.05, niacin=.4, fiber=.5),
    "non_green_veg": dict(energy=25, protein=1.2, fat=.2, carbohydrate=4.5, calcium=25, phosphorus=30, potassium=180, magnesium=15, iron=.5, zinc=.25, selenium=.6, vitamin_a=15, carotene=90, vitamin_b1=.03, vitamin_b2=.04, vitamin_c=12, vitamin_e=.4, niacin=.5, fiber=1.3),
    "green_veg": dict(energy=28, protein=2, fat=.3, carbohydrate=4, calcium=75, phosphorus=45, potassium=260, magnesium=28, iron=1.5, zinc=.4, selenium=1, vitamin_a=180, carotene=1080, vitamin_b1=.06, vitamin_b2=.1, vitamin_c=35, vitamin_e=1, niacin=.7, fiber=2),
    "fruit": dict(energy=52, protein=.6, fat=.2, carbohydrate=12, calcium=12, phosphorus=15, potassium=150, magnesium=10, iron=.3, zinc=.15, selenium=.3, vitamin_a=20, carotene=120, vitamin_b1=.03, vitamin_b2=.03, vitamin_c=18, vitamin_e=.5, niacin=.4, fiber=1.5),
    "dairy": dict(energy=62, protein=3.2, fat=3.4, carbohydrate=4.8, calcium=105, phosphorus=73, potassium=109, magnesium=11, iron=.1, zinc=.4, selenium=2, vitamin_a=24, vitamin_b1=.03, vitamin_b2=.14, vitamin_c=1, vitamin_e=.2, niacin=.1, cholesterol=15),
    "egg": dict(energy=144, protein=13.3, fat=8.8, carbohydrate=2.8, calcium=56, phosphorus=130, potassium=154, magnesium=10, iron=2, zinc=1.1, selenium=14, vitamin_a=234, vitamin_b1=.11, vitamin_b2=.27, vitamin_e=1.8, niacin=.2, cholesterol=585),
    "meat": dict(energy=170, protein=20, fat=9, carbohydrate=0, calcium=8, phosphorus=180, potassium=300, magnesium=22, iron=2, zinc=3, selenium=10, vitamin_a=5, vitamin_b1=.35, vitamin_b2=.15, vitamin_e=.4, niacin=5, cholesterol=70),
    "liver": dict(energy=130, protein=19, fat=4, carbohydrate=5, calcium=10, phosphorus=310, potassium=235, magnesium=25, iron=22, zinc=5, selenium=26, vitamin_a=5000, vitamin_b1=.2, vitamin_b2=2, vitamin_c=20, vitamin_e=.9, niacin=15, cholesterol=300),
    "fish": dict(energy=110, protein=19, fat=3, carbohydrate=0, calcium=45, phosphorus=190, potassium=310, magnesium=30, iron=1, zinc=.8, selenium=25, vitamin_a=15, vitamin_b1=.05, vitamin_b2=.1, vitamin_e=.8, niacin=3, cholesterol=65),
    "sugar": dict(energy=395, protein=0, fat=0, carbohydrate=99, calcium=5, phosphorus=1, potassium=10, magnesium=2, iron=.2, zinc=0, selenium=0),
    "oil": dict(energy=899, protein=0, fat=99.9, carbohydrate=0, calcium=0, phosphorus=0, potassium=0, magnesium=0, iron=0, zinc=0, selenium=0, vitamin_e=40),
    "water": dict(energy=0, protein=0, fat=0, carbohydrate=0, calcium=0, phosphorus=0, potassium=0, magnesium=0, iron=0, zinc=0, selenium=0),
}

ALIASES = {
    "纯牛奶": "牛奶", "巴氏杀菌乳": "牛奶", "酸奶": "牛奶", "西红柿": "番茄",
    "西蓝花": "西兰花", "红萝卜": "胡萝卜", "大肉": "猪肉", "猪瘦肉": "猪肉",
    "猪里脊肉": "猪肉", "肉丝": "猪肉", "肉丁": "猪肉", "龙利鱼": "鱼",
    "鱼头": "鱼", "甜玉米": "玉米", "甜玉米粒": "玉米", "玉米粒": "玉米",
    "小麦粉": "面粉", "全麦面粉": "面粉", "糕点": "切片面包", "饮用水": "水",
}

KEYWORDS = (
    ("water", ("水", "骨汤")), ("oil", ("油", "芝麻酱", "花生米", "核桃仁")),
    ("dairy", ("奶", "酸奶")), ("egg", ("蛋",)), ("liver", ("肝",)),
    ("fish", ("鱼", "虾", "海鲜")), ("meat", ("肉", "鸡", "牛", "排骨", "火腿")),
    ("soy", ("豆腐", "豆干", "豆芽")), ("dry_bean", ("黄豆", "红豆", "绿豆", "青豆", "豌豆", "毛豆")),
    ("fruit", ("苹果", "香蕉", "西瓜", "哈密瓜", "葡萄", "火龙果", "梨", "蓝莓", "圣女果")),
    ("green_veg", ("菠菜", "油麦菜", "生菜", "青菜", "菜心", "西兰花", "西蓝花", "芹菜", "西芹", "青椒", "韭菜", "荷兰豆")),
    ("non_green_veg", ("菜", "瓜", "番茄", "西红柿", "萝卜", "葱", "姜", "蒜", "木耳", "香菇", "蘑菇", "海带", "紫菜", "莲藕", "土豆", "山药", "芋头")),
    ("sugar", ("糖", "果酱")), ("pastry", ("面包", "糕点", "饼干")),
    ("coarse_grain", ("小米", "黑米", "糙米", "燕麦", "玉米", "薏米", "紫薯", "红薯", "玉米糁", "玉米粉")),
    ("fine_grain", ("大米", "面粉", "面条", "饺子皮", "馄饨皮", "江米", "淀粉")),
)

def classify_ingredient(name):
    display = re.sub(r"\s+", " ", str(name or "")).strip()
    lookup = re.sub(r"[（(].*?[）)]", "", display).strip()
    lookup = ALIASES.get(lookup, lookup)
    # Broth is a prepared product of unknown composition; water is exact only.
    if lookup == "水":
        return "water", display
    if any(word in lookup for word in ("汤", "汁", "酱", "复合调味", "花生", "核桃", "土豆", "山药", "芋头", "紫薯", "红薯", "鲜面条", "湿面")):
        return "unclassified", display
    matches = []
    for category, words in KEYWORDS:
        if category == "water":
            continue
        matches.extend((len(word), -index, category) for index, word in enumerate(words) if word in lookup)
    if matches:
        # A named vegetable such as 油麦菜 takes precedence over the generic 油.
        return max(matches, key=lambda match: match[0])[2], display
    return "unclassified", display
