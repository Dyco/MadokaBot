"""每日投胎插件入口。"""

from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
require("nonebot_plugin_datastore")
require("nonebot_plugin_htmlrender")

__plugin_meta__ = PluginMetadata(
    name="每日投胎 · Daily Reborn",
    description="按全球出生人口分布模拟一次新生，每天一次，生成世界地图与人生属性卡片",
    usage="reborn / 每日投胎 / 投胎：抽取或查看今天的投胎结果\n"
    "遵循全局命令起始符；上海时间每日零点重置，跨群共享次数。",
    type="application",
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={"help_category": "拓展功能", "help_order": 60},
)

from . import commands as commands  # noqa: E402,F401
