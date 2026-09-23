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
        "CS unsub <赛事ID>\n"
        "CS nosub\n"
        "CS removesub <赛事ID>\n"
        "CS check <比赛链接>\n"
        "CS list <比赛ID>\n"
        "CS prediction <队伍名|A/B> <积分>\n"
        "CS prediction rank <本群|全部>\n"
        "CS login <手机号> <验证码>\n"
        "CS bind <5E|5e|5eplay|wm|pw|完美> <用户昵称>\n"
        "CS unbind <5E|5e|5eplay|wm|pw|完美>\n"
        "CS 战绩 <5E | 5e | 5eplay> [玩家昵称]\n"
        "CS 战绩 <wm | pw | 完美> [Steam ID]\n"
    ),
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
)

# 分别注册命令处理器和定时任务。
from . import commands as commands  # noqa: E402,F401
from . import scheduler as scheduler  # noqa: E402,F401
