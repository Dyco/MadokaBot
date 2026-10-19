"""从 JSON 世界资料生成异世界出生档案。"""

import math
import random
from functools import lru_cache

from .resources import load_json_resource
from .isekai_life import complete_life


def validate_pool(rows: list[dict], label: str, *, weighted: bool = True) -> None:
    """检查资料标识；实际参与抽取的池另检查正数权重。"""
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError(f"异世界资料的{label}为空或标识重复")
    if weighted and any(not math.isfinite(row["weight"]) or row["weight"] <= 0 for row in rows):
        raise ValueError(f"异世界资料的{label}包含无效权重")


def validate_references(rows: list[dict], field: str, pool: list[dict], label: str) -> None:
    """检查配置引用非空且全部指向当前世界内的条目。"""
    ids = {row["id"] for row in pool}
    for row in rows:
        if not row[field] or not set(row[field]) <= ids:
            raise ValueError(f"异世界资料的{label}引用无效：{row['id']}")


def is_available(row: dict, setting_id: str, region_id: str) -> bool:
    """按资料声明的时代与地区筛选条目，不执行数据中的表达式。"""
    return (
        ("setting_ids" not in row or setting_id in row["setting_ids"])
        and ("region_ids" not in row or region_id in row["region_ids"])
    )


def power_candidates(world: dict, setting_id: str, region_id: str) -> list[dict]:
    """筛选组合及其每项力量都适用当前时代和地区的条目。"""
    powers = {row["id"]: row for row in world["powers"]}
    return [
        row for row in world["power_sets"] if is_available(row, setting_id, region_id)
        and all(is_available(powers[power_id], setting_id, region_id) for power_id in row["power_ids"])
    ]


def parent_candidates(world: dict, family: dict, setting_id: str, region_id: str) -> list[dict]:
    """筛选当前家庭、时代和地区可用且拥有力量组合的父母身份。"""
    available_sets = {row["id"] for row in power_candidates(world, setting_id, region_id)}
    return [
        row for row in world["parent_profiles"]
        if row["id"] in family["parent_profile_ids"]
        and is_available(row, setting_id, region_id)
        and available_sets.intersection(row["power_set_ids"])
    ]


def birth_candidates(axis: dict, family: dict, region: dict) -> list[dict]:
    """取家庭与地区出生条件的交集，防止轨道和地表照护条件混用。"""
    allowed = set(family["birth_options"][axis["id"]])
    if axis["id"] in region.get("birth_options", {}):
        allowed.intersection_update(region["birth_options"][axis["id"]])
    return [row for row in axis["options"] if row["id"] in allowed]


@lru_cache(maxsize=1)
def load_isekai_data() -> dict:
    """通过核心 JSON 工具读取资源清单及世界资料，并校验抽取池与引用。"""
    dataset = load_json_resource("isekai/manifest.json")
    worlds = [
        load_json_resource(f"isekai/{filename}")
        for filename in dataset["world_files"]
    ]
    source_catalog = load_json_resource(f"isekai/{dataset['source_catalog']}")
    sources = {source["id"] for source in source_catalog["sources"]}
    validate_pool(worlds, "世界列表")
    validate_pool(dataset["genders"], "性别列表")
    for world in worlds:
        fields = ("settings", "species", "regions", "families", "parent_profiles", "powers", "power_sets", "traits", "birth_axes")
        for field in fields:
            validate_pool(world[field], f"{world['title']}的{field}", weighted=field not in ("powers", "birth_axes"))
        evidence_rows = [world]
        for field in fields:
            evidence_rows.extend(world[field])
            for row in world[field]:
                for scope, pool in (("setting_ids", world["settings"]), ("region_ids", world["regions"])):
                    if scope in row:
                        validate_references([row], scope, pool, "时代与地区范围")
        for species in world["species"]:
            if "lineages" in species:
                validate_pool(species["lineages"], f"{species['name']}的祖源")
                evidence_rows.extend(species["lineages"])
        for axis in world["birth_axes"]:
            validate_pool(axis["options"], f"{axis['label']}的选项")
            evidence_rows.extend(axis["options"])
            option_ids = {row["id"] for row in axis["options"]}
            for family in world["families"]:
                allowed = family["birth_options"][axis["id"]]
                if not allowed or not set(allowed) <= option_ids:
                    raise ValueError(f"异世界资料的出生条件引用无效：{family['id']}/{axis['id']}")
            for region in world["regions"]:
                allowed = region.get("birth_options", {}).get(axis["id"], option_ids)
                if not allowed or not set(allowed) <= option_ids:
                    raise ValueError(f"异世界资料的地区出生条件无效：{region['id']}/{axis['id']}")
        for row in evidence_rows:
            if not row["source_refs"] or not set(row["source_refs"]) <= sources:
                raise ValueError(f"异世界资料的来源引用无效：{row['id']}")
        validate_references(world["regions"], "species_ids", world["species"], "地区种族")
        validate_references(world["regions"], "family_ids", world["families"], "地区家庭")
        validate_references(world["families"], "parent_profile_ids", world["parent_profiles"], "父母身份")
        validate_references(world["parent_profiles"], "power_set_ids", world["power_sets"], "父母力量组合")
        validate_references(world["power_sets"], "power_ids", world["powers"], "力量条目")
        for setting in world["settings"]:
            regions = [row for row in world["regions"] if is_available(row, setting["id"], row["id"])]
            if not regions:
                raise ValueError(f"异世界资料的时代没有地区：{setting['id']}")
            for region in regions:
                families = [
                    row for row in world["families"]
                    if row["id"] in region["family_ids"] and is_available(row, setting["id"], region["id"])
                ]
                if not families:
                    raise ValueError(f"异世界资料的地区没有可用家庭：{setting['id']}/{region['id']}")
                for family in families:
                    if not parent_candidates(world, family, setting["id"], region["id"]):
                        raise ValueError(f"异世界资料的家庭没有可用身份：{region['id']}/{family['id']}")
                    for axis in world["birth_axes"]:
                        if not birth_candidates(axis, family, region):
                            raise ValueError(f"异世界资料的家庭没有出生条件：{region['id']}/{family['id']}/{axis['id']}")
    return dataset | {"worlds": worlds}


def draw_entry(rows: list[dict], allowed_ids: list[str] | None = None) -> dict:
    """从当前上下文允许的条目中按资料权重抽取一次。"""
    candidates = rows if allowed_ids is None else [row for row in rows if row["id"] in allowed_ids]
    return random.choices(candidates, weights=[row["weight"] for row in candidates])[0]


def draw_parent(world: dict, family: dict, species: dict, lineage: str, role: str, setting_id: str, region_id: str) -> dict:
    """抽取适用地区与时代的身份及预定义力量组合，保持普通同族家庭。"""
    profile = draw_entry(parent_candidates(world, family, setting_id, region_id))
    power_set = draw_entry(power_candidates(world, setting_id, region_id), profile["power_set_ids"])
    power_map = {row["id"]: row for row in world["powers"]}
    powers = [power_map[power_id].copy() for power_id in power_set["power_ids"]]
    return {
        "role": role,
        "profile_id": profile["id"],
        "species_id": species["id"],
        "species": species["name"],
        "lineage": lineage,
        "occupation": profile["occupation"],
        "identity": profile["identity"],
        "power": powers[0],
        "powers": powers,
        "affiliation": profile["affiliation"],
        "resources": profile["resources"],
        "notes": list(dict.fromkeys(power_set["notes"] + [power["risk"] for power in powers if power["risk"]])),
        "source_refs": list(dict.fromkeys(profile["source_refs"] + power_set["source_refs"])),
    }


def simulate_isekai() -> dict:
    """按时代、地区与家庭联动抽取出生条件，并保存可追溯的结果快照。"""
    dataset = load_isekai_data()
    world = draw_entry(dataset["worlds"])
    setting = draw_entry(world["settings"])
    region = draw_entry([row for row in world["regions"] if is_available(row, setting["id"], row["id"])])
    species = draw_entry(world["species"], region["species_ids"])
    lineage = draw_entry(species["lineages"])["name"] if "lineages" in species else ""
    family = draw_entry([
        row for row in world["families"]
        if row["id"] in region["family_ids"] and is_available(row, setting["id"], region["id"])
    ])
    parents = [
        draw_parent(world, family, species, lineage, role, setting["id"], region["id"])
        for role in ("父亲", "母亲")
    ]
    aspects = []
    for axis in world["birth_axes"]:
        option = draw_entry(birth_candidates(axis, family, region))
        aspects.append({"label": axis["label"]} | {key: value for key, value in option.items() if key != "weight"})
    birth_notes = list(dict.fromkeys(
        world["birth_notes"] + [
            power["birth_note"] for parent in parents for power in parent["powers"] if power["birth_note"]
        ]
    ))
    trait = draw_entry(world["traits"])
    result = {
        "mode": "isekai",
        "result_version": "isekai_v2",
        "dataset_version": dataset["version"],
        "title": dataset["title"],
        "notice": dataset["notice"],
        "world": {key: world[key] for key in ("id", "title", "description")},
        "setting": {key: setting[key] for key in ("id", "name", "description")},
        "source_refs": world["source_refs"],
        "birthplace": {key: region[key] for key in ("id", "name", "description", "context")},
        "gender": draw_entry(dataset["genders"])["name"],
        "child": {
            "species_id": species["id"],
            "species": species["name"],
            "lineage": lineage,
            "birth_state": species["birth_state"],
            "features": species["features"],
            "life_span": species["life_span"],
            "aspects": aspects,
            "notes": birth_notes,
            "trait_label": world["trait_label"],
            "trait": {key: trait[key] for key in ("id", "name", "description")},
        },
        "household": {
            key: family[key]
            for key in ("id", "name", "description", "rarity", "resources", "directions", "challenge")
        } | {"resources": list(dict.fromkeys(family["resources"] + [item for parent in parents for item in parent["resources"]]))},
        "parents": parents,
    }

    return complete_life(result)
