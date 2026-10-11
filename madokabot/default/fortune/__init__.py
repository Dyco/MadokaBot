"""每日运势插件元数据与处理器入口。"""

from nonebot import require
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_datastore")
require("nonebot_plugin_htmlrender")

__plugin_meta__ = PluginMetadata(
    name="每日运势",
    description="每日运势插件，提供每日运势查询功能",
    usage="发送“运势”即可查看每日运势",
    type="application",
    extra={"help_category": "基础功能", "help_order": 12},
)

from . import handlers as handlers  # noqa: E402,F401
