"""异世界综合人生结果、父母资料与世界专属属性。"""

import random
import re

from .attributes import STAR_DISTRIBUTION
from .potential import STAR_POINTS

VERSION = "isekai_life_v1"
REALMS = ("凡人", "炼气", "筑基", "结丹", "元婴", "化神", "炼虚", "合体", "大乘")
YEARS = (85, 120, 220, 500, 1200, 2200, 5000, 10000, 18000)
SPECIES_YEARS = {"elf": 750, "dwarf": 350, "halfling": 150, "gnome": 425}


def cultivation_status(rank: int, gender: str, rng: random.Random) -> str:
    """按修为匹配宗门层级及职务，皇族身份按性别与修为细分。"""
    if rank == 0:
        return "散修 - 凡俗求道者"
    if rng.random() < .35:
        return "散修"
    if rank >= 4 and rng.random() < .12:
        role = "老祖" if rank >= 7 else "帝君" if rank >= 6 else ("皇子" if gender == "男" else "皇女")
        return f"皇族 - {role}"
    tiers = ("三级宗门", "二级宗门", "一级宗门", "仙宗", "圣宗")
    tier = tiers[min(4, max(0, rank - 2))]
    roles = ("杂役", "外门弟子") if rank == 1 else ("内门弟子", "执事") if rank == 2 else (
        "长老", "执事") if rank == 3 else ("长老", "大长老", "宗主") if rank < 7 else ("宗主", "老祖")
    if rank >= 5:
        roles += ("圣子" if gender == "男" else "圣女",)
    return f"{tier} - {rng.choice(roles)}"


def body_text(mechanical: int) -> str:
    """统一表达赛博躯体中人类组织与机械的比例。"""
    return f"人类({100 - mechanical}%) 机械({mechanical}%)"


def parent_fields(parent: dict, kind: str, region: str, rng: random.Random) -> list[dict]:
    """把父母现有身份及力量转换成各世界适用的精简资料。"""
    if kind == "cyberpunk":
        return [{"label": "职业", "value": parent["occupation"]}, {"label": "地区", "value": region},
                {"label": "躯体", "value": body_text(rng.choices((0, 15, 30, 45, 55, 70), (25, 25, 20, 15, 10, 5))[0])}]
    powers = parent["powers"]
    power = " / ".join(row["name"] for row in powers)
    identity = parent["identity"]
    label = "实力"
    if kind == "cultivation":
        rank = max((REALMS.index(row["name"]) if row["name"] in REALMS else 0 for row in powers), default=0)
        identity = cultivation_status(rank, "男" if parent["role"] == "父亲" else "女", rng) if rank else identity
        label = "玄力"
    elif kind == "occult_industrial":
        power = " / ".join(re.sub(r".*?序列(\d+) · ", r"序列\1 - ", row["name"]) for row in powers)
        label = "非凡力量"
    else:
        converted = []
        for row in powers:
            match = re.search(r"(.+) · (\d+)级", row["name"])
            if match:
                level = int(match[2])
                converted.append(("见习" if level < 3 else "熟练" if level < 5 else "资深" if level < 9 else "大师" if level < 13 else "传奇") + match[1])
            else:
                converted.append("普通居民")
        power = " / ".join(converted)
        identity = parent["occupation"]
    return [{"label": "身份", "value": identity}, {"label": "种族", "value": parent["species"]},
            {"label": label, "value": power}]


def complete_life(result: dict) -> dict:
    """联动家庭与四项星级，生成并保存世界专属的综合人生结果。"""
    rng = random.Random()
    kind = result["world"]["id"]
    rarity = result["household"]["rarity"]
    minimum = {"罕见": 2.5, "稀有": 3}.get(rarity, 1)
    family = rng.choices([v for v, _ in STAR_DISTRIBUTION if v >= minimum],
                         [w for v, w in STAR_DISTRIBUTION if v >= minimum])[0]
    stars = {"家境": family}
    for name in ("魅力", "智力", "运气"):
        options = [(v, w) for v, w in STAR_DISTRIBUTION if v >= (max(1, family - 2) if name == "魅力" else 1)]
        stars[name] = rng.choices([v for v, _ in options], [w for _, w in options])[0]
    ability = max(0, min(1, (stars["智力"] * .45 + stars["运气"] * .35 + family * .2 - 1) / 4 + rng.gauss(0, .12)))
    fortune = max(0, min(7, round(family * .8 + stars["智力"] * .3 + stars["运气"] * .4 + rng.gauss(0, 1) - 2)))
    wealth = ("勉强糊口", "温饱有余", "小有积蓄", "家资殷实", "富甲一方", "巨富之家", "商业巨头", "世界级财富")[fortune]
    parents = [dict(parent) for parent in result["parents"]]
    region = "轨道居住地" if "orbital" in result["birthplace"]["id"] else rng.choice(("北方国家", "南方国家", "中央都市圈"))
    for parent in parents:
        parent["fields"] = parent_fields(parent, kind, region, rng)
    body = result["child"]["species"]
    if kind == "cyberpunk":
        body = body_text(rng.choices((0, 10, 25, 45, 55, 70, 85), (20, 20, 20, 15, 12, 8, 5))[0])
    if kind == "cultivation":
        rank = min(8, round(ability * 8))
        age = max(20, round(YEARS[rank] * rng.uniform(.55, 1)))
        status = cultivation_status(rank, result["gender"], rng)
        details = [{"label": "玄力", "value": REALMS[rank]}, {"label": "寿命", "value": f"{age}岁"}, {"label": "地位", "value": status}]
        prestige = next((value for title, value in (("皇族", 1), ("圣宗", 1), ("仙宗", .8),
                        ("一级宗门", .6), ("二级宗门", .4), ("三级宗门", .2)) if title in status), .1)
        quality = (rank / 8 + age / YEARS[-1] + prestige) / 3
    else:
        normal_age = SPECIES_YEARS.get(result["child"]["species_id"], 85) if kind == "high_fantasy" else 100 if kind == "cyberpunk" else 85
        age = max(18, round(normal_age * rng.uniform(.5, 1.1) * (.7 + stars["运气"] * .08)))
        details = [{"label": "财富", "value": wealth}, {"label": "寿命", "value": f"{age}岁"}]
        if kind == "occult_industrial":
            # 使用世界资料已有的序列与名称，不凭空拼接非凡途径或混合序列。
            from .isekai import load_isekai_data
            world = next(row for row in load_isekai_data()["worlds"] if row["id"] == kind)
            options = [row for row in world["powers"] if row["id"] == "ordinary" or re.search(r"序列\d+", row["name"])]
            target = 10 - round(ability * 4)
            weights = []
            for row in options:
                match = re.search(r"序列(\d+)", row["name"])
                level = int(match[1]) if match else 10
                weights.append(max(.01, 1 - abs(level - target) * .45))
            power = rng.choices(options, weights)[0]["name"]
            details.append({"label": "非凡等级", "value": re.sub(r".*?序列(\d+) · ", r"序列\1 - ", power)})
        else:
            married = age >= 22 and rng.random() < .35 + stars["魅力"] * .09
            children = rng.choices((0, 1, 2, 3, 4), (20, 30, 32, 14, 4))[0] if married else 0
            children = min(children, max(0, age - 20) // 2)
            details.append({"label": "婚育子女", "value": f"{'已婚' if married else '未婚'} - {children}名子女"})
        quality = (fortune / 7 + min(1, age / normal_age)) / 2
        if kind == "occult_industrial":
            sequence = re.search(r"序列(\d+)", power)
            strength = min(1, (10 - int(sequence[1])) / 4) if sequence else 0
            quality = (fortune / 7 + min(1, age / normal_age) + strength) / 3
    score = min(100, max(0, round(sum(STAR_POINTS[value] for value in stars.values()) + quality * 20)))
    return result | {
        "result_version": VERSION,
        "attributes": stars, "parents": parents, "body": body, "life": details, "score": score,
    }

