"""按游戏预设生成角色属性、养成进度及模拟卡池表现。"""

import random
from functools import lru_cache
from math import log10
from pathlib import Path

from madokabot.core.storage.json_store import JsonDataStore

from .attributes import draw_star
from .identity import draw_option, validate_pool
from .potential import attribute_quality
from .resources import DATA_DIR, load_json_resource

GAMES_VERSION = "games_v4"
# 色阶由低至高配置，最高档金色；按实际评级档数取末尾对应色阶。
RARITY_TONES = ("copper", "slate", "jade", "azure", "violet", "gold")


@lru_cache(maxsize=1)
def load_games_data() -> dict:
    """读取二游配置，校验流水分档、稀有度及各档养成上限。"""
    dataset = load_json_resource("games/manifest.json")
    if dataset["schema_version"] != 2:
        raise ValueError("二游资料格式版本不受支持")
    ranges = dataset["revenue_ranges"]
    if not 2 <= len(ranges) <= len(RARITY_TONES):
        raise ValueError("二游流水分档数量无效")
    previous = (0, 0)
    for bounds in ranges:
        if len(bounds) != 2 or any(type(value) is not int for value in bounds):
            raise ValueError("二游流水范围须为整数上下限")
        lower, upper = bounds
        if not 0 < lower <= upper or lower <= previous[0] or upper <= previous[1]:
            raise ValueError("二游流水范围无效或未按评级递增")
        previous = bounds
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
        if len(rarities) != len(ranges) or len(set(rarities)) != len(rarities):
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
    """按实际金额显示百元至十亿级，避免低评级流水被误标成万元。"""
    for minimum, label in (
        (10**9, "十亿级"), (10**8, "亿元级"), (10**7, "千万元级"), (10**6, "百万元级"),
        (10**5, "十万元级"), (10**4, "万元级"), (10**3, "千元级"),
    ):
        if revenue >= minimum:
            return label
    return "百元级"


def game_detail_rows(result: dict) -> list[dict]:
    """统一卡片和文字的等级、模拟流水及角色持有人数。"""
    return [
        {"label": "等级", "value": f"{result['level']}/{result['level_cap']}"},
        {"label": "卡池流水", "value": revenue_label(result["revenue"])},
        {"label": "抽取玩家", "value": str(result["players"])},
    ]


def game_rating_index(world: dict, attributes: dict, growth: float) -> int:
    """按属性与养成定档，双三星可达最高档，流水不反向决定评级。"""
    quality = attribute_quality(attributes.values()) + growth * .15
    count = len(world["rarities"])
    index = min(count - 2, int(quality * (count - 1) / .6))
    if min(attributes.values()) >= 2.5 and quality >= .48:
        index = count - 1
    return index


def simulate_games() -> dict:
    """先评定角色等级，再按该档生成流水与持有人数，不生成百分制分数。"""
    dataset = load_games_data()
    world = draw_option(dataset["worlds"])
    attributes = {"人气": draw_star(), "战力": draw_star()}
    maximum = world["awakening"]["max"]
    awakening = random.choices(range(maximum + 1), weights=[.6**index for index in range(maximum + 1)])[0]
    quality = attribute_quality(attributes.values())
    growth = awakening / maximum
    index = game_rating_index(world, attributes, growth)
    popularity = (attributes["人气"] - 1) / 4
    combat = (attributes["战力"] - 1) / 4
    appeal = popularity * .65 + combat * .35
    lower, upper = dataset["revenue_ranges"][index]
    low_log, high_log = log10(lower), log10(upper + 1)
    target_log = random.triangular(low_log, high_log, low_log + (high_log - low_log) * (.7 * appeal + .3 * growth))
    target = 10 ** target_log
    # 在档位内按数量级波动；限制单人投入，保证整数人数与投入的乘积仍落在该档。
    spending = min(
        upper - lower + 1,
        max(1, round(random.uniform(50, 200) * (1 + quality * 2) * (1 + growth * .5))),
    )
    minimum_players = (lower + spending - 1) // spending
    maximum_players = upper // spending
    players = max(minimum_players, min(maximum_players, round(target / spending)))
    revenue = players * spending
    rarity = world["rarities"][index]
    caps = world["level_caps"].get(rarity, world["level_caps"]["default"])
    stage = random.randrange(len(caps))
    level_cap = caps[stage]
    # 方舟精英化后等级重置；其他游戏沿用已解锁的相邻突破区间。
    minimum = 1 if world["id"] == "arknights" or stage == 0 else caps[stage - 1]
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
    }
