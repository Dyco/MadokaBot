from nonebot import on_notice
from nonebot.adapters.onebot.v11 import PokeNotifyEvent
from nonebot.plugin import PluginMetadata

from madokabot.core.messaging.resources import get_random_resource_segment
from madokabot.core.resources import ResourceType, ResourceFolder

__plugin_meta__ = PluginMetadata(
    name="戳一戳",
    description="戳一戳机器人，可触发随机円香语音。",
    usage="",
    type="application",
    extra={"help_category": "响应内容", "help_order": 10},
)


poke_matcher = on_notice()


@poke_matcher.handle()
async def _handle_poke(event: PokeNotifyEvent):
    """戳一戳处理方法。"""
    if event.target_id != event.self_id:
        return
    await poke_matcher.finish(
        get_random_resource_segment(ResourceType.AUDIO, ResourceFolder.POKE)
    )
