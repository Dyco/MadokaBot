"""HLTV 赛事查询与订阅插件。"""

from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")
require("nonebot_plugin_alconna")

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="HLTV 赛事查询与订阅",
    description="查询 HLTV CS 赛事数据，渲染 Rating 3.0 统计卡片并订阅比赛更新。",
    usage=(
        "CS help\n"
        "CS sub <赛事ID>\n"
        "例如：CS sub 2397623"
    ),
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
)

# 导入 matcher 完成 NoneBot 指令注册。
from . import matchers as _matchers  # noqa: E402,F401
