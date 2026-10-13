"""使用香港天文台本地月初对照表换算农历日期。"""

import json
from bisect import bisect_right
from datetime import date
from functools import lru_cache

from madokabot.core.resources import ResourceFolder, ResourceType, assets

LUNAR_DAYS = (
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
)


@lru_cache(maxsize=1)
def _load_calendar() -> tuple[date, date, list[date], list[str]]:
    """读取并缓存本地农历月初、公历有效范围和含闰月的月份名称。"""
    path = assets.get_dir(ResourceType.JSON, ResourceFolder.FORTUNE) / "lunar_months.json"
    calendar = json.loads(path.read_text(encoding="utf-8"))
    starts = [date.fromisoformat(item[0]) for item in calendar["months"]]
    names = [item[1] for item in calendar["months"]]
    return date.fromisoformat(calendar["start"]), date.fromisoformat(calendar["end"]), starts, names


def get_lunar_date(today: date) -> str:
    """在1901至2100年的月初表中定位农历月份，并按日期差计算农历日。"""
    first, last, starts, names = _load_calendar()
    if not first <= today <= last:
        raise ValueError("农历对照表支持1901至2100年的公历日期")
    index = bisect_right(starts, today) - 1
    day = (today - starts[index]).days
    return f"{names[index]}{LUNAR_DAYS[day]}"
