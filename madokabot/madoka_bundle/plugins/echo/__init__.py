from nonebot import on_message
from nonebot.rule import fullmatch
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata

from .config import EchoConfig, config
from ...utils import get_latency_ms 

__plugin_meta__ = PluginMetadata(
    name="状态测试",
    description="简单的存活测试插件",
    usage="发送关键词获取响应",
    type="application",
    config=EchoConfig,
)

# 关键词匹配响应
echo = on_message( rule=fullmatch(config.echo_keywords) , priority=10 , block=True )

@echo.handle()
async def _(event: MessageEvent):
    ms = get_latency_ms(event)
    await echo.finish(f"{config.echo_reply} ({ms:.0f}ms)")