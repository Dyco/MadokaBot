"""世界投胎的常用地理分区，仅用于结果展示。"""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_regions() -> dict:
    """读取已确认的国家分区及俄罗斯近似分界规则。"""
    return json.loads((Path(__file__).parent / "data/world_regions.json").read_text(encoding="utf-8"))


def world_region(code: str, longitude: float | None = None) -> str:
    """查询国家分区；俄罗斯无历史坐标时保留东欧与北亚两种可能。"""
    data = load_regions()
    if code == "RUS":
        rule = data["russia"]
        if longitude is None:
            return f"{rule['west']}／{rule['east']}"
        return rule["west" if longitude < rule["longitude_split"] else "east"]
    return next((region for region, codes in data["regions"].items() if code in codes), "")


def result_region(result: dict) -> str:
    """仅为世界模式提供分区，优先按保存的随机坐标区分俄罗斯东西部。"""
    if result.get("mode", "world") != "world":
        return ""
    point = result.get("map_point")
    longitude = (point["x"] * 360 / 1000) % 360 - 180 if point else result["country"].get("longitude")
    return world_region(result["country"]["code"], longitude)
