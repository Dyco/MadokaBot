"""按日常、异世界与战斗题材生成动漫人生档案。"""

import random
from functools import lru_cache
from pathlib import Path

from madokabot.core.storage.json_store import JsonDataStore

from .anime_life import CATEGORY_NAMES, DANGER_RISK, draw_presence, simulate_anime_life
from .attributes import draw_attributes
from .identity import draw_option, validate_pool
from .potential import STAR_POINTS
from .resources import DATA_DIR, load_json_resource

ANIME_VERSION = "anime_v2"
# 字母战力为作品内部的玩法分档，不表示不同作品之间的实力换算。
COMBAT_POINTS = {"D": 2, "D+": 4, "C": 7, "C+": 10, "B": 13, "B+": 16, "A": 18, "A+": 19, "S": 20}
# 复用五项联合星级分布，同时保持可见魅力与人生婚育使用同一个属性。
ISEKAI_ATTRIBUTES = {"财富": "家境", "战力": "智力", "魅力": "魅力", "声望": "健康", "运气": "运气"}


def validate_anime_world(world: dict, source_ids: set[str]) -> None:
    """要求每部作品预设题材、危险度、标题图及题材适配的评级和死因。"""
    if world["category"] not in CATEGORY_NAMES or world["danger"] not in DANGER_RISK:
        raise ValueError(f"{world['title']}缺少有效的作品分类或世界危险度")
    if type(world["harem"]) is not bool or Path(world["logo"]).name != world["logo"]:
        raise ValueError(f"{world['title']}的后宫标记或标题图文件名无效")
    if not world["source_refs"] or not set(world["source_refs"]) <= source_ids:
        raise ValueError(f"{world['title']}的作品来源无效")
    if not world["death_causes"] or len(set(world["death_causes"])) != len(world["death_causes"]):
        raise ValueError(f"{world['title']}的死因为空或重复")
    factions = world.get("factions", [])
    if world["category"] == "battle":
        validate_pool(factions, f"{world['title']}的阵营")
        for faction in factions:
            ranks = faction.get("ranks") or world["ranks"]
            if not ranks or len({rank[0] for rank in ranks}) != len(ranks):
                raise ValueError(f"{world['title']}的阵营评级为空或重复")
            if any(weight <= 0 or combat not in COMBAT_POINTS for _, weight, combat in ranks):
                raise ValueError(f"{world['title']}的评级权重或战力分档无效")
            if "lifespan" in faction:
                minimum, maximum = faction["lifespan"]
                if not 18 <= minimum <= maximum:
                    raise ValueError(f"{world['title']}的阵营寿命范围无效")
    faction_ids = {faction["id"] for faction in factions}
    for event in world["events"]:
        if event["weight"] <= 0 or not set(event.get("factions", [])) <= faction_ids:
            raise ValueError(f"{world['title']}的大事件权重或适用阵营无效")
        if "age" in event and not 1 <= event["age"][0] <= event["age"][1]:
            raise ValueError(f"{world['title']}的大事件适用年龄无效")
    if world["danger"] == "安全" and world["events"]:
        raise ValueError(f"{world['title']}标为安全，不能配置危险大事件")


@lru_cache(maxsize=1)
def load_anime_data() -> dict:
    """读取精简的动漫资料，题材必填，保留共用资源目录与 JSON 存储入口。"""
    dataset = load_json_resource("anime/manifest.json")
    if dataset["schema_version"] != 2:
        raise ValueError("动漫资料格式版本不受支持")
    sources = JsonDataStore(DATA_DIR / "anime/sources.json").content
    source_ids = {source["id"] for source in sources}
    if len(source_ids) != len(sources):
        raise ValueError("动漫资料来源标识重复")
    worlds = [load_json_resource(f"anime/{filename}") for filename in dataset["world_files"]]
    validate_pool(worlds, "动漫作品列表")
    validate_pool(dataset["genders"], "动漫性别列表")
    for world in worlds:
        validate_anime_world(world, source_ids)
    return dataset | {"worlds": worlds}


def draw_battle_rank(world: dict, faction: dict, talent: float) -> tuple[str, str]:
    """在本阵营评级内抽取成长结果，较高天赋提高高战力档位的相对权重。"""
    ranks = faction.get("ranks") or world["ranks"]
    weights = [weight * 2 ** ((talent - 3) * COMBAT_POINTS[combat] / 10) for _, weight, combat in ranks]
    rank, _, combat = random.choices(ranks, weights=weights)[0]
    return rank, combat


def simulate_anime() -> dict:
    """按作品分类生成属性、存在感及人生结局，保存后重复查看不再抽取。"""
    dataset = load_anime_data()
    world = draw_option(dataset["worlds"])
    base = draw_attributes()
    category = world["category"]
    faction, rank, combat = {}, "", ""
    if category == "battle":
        attributes = {"天赋": base["智力"], "人气": base["魅力"]}
        faction = draw_option(world["factions"])
        rank, combat = draw_battle_rank(world, faction, attributes["天赋"])
        power = COMBAT_POINTS[combat] / 20
        score = round((sum(STAR_POINTS[value] for value in attributes.values()) + COMBAT_POINTS[combat]) * 5 / 3)
    else:
        attributes = base if category == "daily" else {name: base[source] for name, source in ISEKAI_ATTRIBUTES.items()}
        power = 0 if category == "daily" else attributes["战力"] / 5
        score = sum(STAR_POINTS[value] for value in attributes.values())
    presence = draw_presence(category, faction, base["魅力"])
    life = simulate_anime_life(world, base, faction, presence, power)
    return {
        "mode": "anime", "result_version": ANIME_VERSION, "dataset_version": dataset["version"],
        "title": dataset["title"], "notice": dataset["notice"],
        "world": {key: world[key] for key in ("id", "title", "category", "danger", "logo")},
        "gender": draw_option(dataset["genders"])["name"], "attributes": attributes,
        "faction": faction.get("name", ""), "rank": rank, "combat": combat,
        "presence": presence, "life": life, "score": score,
        "summary": " · ".join(value for value in (presence, faction.get("name", ""), rank) if value),
    }
