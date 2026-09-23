"""Steam 插件元数据、命令和定时任务加载入口。"""

from nonebot.plugin import PluginMetadata, inherit_supported_adapters

from .config import SteamConfig
from .matchers import STEAM_USAGE

__plugin_meta__ = PluginMetadata(
    name="Steam Info",
    description="Steam 好友状态查询与播报，主指令为steam",
    usage=STEAM_USAGE,
    type="application",
    homepage="https://github.com/zhaomaoniu/nonebot-plugin-steam-info",
    config=SteamConfig,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
)

from . import commands as commands  # noqa: E402,F401
from . import scheduler as scheduler  # noqa: E402,F401
