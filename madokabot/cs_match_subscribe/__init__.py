from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")
require("nonebot_plugin_alconna")
require("nonebot_plugin_htmlrender")

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="CS相关插件，支持订阅HLTV赛事或查询5E/完美平台玩家信息",
    description="查询 HLTV CS 赛事数据，渲染 Rating 3.0 统计卡片并订阅赛事比赛更新。",
    usage=(
        "CS help\n"
        "CS list event\n"
        "CS sub <赛事ID>\n"
        "CS check <比赛链接>\n"
        "CS login <手机号> <验证码>\n"
        "CS bind <5E|5e|5eplay|wm|pw|完美> <用户昵称>\n"
        "CS unbind <5E|5e|5eplay|wm|pw|完美>\n"
        "CS 战绩 <5E|5e|5eplay|wm|pw|完美> [玩家昵称]\n"
    ),
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
)

# 导入 matcher 完成 NoneBot 指令注册。
from . import matchers as _matchers  # noqa: E402,F401
