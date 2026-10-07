"""数据库模型基类。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from nonebot_plugin_datastore import get_plugin_data

# 保留历史数据库命名空间。
data = get_plugin_data("madoka_bundle")
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    """上海时间获取方法。"""
    return datetime.now(_SHANGHAI_TZ)
