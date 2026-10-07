"""向管理员发送跨插件通知。"""

from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot

def _get_superuser_ids(bot: Bot) -> list[int]:
    """管理员账号读取方法。"""
    configured_ids: Any = getattr(bot.config, "superusers", ())
    if isinstance(configured_ids, (str, int)):
        configured_ids = (configured_ids,)

    superuser_ids: list[int] = []
    for user_id in configured_ids:
        try:
            value = int(str(user_id).strip())
        except (TypeError, ValueError):
            continue
        if value not in superuser_ids:
            superuser_ids.append(value)
    return superuser_ids


async def send_message_to_admin(message: str, bot: Bot) -> None:
    """管理员通知方法。"""
    superuser_ids = _get_superuser_ids(bot)
    if not superuser_ids:
        logger.warning("未配置 SUPERUSERS，无法发送管理员私聊消息")
        return

    try:
        await bot.send_private_msg(
            user_id=superuser_ids[0],
            message=message,
        )
    except Exception:
        logger.exception(f"管理员私聊消息发送失败，消息内容：{message}")


