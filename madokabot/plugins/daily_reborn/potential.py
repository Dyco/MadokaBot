"""五项星级的递减增益评分与静态视觉分档。"""

from .attributes import ATTRIBUTES

EVALUATION_SYSTEM = "potential_v2"
# 四星后进入边际递减区，每项每提升半星仅加一分；低中星级保留更明显的差距。
STAR_POINTS = {1: 2, 1.5: 4, 2: 7, 2.5: 10, 3: 13, 3.5: 16, 4: 18, 4.5: 19, 5: 20}


def calculate_score(stars: dict) -> int:
    """累加五项递减分值，全四星九十分、全四星半九十五分、仅全五星一百分。"""
    return sum(STAR_POINTS[stars[name]] for name in ATTRIBUTES)


def score_tier(score: int) -> str:
    """按分数划分静态色彩与材质档位，不生成字母评级或评级文案。"""
    for threshold, tier in (
        (100, "perfect"), (95, "prismatic"), (90, "gold"),
        (80, "violet"), (70, "azure"), (60, "jade"), (40, "slate"), (0, "copper"),
    ):
        if score >= threshold:
            return tier
    raise ValueError("评分不能为负数")


def evaluate_life(stars: dict) -> dict:
    """根据已保存星级计算当前评分，不叠加破坏分值锚点的天赋保底或共鸣加分。"""
    return {"evaluation_system": EVALUATION_SYSTEM, "score": calculate_score(stars)}
