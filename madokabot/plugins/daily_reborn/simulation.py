"""按出生人数加权抽样并生成游戏属性。"""

import math
import random
from functools import lru_cache

from .attributes import ATTRIBUTES, STAR_SYSTEM, attribute_stars, draw_star
from .geography import random_location
from .modes import RebornMode
from .potential import EVALUATION_SYSTEM, evaluate_life
from .potential import score_label as score_label
from .resources import load_json_resource


@lru_cache(maxsize=4)
def load_population(mode: RebornMode = "world") -> dict:
    """通过核心 JSON 工具读取人口快照，拒绝无效的权重与出生性别比。"""
    filename = "population.json" if mode == "world" else f"{mode}_population.json"
    dataset = load_json_resource(filename)
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
    """补全旧潜力评价并纠正误标为非军事区的朝韩结果，不修改原记录或重抽。"""
    country = result.get("country", {})
    if country.get("code") in ("PRK", "KOR") and country.get("name") == "朝韩非军事区":
        current = next(row for row in load_population()["countries"] if row["code"] == country["code"])
        result = result | {
            "country": country | {key: current[key] for key in ("name", "longitude", "latitude", "map_code")},
            "map_point": None,
        }
    if result.get("attribute_system") == STAR_SYSTEM and result.get("evaluation_system") == EVALUATION_SYSTEM:
        return result
    stars = attribute_stars(result)
    return result | {"attributes": stars, "attribute_system": STAR_SYSTEM} | evaluate_life(stars)


def simulate_rebirth(*, mode: RebornMode = "world") -> dict:
    """按出生人数与性别比抽样，生成星级潜力并保存地区内的随机定位。"""
    dataset = load_population(mode)
    countries = dataset["countries"]
    country = random.choices(countries, weights=[row["births"] for row in countries])[0]
    attributes = {name: draw_star() for name in ATTRIBUTES}
    # 出生性别比统一为每 100 名女婴对应的男婴数量，不使用总人口性别比。
    ratio = country["sex_ratio"]
    gender = "男" if random.random() < ratio / (ratio + 100) else "女"
    return {
        "country": country,
        "mode": mode,
        "data_year": country.get("year", dataset["year"]),
        "source": country.get("source", dataset["source"]),
        "data_note": "中方案预测" if mode == "world" else country.get("births_note", dataset.get("births_note", "")),
        "probability": country["births"] / sum(row["births"] for row in countries),
        "gender": gender,
        "map_point": random_location(country, mode=mode),
        "attributes": attributes,
        "attribute_system": STAR_SYSTEM,
        **evaluate_life(attributes),
    }
