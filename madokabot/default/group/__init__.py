"""群访问名单、群资料同步与自动退群。"""

from nonebot.plugin import PluginMetadata

from .config import GroupConfig

__plugin_meta__ = PluginMetadata(
    name="群管理",
    description="管理群访问名单、同步群资料并根据人数执行自动退群",
    usage="群白名单 添加/删除/列表 [群号]\n群黑名单 添加/删除/列表 [群号]",
    type="application",
    config=GroupConfig,
)

from . import handlers as handlers  # noqa: E402,F401
from . import profile as profile  # noqa: E402,F401
from . import auto_leave as auto_leave  # noqa: E402,F401
