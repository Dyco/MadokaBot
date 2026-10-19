"""汇总属性与人生质量后的边际递减评分及视觉分档。"""

from collections.abc import Iterable

EVALUATION_SYSTEM = "potential_v3"
# 保留低分段较快增长，四星以上再接近满分；曲线统一作用于综合质量。
BASE_SCORE = 20
PERFECT_QUALITY = .84
SCORE_POWER = .7


def attribute_quality(stars: Iterable[float]) -> float:
    """按平均水平占七成五、最突出属性占两成五汇总，保持顺序无关和单调递增。"""
    values = [(value - 1) / 4 for value in stars]
    return .75 * sum(values) / len(values) + .25 * max(values)


def calculate_score(stars: Iterable[float], life_quality: float) -> int:
    """先汇总六成五属性与三成五人生质量，再用凹幂函数实现总量边际递减。"""
    quality = .65 * attribute_quality(stars) + .35 * max(0, min(1, life_quality))
    if quality >= PERFECT_QUALITY:
        return 100
    # 未满足满分条件时最多九十九分，避免四舍五入提前得到一百分。
    return min(99, round(BASE_SCORE + (100 - BASE_SCORE) * (quality / PERFECT_QUALITY) ** SCORE_POWER))


def score_tier(score: int) -> str:
    """按分数划分静态色彩与材质档位，不生成字母评级或评级文案。"""
    for threshold, tier in (
        (100, "perfect"), (95, "prismatic"), (90, "gold"),
        (80, "violet"), (70, "azure"), (60, "jade"), (40, "slate"), (0, "copper"),
    ):
        if score >= threshold:
            return tier
    raise ValueError("评分不能为负数")
