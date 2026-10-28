"""Name classification only. Nutrient representative values have been removed.
"""
import re

NUTRIENT_KEYS = (
    "energy", "protein", "fat", "carbohydrate", "calcium", "vitamin_a", "vitamin_b1",
    "vitamin_b2", "vitamin_c", "vitamin_e", "niacin", "potassium", "magnesium", "iron",
    "zinc", "phosphorus", "selenium", "carotene", "fiber", "cholesterol",
)


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
