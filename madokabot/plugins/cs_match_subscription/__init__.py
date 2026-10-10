from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")
require("nonebot_plugin_alconna")
require("nonebot_plugin_htmlrender")

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="CS插件",
    description="查询HLTV CS赛事数据，渲染Rating 3.0统计卡片并订阅赛事比赛更新。",
    usage=(
        "CS help\n"
        "CS event\n"
        "CS event <all|single|notif|predict>\n"
        "CS sub <赛事ID>\n"
        "CS unsub <赛事ID>\n"
        "CS nosub\n"
        "CS removesub <赛事ID>\n"
        "CS check <比赛链接>\n"
        "CS list <比赛ID>\n"
        "CS prediction <队伍名|竞猜编号> <积分>\n"
        "CS prediction rank <本群|全部|个人>\n"
        "CS login <手机号> <验证码>\n"
        "CS bind <5E|5e|5eplay> <玩家昵称>\n"
        "CS bind <wm|pw|完美> [Steam32位或64位ID]\n"
        "CS unbind <5E|5e|5eplay|wm|pw|完美>\n"
        "CS 战绩 <5E|5e|5eplay> [玩家昵称]\n"
        "CS 战绩 <wm|pw|完美> [Steam32位或64位ID]\n"
    ),
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={"help_category": "拓展功能", "help_order": 10},
)

from . import commands as commands  # noqa: E402,F401
from . import schema as schema  # noqa: E402,F401
from . import scheduler as scheduler  # noqa: E402,F401
