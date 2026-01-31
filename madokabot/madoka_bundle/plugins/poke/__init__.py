from nonebot import on_notice
from nonebot.adapters.onebot.v11 import PokeNotifyEvent
from ...constants import ResType, SubFolder
from ...utils import get_random_res
from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="戳一戳",
    description="戳一戳插件",
    usage="戳一戳机器人，可以返回一句円香语音",
    type="application",
)


poke = on_notice()

@poke.handle()
async def _(event: PokeNotifyEvent):
    if event.target_id != event.self_id: return
    await poke.finish(get_random_res(ResType.AUDIO, SubFolder.POKE))