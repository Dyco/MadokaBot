from nonebot import require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
require("nonebot_plugin_htmlrender")
require("nonebot_plugin_localstore")

__plugin_meta__ = PluginMetadata(
    name="picture_maker",
    description="接收图片并按音乐模板生成图片",
    usage="/制图 音乐 <图片> [模板] [标题] [子标题]",
    type="application",
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
)

# 导入指令模块，完成 NoneBot matcher 注册。
from . import matchers as _matchers  # noqa: E402,F401
