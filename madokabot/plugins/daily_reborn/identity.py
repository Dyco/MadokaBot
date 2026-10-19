"""二次元与二游共用的权重校验及抽取。"""

import math
import random


def validate_pool(rows: list[dict], label: str) -> None:
    """检查资料标识唯一且抽取权重为有限正数。"""
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError(f"作品资料的{label}为空或标识重复")
    if any(not math.isfinite(row["weight"]) or row["weight"] <= 0 for row in rows):
        raise ValueError(f"作品资料的{label}包含无效权重")

def draw_option(options: list[dict]) -> dict:
    """按配置权重抽取条目，权重不表示原作人口或能力分布。"""
    return random.choices(options, weights=[option["weight"] for option in options])[0]
