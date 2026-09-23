"""签到插件元数据与处理器加载入口。"""

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="每日签到",
    description="每日签到插件",
    usage="每日签到，用于获取积分",
    type="application",
)

from . import handlers as handlers  # noqa: E402,F401
