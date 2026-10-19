"""作品身份档案共用的资料校验、条件抽取与结果快照。"""

import math
import random
from functools import lru_cache

from madokabot.core.storage.json_store import JsonDataStore

from .resources import DATA_DIR, load_json_resource


def validate_pool(rows: list[dict], label: str) -> None:
    """检查资料标识唯一且抽取权重为有限正数。"""
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError(f"作品资料的{label}为空或标识重复")
    if any(not math.isfinite(row["weight"]) or row["weight"] <= 0 for row in rows):
        raise ValueError(f"作品资料的{label}包含无效权重")


def matching_options(pool: dict, selected: dict[str, str]) -> list[dict]:
    """仅保留满足所有前置字段条件的条目，不执行配置表达式。"""
    return [
        option for option in pool["options"]
        if all(selected[key] in ids for key, ids in option.get("requires", {}).items())
    ]


def validate_world(world: dict, source_ids: set[str]) -> None:
    """检查字段、资料或玩法依据及全部条件分支，防止资料组合断路。"""
    pools = world["pools"]
    pool_ids = [pool["id"] for pool in pools]
    if len(set(pool_ids)) != len(pool_ids) or not {"faction", "rating"} <= set(pool_ids):
        raise ValueError(f"{world['title']}的字段重复或缺少阵营、评级")
    fields = [field for section in world["sections"] for field in section["fields"]]
    visible = {pool["id"] for pool in pools if not pool.get("hidden") and pool["id"] != "rating"}
    if len(fields) != len(set(fields)) or set(fields) != visible:
        raise ValueError(f"{world['title']}的展示分区与字段不一致")
    if not world["history_fields"] or not set(world["history_fields"]) <= visible:
        raise ValueError(f"{world['title']}的历史摘要引用无效")
    previous = {}
    for pool in pools:
        validate_pool(pool["options"], f"{world['title']}的{pool['id']}")
        for option in pool["options"]:
            refs = option["source_refs"]
            basis = option.get("basis", "original")
            if (
                basis not in {"original", "gameplay"} or not set(refs) <= source_ids
                or (basis == "original" and not refs)
                or (basis == "gameplay" and not option.get("description"))
            ):
                raise ValueError(f"{world['title']}的资料或玩法依据无效：{option['id']}")
            if "range" in option:
                bounds = option["range"]
                if len(bounds) != 2 or any(type(value) is not int for value in bounds) or bounds[0] > bounds[1]:
                    raise ValueError(f"{world['title']}的数值范围无效：{option['id']}")
                if "value" in option or not isinstance(option["unit"], str):
                    raise ValueError(f"{world['title']}的数值格式无效：{option['id']}")
            elif not isinstance(option["value"], str):
                raise ValueError(f"{world['title']}的条目文本无效：{option['id']}")
            for key, ids in option.get("requires", {}).items():
                if key not in previous or not ids or not set(ids) <= previous[key]:
                    raise ValueError(f"{world['title']}的前置条件无效：{option['id']}")
        previous[pool["id"]] = {option["id"] for option in pool["options"]}

    states = {()}
    for index, pool in enumerate(pools):
        future_keys = {
            key for later in pools[index + 1:] for option in later["options"]
            for key in option.get("requires", {})
        }
        next_states, reached = set(), set()
        for state in states:
            selected = dict(state)
            options = matching_options(pool, selected)
            if not options:
                raise ValueError(f"{world['title']}的{pool['id']}存在无可用条目的分支：{selected}")
            for option in options:
                reached.add(option["id"])
                values = selected | {pool["id"]: option["id"]}
                next_states.add(tuple(sorted((key, value) for key, value in values.items() if key in future_keys)))
        if reached != previous[pool["id"]]:
            raise ValueError(f"{world['title']}的{pool['id']}含有不可达条目")
        states = next_states


@lru_cache(maxsize=2)
def load_identity_data(folder: str) -> dict:
    """通过核心 JSON 工具加载作品清单与来源登记，更新资料后重启生效。"""
    dataset = load_json_resource(f"{folder}/manifest.json")
    if dataset["schema_version"] != 1:
        raise ValueError("作品资料格式版本不受支持")
    sources = JsonDataStore(DATA_DIR / folder / "sources.json").content
    source_ids = {source["id"] for source in sources}
    if len(source_ids) != len(sources):
        raise ValueError("作品资料来源标识重复")
    worlds = [load_json_resource(f"{folder}/{filename}") for filename in dataset["world_files"]]
    validate_pool(worlds, "世界列表")
    validate_pool(dataset["genders"], "性别列表")
    for world in worlds:
        validate_world(world, source_ids)
    return dataset | {"worlds": worlds, "sources": {source["id"]: source for source in sources}}


def draw_option(options: list[dict]) -> dict:
    """按配置权重抽取条目，权重不表示原作人口或能力分布。"""
    return random.choices(options, weights=[option["weight"] for option in options])[0]


def option_value(option: dict) -> str:
    """从配置的整数范围抽取数值并追加单位，不执行配置中的表达式。"""
    if "range" in option:
        return f"{random.randint(*option['range'])}{option['unit']}"
    return option["value"]


def simulate_identity(dataset: dict, *, mode: str) -> dict:
    """按作品内的前置条件抽取档案，并保存字段与引用来源的完整快照。"""
    world = draw_option(dataset["worlds"])
    selected, rows = {}, {}
    for pool in world["pools"]:
        option = draw_option(matching_options(pool, selected))
        selected[pool["id"]] = option["id"]
        rows[pool["id"]] = {
            "label": pool["label"], "value": option_value(option),
            "description": option.get("description", ""), "source_refs": option["source_refs"],
            "basis": option.get("basis", "original"),
        }
    refs = list(dict.fromkeys(ref for row in rows.values() for ref in row["source_refs"]))
    return {
        "mode": mode, "result_version": f"{mode}_v1", "dataset_version": dataset["version"],
        "title": dataset["title"], "notice": dataset["notice"],
        "world": {key: world[key] for key in ("id", "title", "description", "scope")},
        "gender": draw_option(dataset["genders"])["name"], "selections": selected,
        "faction": rows["faction"]["value"], "rating": rows["rating"],
        "summary": " · ".join(rows[key]["value"] for key in world["history_fields"]),
        "sections": [
            {"title": section["title"], "rows": [rows[key] for key in section["fields"]]}
            for section in world["sections"]
        ],
        "sources": [dataset["sources"][ref] for ref in refs],
    }
