"""签到插件元数据与处理器加载入口。"""

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="每日签到",
    description="每日签到获取积分，并展示签到卡片",
    usage="发送签到/打卡/sign即可签到；首次签到会自动注册账号",
    type="application",
    extra={"help_category": "基础功能", "help_order": 10},
)

from . import handlers as handlers  # noqa: E402,F401
