"""人生属性的半星抽样、稀有度与展示信息。"""

import math
import random

ATTRIBUTES = ("家境", "健康", "智力", "魅力", "运气")
# 权重按千分之一计，4 / 4.5 / 5 星分别为 2% / 0.8% / 0.2%。
STAR_DISTRIBUTION = ((1, 100), (1.5, 160), (2, 240), (2.5, 240), (3, 160), (3.5, 70), (4, 20), (4.5, 8), (5, 2))
STAR_SYSTEM = "stars_v1"


def draw_star() -> float:
    """按离散权重独立抽取 1～5 星，每半星一档，最低保证一星。"""
    ticket = random.randrange(sum(weight for _, weight in STAR_DISTRIBUTION))
    for stars, weight in STAR_DISTRIBUTION:
        if ticket < weight:
            return stars
        ticket -= weight
    raise RuntimeError("星级权重未覆盖抽样区间")


def attribute_stars(result: dict) -> dict[str, float]:
    """读取新星级，旧百分制结果仅按十分一档转换为半星，不修改持久化数据。"""
    if result.get("attribute_system") == STAR_SYSTEM:
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
