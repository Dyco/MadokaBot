import time

from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import fullmatch

__plugin_meta__ = PluginMetadata(
    name="状态测试",
    description="简单的存活测试插件",
    usage="发送ping或円香，查看机器人响应及消息延迟",
    type="application",
    extra={"help_category": "响应内容", "help_order": 30},
)


ping_reply: str = "我在"
ping_keywords: list[str] = ["ping", "円香"]

ping_matcher = on_message(
    rule=fullmatch(ping_keywords),
    priority=10,
    block=True,
)


@ping_matcher.handle()
async def _handle_ping(event: MessageEvent):
    """存活测试方法。"""
    ms = max(0.0, (time.time() - event.time) * 1000)
    await ping_matcher.finish(f"{ping_reply} ({ms:.0f}ms)")
