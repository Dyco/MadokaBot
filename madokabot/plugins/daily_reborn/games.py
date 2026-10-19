"""按游戏预设生成角色属性、养成进度及模拟卡池表现。"""

import random
from functools import lru_cache
from pathlib import Path

from madokabot.core.storage.json_store import JsonDataStore

from .attributes import draw_star
from .identity import draw_option, validate_pool
from .resources import DATA_DIR, load_json_resource

GAMES_VERSION = "games_v2"
# 稀有度由低至高配置，最高档使用金色，六星制比五星制多一个基础档。
RARITY_TONES = ("copper", "slate", "jade", "azure", "violet", "gold")


@lru_cache(maxsize=1)
def load_games_data() -> dict:
    """读取精简二游配置，检查地区、属性、稀有度和各档养成上限。"""
    dataset = load_json_resource("games/manifest.json")
    if dataset["schema_version"] != 2:
        raise ValueError("二游资料格式版本不受支持")
    sources = JsonDataStore(DATA_DIR / "games/sources.json").content
    source_ids = {source["id"] for source in sources}
    if len(source_ids) != len(sources):
        raise ValueError("二游资料来源标识重复")
    worlds = [load_json_resource(f"games/{filename}") for filename in dataset["world_files"]]
    validate_pool(worlds, "二游作品列表")
    validate_pool(dataset["genders"], "二游性别列表")
    for world in worlds:
        if not world["source_refs"] or not set(world["source_refs"]) <= source_ids:
            raise ValueError(f"{world['title']}的来源引用无效")
        if not world["regions"] or not world["combat_attributes"] or Path(world["logo"]).name != world["logo"]:
            raise ValueError(f"{world['title']}的地区、战斗属性或标题图无效")
        rarities = world["rarities"]
        if not 2 <= len(rarities) <= len(RARITY_TONES) or len(set(rarities)) != len(rarities):
            raise ValueError(f"{world['title']}的稀有度配置无效")
        if not world["awakening"]["label"] or not 1 <= world["awakening"]["max"] <= 6:
            raise ValueError(f"{world['title']}的觉醒次数配置无效")
        caps = world["level_caps"]
        if "default" not in caps or not set(caps) <= {"default", *rarities}:
            raise ValueError(f"{world['title']}的等级模板引用无效")
        for values in caps.values():
            if not values or any(type(value) is not int or value <= 0 for value in values) or values != sorted(set(values)):
                raise ValueError(f"{world['title']}的等级上限无效")
    return dataset | {"worlds": worlds}


def revenue_label(revenue: int) -> str:
    """将模拟卡池收入归为万元级至十亿级，不展示伪精确流水。"""
    for minimum, label in ((10**9, "十亿级"), (10**8, "亿元级"), (10**7, "千万元级"), (10**6, "百万元级"), (10**5, "十万元级")):
        if revenue >= minimum:
            return label
    return "万元级"


def game_detail_rows(result: dict) -> list[dict]:
    """统一卡片和文字的等级、模拟流水及角色持有人数。"""
    return [
        {"label": "等级", "value": f"{result['level']}/{result['level_cap']}"},
        {"label": "卡池流水", "value": revenue_label(result["revenue"])},
        {"label": "抽取玩家", "value": str(result["players"])},
    ]


def simulate_games() -> dict:
    """联动角色人气、战力与觉醒形成评级，并生成等级、持有人数和卡池收入。"""
    dataset = load_games_data()
    world = draw_option(dataset["worlds"])
    attributes = {"人气": draw_star(), "战力": draw_star()}
    maximum = world["awakening"]["max"]
    awakening = random.choices(range(maximum + 1), weights=[.6**index for index in range(maximum + 1)])[0]
    quality = (sum(attributes.values()) - 2) / 8 * .9 + awakening / maximum * .1
    index = min(len(world["rarities"]) - 1, int(quality * len(world["rarities"])))
    rarity = world["rarities"][index]
    caps = world["level_caps"].get(rarity, world["level_caps"]["default"])
    stage = random.randrange(len(caps))
    level_cap = caps[stage]
    # 方舟精英化后等级重置；其他游戏沿用已解锁的相邻突破区间。
    minimum = 1 if world["id"] == "arknights" or stage == 0 else caps[stage - 1]
    popularity = (attributes["人气"] - 1) / 4
    holding_rate = 1 - index / (len(world["rarities"]) - 1) * .65
    players = round(10 ** random.uniform(3 + popularity * 2, 4 + popularity * 3) * holding_rate)
    spending = random.uniform(30, 300) * (1 + quality * 3) * (1 + awakening / maximum * .5)
    revenue = round(max(10_000, min(9_999_999_999, players * spending)))
    region = random.choice(world["regions"])
    combat_attribute = random.choice(world["combat_attributes"])
    return {
        "mode": "games", "result_version": GAMES_VERSION, "dataset_version": dataset["version"],
        "title": dataset["title"], "notice": dataset["notice"],
        "world": {key: world[key] for key in ("id", "title", "logo")}, "region": region,
        "gender": draw_option(dataset["genders"])["name"], "attributes": attributes,
        "awakening": world["awakening"] | {"count": awakening}, "combat_attribute": combat_attribute,
        "level": random.randint(minimum, level_cap), "level_cap": level_cap,
        "revenue": revenue, "players": players,
        "rating": {"value": rarity, "tier": RARITY_TONES[-len(world["rarities"]) + index]},
        "summary": f"{region} · {combat_attribute}",
    }
