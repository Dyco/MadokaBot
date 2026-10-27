"""向管理员发送跨插件通知。"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, OneBotV11AdapterException


def _get_superuser_ids(bot: Bot) -> list[int]:
    """读取并去重 QQ 超级用户账号，支持 onebot 前缀。"""
    superuser_ids: set[int] = set()
    for user_id in bot.config.superusers:
        try:
            value = int(user_id.strip().removeprefix("onebot:"))
        except ValueError:
            continue
        superuser_ids.add(value)
    return sorted(superuser_ids)


async def send_message_to_admin(message: str, bot: Bot) -> None:
    """逐个通知所有 QQ 超级用户，单个发送失败不影响其他账号。"""
    superuser_ids = _get_superuser_ids(bot)
    if not superuser_ids:
        logger.warning("SUPERUSERS 中未配置有效的 QQ 账号，无法发送管理员私聊消息")
        return

    for user_id in superuser_ids:
        try:
            await bot.send_private_msg(user_id=user_id, message=message)
        except OneBotV11AdapterException:
            logger.exception(
                f"管理员私聊消息发送失败，QQ：{user_id}，消息内容：{message}"
            )
