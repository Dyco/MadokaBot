"""每日投胎插件入口。"""

from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
require("nonebot_plugin_datastore")
require("nonebot_plugin_htmlrender")

from madokabot.core.config import command_start

__plugin_meta__ = PluginMetadata(
    name="每日投胎",
    description="模拟投胎，生成出生地与人生属性卡片",
    usage=f"{command_start}投胎：世界投胎，每日免费一次\n"
    f"{command_start}投胎中国：中国投胎，每日免费一次（含港澳台）\n"
    f"{command_start}投胎 重开：消耗 5 积分重新随机投胎\n",
    type="application",
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={"help_category": "拓展功能", "help_order": 60},
)

from . import commands as commands  # noqa: E402,F401
