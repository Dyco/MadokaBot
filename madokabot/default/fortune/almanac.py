"""接入 lunar-python 的中文农历和每日黄历宜忌。"""

from datetime import date
from functools import lru_cache

from lunar_python import Solar


def format_activities(items: list[str]) -> str:
    """保留来源顺序，每行最多展示4个完整词条并控制卡片文字长度。"""
    selected = []
    for item in items:
        if len(selected) == 4 or len("、".join([*selected, item])) > 18:
            break
        selected.append(item)
    return "、".join(selected) or "暂无"


@lru_cache(maxsize=8)
def get_almanac(today: date) -> tuple[str, str, str]:
    """按上海公历日期读取离线黄历数据，同一天复用不可变结果。"""
    lunar = Solar.fromYmd(today.year, today.month, today.day).getLunar()
    lunar_date = f"{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}"
    return (
        lunar_date,
        format_activities(lunar.getDayYi()),
        format_activities(lunar.getDayJi()),
    )
