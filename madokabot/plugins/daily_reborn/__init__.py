"""每日投胎插件入口。"""

from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
require("nonebot_plugin_datastore")
require("nonebot_plugin_htmlrender")

from madokabot.core.config import command_start

__plugin_meta__ = PluginMetadata(
    name="每日投胎",
    description="模拟现实、异世界、二次元或二游投胎，生成出生档案与作品身份卡片",
    usage=f"{command_start}投胎：世界投胎，每日免费一次\n"
    f"{command_start}投胎中国：中国投胎，每日免费一次（含港澳台）\n"
    f"{command_start}投胎日本：日本投胎，每日免费一次（47 个都道府县）\n"
    f"{command_start}投胎美国：美国投胎，每日免费一次（50 州及华盛顿特区）\n"
    f"{command_start}投胎异世界：随机异世界出身，每日免费一次\n"
    f"{command_start}投胎异世界 重开：消耗 5 积分重新随机异世界出身\n"
    f"{command_start}投胎二次元 / {command_start}投胎动漫：按动漫题材模拟人生，每日免费一次\n"
    f"{command_start}投胎二次元 重开：消耗 5 积分重新随机作品身份\n"
    f"{command_start}投胎二游：随机游戏身份，每日免费一次，展示最近十次历史\n"
    f"{command_start}投胎二游 重开：消耗 5 积分重新随机游戏身份\n"
    f"{command_start}投胎 重开：消耗 5 积分重新随机投胎\n"
    f"{command_start}一键投胎：领取或复查全部模式的今日结果，重复查看不扣积分、不增加次数\n"
    "单独发送对应投胎命令，可将一键投胎的今日结果渲染成图片复查\n"
    f"{command_start}一键投胎 重开：消耗 35 积分重新随机全部七种投胎\n",
    type="application",
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={"help_category": "拓展功能", "help_order": 60},
)

from . import commands as commands
