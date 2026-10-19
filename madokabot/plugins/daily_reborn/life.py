"""根据现实投胎星级生成并保存游戏内的人生结果。"""

import random

# 资产为游戏内规模档位，不绑定现实国家的货币或经济预测。
ASSET_LEVELS = ("千元级", "万元级", "十万元级", "百万级", "千万级", "亿级", "十亿级", "百亿级")


def simulate_life(stars: dict) -> dict:
    """以属性联动人生结果，低运气放大资产波动及损失。"""
    rng = random.Random()
    family, health, intelligence, charm, luck = (stars[name] for name in ("家境", "健康", "智力", "魅力", "运气"))
    expected_age = 40 + health * 8 + family * 2 + luck * 2
    early_risk = .025 + (5 - health) * .02 + (5 - luck) * .01
    if rng.random() < early_risk:
        lifespan = rng.randint(1, round(expected_age * .6))
    else:
        lifespan = max(18, min(110, round(rng.gauss(expected_age, 8))))

    asset_power = 1 + family * .7 + intelligence * .35 + luck * .35 + charm * .1
    asset_power += rng.gauss(0, .65 + (5 - luck) * .15) - max(0, 30 - lifespan) / 10
    # 家境只影响起点，重大损失仍可使富裕家庭出身者落入最低资产档。
    loss_risk = .02 + (5 - luck) ** 2 * .015
    if rng.random() < loss_risk:
        asset_power -= rng.uniform(1.5, 3.5) + (5 - luck) * .4
    asset_level = max(0, min(len(ASSET_LEVELS) - 1, round(asset_power) - 3))

    marriage_age = rng.randint(18, 35)
    married = lifespan >= marriage_age and rng.random() < .4 + charm * .07 + luck * .02
    children = 0
    if married:
        children = rng.choices((0, 1, 2, 3, 4), weights=(18, 32, 32, 14, 4))[0]
        children = min(children, max(0, min(lifespan, 45) - marriage_age) // 2)
    return {"assets": ASSET_LEVELS[asset_level], "lifespan": lifespan, "married": married, "children": children}


def life_rows(life: dict) -> list[dict]:
    """统一图片与文字的资产、寿命和婚育展示格式。"""
    return [
        {"label": "个人资产", "value": life["assets"]},
        {"label": "最终寿命", "value": f"{life['lifespan']}岁"},
        {"label": "婚育子女", "value": f"{'结婚' if life['married'] else '未婚'} - {life['children']}名子女"},
    ]


def life_quality(life: dict, normal_age: float = 85) -> float:
    """按预期寿命归一化，存在资产结果时与资产档位等权综合；婚育不加减分。"""
    longevity = max(0, min(1, life["lifespan"] / normal_age))
    if "assets" not in life:
        return longevity
    wealth = ASSET_LEVELS.index(life["assets"]) / (len(ASSET_LEVELS) - 1)
    return (longevity + wealth) / 2
