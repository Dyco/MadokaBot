"""按群访问名单自动接受机器人入群邀请。"""

from nonebot import logger, on_request
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupRequestEvent,
    OneBotV11AdapterException,
)

from .access import is_group_blacklisted, is_group_whitelisted

group_invite_request = on_request(block=False)


@group_invite_request.handle()
async def _handle_group_invite(bot: Bot, event: GroupRequestEvent) -> None:
    """自动同意白名单群的邀请，黑名单优先，其他请求保持待处理。"""
    if event.sub_type != "invite":
        return

    context = f"机器人 {bot.self_id}，群 {event.group_id}，邀请人 {event.user_id}"
    if is_group_blacklisted(event.group_id) or not is_group_whitelisted(event.group_id):
        logger.info(f"群邀请未通过名单检查，保留人工处理：{context}")
        return

    try:
        await event.approve(bot)
    except OneBotV11AdapterException as exc:
        logger.warning(f"自动同意群邀请失败，不自动重试：{context}，{exc!r}")
        return

    logger.info(f"已提交同意群邀请请求：{context}")
