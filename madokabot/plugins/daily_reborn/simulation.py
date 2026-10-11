"""按出生人数加权抽样并生成游戏属性。"""

import json
import math
import random
from functools import lru_cache
from pathlib import Path

from .attributes import ATTRIBUTES, STAR_SYSTEM, attribute_stars, draw_star
from .potential import EVALUATION_SYSTEM, evaluate_life, score_label as score_label

DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=2)
def load_population(china: bool = False) -> dict:
    """读取世界或中国人口快照，拒绝无效的抽样权重与出生性别比。"""
    filename = "china_population.json" if china else "population.json"
    dataset = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
    countries = dataset["countries"]
    if not countries or len({row["code"] for row in countries}) != len(countries):
        raise ValueError("出生人口数据为空或存在重复地区")
    for row in countries:
        if not math.isfinite(row["births"]) or row["births"] <= 0:
            raise ValueError(f"出生人口权重无效：{row['code']}")
        if not math.isfinite(row["sex_ratio"]) or row["sex_ratio"] <= 0:
            raise ValueError(f"出生性别比无效：{row['code']}")
    return dataset


def display_result(result: dict) -> dict:
    """按当前潜力规则补全旧结果的展示，不修改数据库记录或重新抽样。"""
    if result.get("attribute_system") == STAR_SYSTEM and result.get("evaluation_system") == EVALUATION_SYSTEM:
        return result
    stars = attribute_stars(result)
    return result | {"attributes": stars, "attribute_system": STAR_SYSTEM} | evaluate_life(stars)


def simulate_rebirth(*, china: bool = False) -> dict:
    """以出生人数及出生性别比抽样，五项星级独立抽取并生成潜力剧本。"""
    dataset = load_population(True) if china else load_population()
    countries = dataset["countries"]
    country = random.choices(countries, weights=[row["births"] for row in countries])[0]
    attributes = {name: draw_star() for name in ATTRIBUTES}
    # 出生性别比统一为每 100 名女婴对应的男婴数量，不使用总人口性别比。
    ratio = country["sex_ratio"]
    gender = "男" if random.random() < ratio / (ratio + 100) else "女"
    return {
        "country": country,
        "mode": "china" if china else "world",
        "data_year": country.get("year", dataset["year"]),
        "source": country.get("source", dataset["source"]),
        "data_note": country.get("births_note", "") if china else "中方案预测",
        "probability": country["births"] / sum(row["births"] for row in countries),
        "gender": gender,
        "attributes": attributes,
        "attribute_system": STAR_SYSTEM,
        **evaluate_life(attributes),
    }
