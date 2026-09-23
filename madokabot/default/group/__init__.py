"""群访问名单管理与自动退群。"""

from nonebot.plugin import PluginMetadata

from .config import GroupConfig

__plugin_meta__ = PluginMetadata(
    name="群管理",
    description="管理群白名单、黑名单并根据群人数执行自动退群",
    usage="群白名单 添加/删除/列表 [群号]\n群黑名单 添加/删除/列表 [群号]",
    type="application",
    config=GroupConfig,
)

from . import handlers as handlers  # noqa: E402,F401
from . import auto_leave as auto_leave  # noqa: E402,F401
