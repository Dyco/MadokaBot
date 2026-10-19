"""人生属性的半星抽样、稀有度与展示信息。"""

import math
import random

ATTRIBUTES = ("家境", "健康", "智力", "魅力", "运气")
# 普通档案以二至三星半为主，完整高星组合由联合抽取的独立票区间控制。
STAR_DISTRIBUTION = ((1, 60), (1.5, 100), (2, 170), (2.5, 240), (3, 220), (3.5, 130), (4, 60), (4.5, 17), (5, 3))
STAR_SYSTEM = "stars_v2"


def draw_star(minimum: float = 1, *, exclude: float | None = None) -> float:
    """按半星权重抽取单项属性，支持家庭保障下限及联合抽取排除项。"""
    options = [(stars, weight) for stars, weight in STAR_DISTRIBUTION if stars >= minimum and stars != exclude]
    return random.choices([stars for stars, _ in options], weights=[weight for _, weight in options])[0]


def draw_attributes() -> dict[str, float]:
    """联合抽取五项星级，恰好全五星百万分之一、全四星万分之一，家境提高健康与魅力下限。"""
    ticket = random.randrange(1_000_000)
    if ticket == 0:
        return dict.fromkeys(ATTRIBUTES, 5)
    if ticket <= 100:
        return dict.fromkeys(ATTRIBUTES, 4)
    family = draw_star()
    stars = {
        "家境": family,
        "健康": draw_star(max(1, family - 1.5)),
        "智力": draw_star(),
        "魅力": draw_star(max(1, family - 2)),
    }
    # 普通票区间排除两个特定完整组合，防止叠加改变约定的精确概率。
    exclude = family if family in (4, 5) and all(value == family for value in stars.values()) else None
    stars["运气"] = draw_star(exclude=exclude)
    return stars


def attribute_stars(result: dict) -> dict[str, float]:
    """读取两版半星档案，旧百分制仅转换展示，不改变已保存属性或应用新的家境联动。"""
    if result.get("attribute_system") in {"stars_v1", STAR_SYSTEM}:
        return dict(result["attributes"])
    return {name: max(1, min(5, math.floor(value / 10 + .5) / 2)) for name, value in result["attributes"].items()}


def attribute_rows(stars: dict) -> list[dict]:
    """生成五项属性的整星、半星、空星及稀有度信息，供图片和文字共用。"""
    rows = []
    for name, value in stars.items():
        if value == 5:
            rarity, title = "legendary", "传说"
        elif value == 4.5:
            rarity, title = "epic", "史诗"
        elif value == 4:
            rarity, title = "rare", "卓越"
        elif value >= 3:
            rarity, title = "fine", "优秀"
        else:
            rarity, title = "normal", "普通"
        rows.append({
            "name": name, "value": value, "value_text": f"{value:g}",
            "rarity": rarity, "title": title,
            "slots": ["full" if value >= index + 1 else "half" if value >= index + .5 else "empty" for index in range(5)],
        })
    return rows
