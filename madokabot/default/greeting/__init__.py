from madokabot.core.messaging.notifications import send_message_to_admin

from nonebot import on_metaevent
from nonebot.adapters.onebot.v11 import Bot, LifecycleMetaEvent
from nonebot.plugin import PluginMetadata

from .config import GreetingConfig, config


__plugin_meta__ = PluginMetadata(
    name="打招呼",
    description="机器人连接成功后向管理员发送问候消息",
    usage="机器人启动后自动向管理员发送问候消息",
    type="application",
    config=GreetingConfig,
    supported_adapters={"~onebot.v11"},
)


def _is_first_connect(_: LifecycleMetaEvent) -> bool:
    return True


greeting_metaevent = on_metaevent(rule=_is_first_connect, temp=True)


@greeting_metaevent.handle()
async def _handle_greeting(bot: Bot) -> None:
    await send_message_to_admin(config.greeting_message, bot)
