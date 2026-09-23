import time

from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import fullmatch

__plugin_meta__ = PluginMetadata(
    name="状态测试",
    description="简单的存活测试插件",
    usage="发送关键词获取响应",
    type="application",
)


ping_reply: str = "我在"  # 回复内容
ping_keywords: list[str] = ["ping", "円香"]  # 触发关键词

ping_matcher = on_message(
    rule=fullmatch(ping_keywords),
    priority=10,
    block=True,
)


@ping_matcher.handle()
async def _handle_ping(event: MessageEvent):
    """回应存活测试，并显示消息到达后的延迟。"""
    ms = max(0.0, (time.time() - event.time) * 1000)
    await ping_matcher.finish(f"{ping_reply} ({ms:.0f}ms)")
