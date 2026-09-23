"""账号注册指令。"""

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_datastore import create_session

from .matchers import register_cmd
from .service import register_user


@register_cmd.handle()
async def _register(event: MessageEvent):
    """处理账号注册指令。"""
    nickname = event.sender.nickname or event.sender.card or ""
    async with create_session() as session:
        _, _, created = await register_user(
            session,
            event.get_user_id(),
            nickname,
        )

    if created:
        await register_cmd.finish("事务所信息注册成功。")
    await register_cmd.finish("制作人，你已经注册过了事务所信息了。")
