"""动漫题材的存在感、世界风险与人生结局。"""

import random

from .life import simulate_life

# 作品分类和世界危险度必须由资料作者预设，不能根据抽到的身份临时改写。
CATEGORY_NAMES = {"daily": "日常番", "isekai": "异世界番", "battle": "战斗番"}
DANGER_RISK = {"安全": 0, "和平": .03, "动荡": .14, "危险": .30, "灾难": .50}
PRESENCE_WEIGHTS = {"路人": 42, "配角": 18, "炮灰": 15, "工具人": 10, "反派": 9, "大反派": 5, "主角": 1}


def draw_presence(category: str, faction: dict, popularity: float) -> str:
    """日常番排除反派，敌对阵营使用反派定位，其余角色按存在感权重抽取。"""
    options = list(PRESENCE_WEIGHTS)
    if category == "daily":
        options = [name for name in options if name not in {"反派", "大反派"}]
    elif faction.get("antagonist"):
        options = ["反派", "大反派"]
    weights = [PRESENCE_WEIGHTS[name] * (1 + popularity / 5 if name in {"配角", "主角"} else 1) for name in options]
    return random.choices(options, weights=weights)[0]


def draw_death(world: dict, faction: dict, lifespan: int) -> str:
    """只从本作品、本阵营及适用年龄的大事件中选择死因，禁止跨作品混用。"""
    causes = [(cause, 1) for cause in faction.get("death_causes", world["death_causes"])]
    causes.extend(
        (event["name"], event["weight"]) for event in world["events"]
        if (not event.get("factions") or faction.get("id") in event["factions"])
        and ("age" not in event or event["age"][0] <= lifespan <= event["age"][1])
    )
    return random.choices([name for name, _ in causes], weights=[weight for _, weight in causes])[0]


def simulate_anime_life(world: dict, base: dict, faction: dict, presence: str, power: float) -> dict:
    """联动健康、运气、战力和世界风险生成寿命，婚育受生存年龄及阵营限制。"""
    original = simulate_life(base)
    lifespan = original["lifespan"]
    if "lifespan" in faction:
        minimum, maximum = faction["lifespan"]
        lifespan = round(random.triangular(minimum, maximum, minimum + (maximum - minimum) * base["健康"] / 5))
    risk = DANGER_RISK[world["danger"]] * (1 + (3 - base["运气"]) * .12) * (1 - power * .45)
    if presence == "炮灰":
        risk *= 1.35
    elif presence == "主角":
        risk *= .7
    if random.random() < risk:
        lifespan = random.randint(1, round(lifespan * .75))
        death = draw_death(world, faction, lifespan)
    else:
        death = faction.get("natural_death", "寿终正寝" if lifespan >= 65 else "疾病")
    marriage_age = random.randint(18, 35)
    married = (
        faction.get("marriage", True) and lifespan >= marriage_age
        and random.random() < .4 + base["魅力"] * .07 + base["运气"] * .02
    )
    spouses = 0
    children = 0
    if married:
        spouses = random.choices((1, 2, 3, 4), weights=(50, 28, 16, 6))[0] if world["harem"] else 1
        children = sum(random.choices((0, 1, 2, 3, 4), weights=(18, 32, 32, 14, 4), k=spouses))
        children = min(children, max(0, min(lifespan, 45) - marriage_age) // 2 * spouses)
    return {"lifespan": lifespan, "death": death, "married": married, "spouses": spouses, "children": children}


def anime_life_rows(result: dict) -> list[dict]:
    """统一图片和文字的存在感、寿命死因与单婚或后宫婚育展示。"""
    life = result["life"]
    lifespan = f"{life['lifespan']}岁"
    if result["world"]["category"] != "daily":
        lifespan += f" - 死于（{life['death']}）"
    marriage = "结婚" if life["married"] else "未婚"
    if life["spouses"] > 1:
        marriage += f"（{('零', '一', '二', '三', '四')[life['spouses']]}人） - 共{life['children']}名子女"
    else:
        marriage += f" - {life['children']}名子女"
    return [
        {"label": "存在感", "value": result["presence"]},
        {"label": "最终寿命", "value": lifespan},
        {"label": "婚育子女", "value": marriage},
    ]
