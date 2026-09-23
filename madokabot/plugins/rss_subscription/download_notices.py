"""RSS 下载与上传任务的群消息通知。"""

from typing import Any, Dict, List, Optional, Sequence

from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from madokabot.core.group.access import is_group_whitelisted

from .config import config
from .utils import get_bot_group_list


def _whitelisted_group_ids(group_ids: Sequence[str]) -> List[str]:
    """筛选有效且位于白名单中的群号。"""
    return [
        str(group_id)
        for group_id in group_ids
        if str(group_id).isdigit() and is_group_whitelisted(group_id)
    ]


async def send_msg(
    bot: Bot, msg: str, notice_group: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """向任务指定的白名单群发送状态通知。"""
    logger.info(msg)
    msg_id: List[Dict[str, Any]] = []
    configured_group_ids = notice_group or config.down_status_msg_group
    down_status_msg_group = _whitelisted_group_ids(configured_group_ids)
    if not down_status_msg_group:
        return msg_id
    group_list = await get_bot_group_list(bot)
    for group_id in down_status_msg_group:
        if int(group_id) not in group_list:
            logger.error(f"Bot[{bot.self_id}]未加入群组[{group_id}]")
            continue
        msg_id.append(await bot.send_group_msg(group_id=int(group_id), message=msg))
    return msg_id


async def _safe_upload_notice(bot: Bot, message: str, group_id: str) -> None:
    """发送上传通知并记录发送异常。"""
    try:
        await send_msg(bot, message, [group_id])
    except Exception:
        logger.exception(f"发送群文件上传状态到群[{group_id}]时出错")
