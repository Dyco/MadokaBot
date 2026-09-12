from nonebot import on_notice
from nonebot.adapters.onebot.v11 import PokeNotifyEvent
from nonebot.plugin import PluginMetadata

from ...constants import ResType, SubFolder
from ...utils import get_random_res

__plugin_meta__ = PluginMetadata(
    name="戳一戳",
    description="戳一戳插件",
    usage="戳一戳机器人，可以返回一句円香语音",
    type="application",
)


poke_matcher = on_notice()


@poke_matcher.handle()
async def _handle_poke(event: PokeNotifyEvent):
    if event.target_id != event.self_id:
        return
    await poke_matcher.finish(get_random_res(ResType.AUDIO, SubFolder.POKE))
