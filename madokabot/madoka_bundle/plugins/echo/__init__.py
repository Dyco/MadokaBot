from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import fullmatch

from ...utils import get_latency_ms
from .config import EchoConfig, config

__plugin_meta__ = PluginMetadata(
    name="状态测试",
    description="简单的存活测试插件",
    usage="发送关键词获取响应",
    type="application",
    config=EchoConfig,
)

echo_matcher = on_message(
    rule=fullmatch(config.echo_keywords),
    priority=10,
    block=True,
)


@echo_matcher.handle()
async def _handle_echo(event: MessageEvent):
    ms = get_latency_ms(event)
    await echo_matcher.finish(f"{config.echo_reply} ({ms:.0f}ms)")
