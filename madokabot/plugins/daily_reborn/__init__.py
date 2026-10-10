"""每日投胎插件入口。"""

from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
require("nonebot_plugin_datastore")
require("nonebot_plugin_htmlrender")

__plugin_meta__ = PluginMetadata(
    name="每日投胎",
    description="模拟一次投胎，生成世界地图与人生属性卡片",
    usage="/投胎：抽取或查看今天的投胎结果\n"
    "/投胎 重开：花费积分进行重开\n",
    type="application",
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={"help_category": "拓展功能", "help_order": 60},
)

from . import commands as commands  # noqa: E402,F401
