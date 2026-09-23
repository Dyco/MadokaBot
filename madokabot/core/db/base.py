"""共享数据库模型基类与默认时间支持。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from nonebot_plugin_datastore import get_plugin_data

# 保留历史数据命名空间，各业务模型共用同一份元数据。
data = get_plugin_data("madoka_bundle")
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    """返回用于数据库默认时间的上海时区当前时间。"""
    return datetime.now(_SHANGHAI_TZ)
