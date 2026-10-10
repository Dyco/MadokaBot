"""按出生人数加权抽样并生成游戏属性。"""

import json
import math
import random
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ATTRIBUTES = ("家境", "健康", "智力", "魅力", "运气")


@lru_cache(maxsize=1)
def load_population() -> dict:
    """读取随插件发布的联合国人口快照，拒绝无效的抽样权重。"""
    dataset = json.loads((DATA_DIR / "population.json").read_text(encoding="utf-8"))
    countries = dataset["countries"]
    if not countries or len({row["code"] for row in countries}) != len(countries):
        raise ValueError("出生人口数据为空或存在重复地区")
    for row in countries:
        if not math.isfinite(row["births"]) or row["births"] <= 0:
            raise ValueError(f"出生人口权重无效：{row['code']}")
    return dataset


def score_label(score: int) -> tuple[str, str]:
    """根据五项随机属性的平均分给出评价与寄语。"""
    for threshold, label, comment in (
        (85, "SSR · 天选开局", "你抽到了闪闪发光的起点，接下来去写自己的故事吧。"),
        (70, "SR · 顺风启程", "行囊里装着不少好牌，勇敢出发就好。"),
        (50, "R · 平凡新生", "平凡的开场，也可以走向很精彩的远方。"),
        (0, "N · 逆风成长", "开局有些挑战，但人生的后续章节还留着空白。"),
    ):
        if score >= threshold:
            return label, comment
    raise ValueError("综合分不能小于零")


def simulate_rebirth() -> dict:
    """以年度出生人数为权重抽取地区，性别按出生性别比抽取，评分仅用游戏属性。"""
    dataset = load_population()
    countries = dataset["countries"]
    country = random.choices(countries, weights=[row["births"] for row in countries])[0]
    attributes = {name: random.randint(1, 100) for name in ATTRIBUTES}
    score = round(sum(attributes.values()) / len(attributes))
    label, comment = score_label(score)
    # 联合国出生性别比的单位为每 100 名女婴对应的男婴数量。
    ratio = country["sex_ratio"]
    gender = "男" if random.random() < ratio / (ratio + 100) else "女"
    return {
        "country": country,
        "data_year": dataset["year"],
        "source": dataset["source"],
        "probability": country["births"] / sum(row["births"] for row in countries),
        "gender": gender,
        "attributes": attributes,
        "score": score,
        "label": label,
        "comment": comment,
    }
