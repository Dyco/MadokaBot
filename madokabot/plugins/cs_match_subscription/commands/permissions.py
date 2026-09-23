"""CS 群订阅命令的权限检查。"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import (
    GROUP_ADMIN,
    GROUP_OWNER,
    Bot,
    GroupMessageEvent,
    MessageEvent,
)
from nonebot.permission import SUPERUSER

from ..matchers import cs_cmd


async def group_subscription_target(
    bot: Bot,
    event: MessageEvent,
) -> dict[str, str] | None:
    """校验群管理权限并返回当前群的推送目标。"""
    if not isinstance(event, GroupMessageEvent):
        await cs_cmd.finish("此命令仅支持群聊。")
        return None
    if not (
        await SUPERUSER(bot, event)
        or await GROUP_ADMIN(bot, event)
        or await GROUP_OWNER(bot, event)
    ):
        await cs_cmd.finish("权限不足，只有超级用户、群管理员或群主可以使用此命令。")
        return None
    return {"kind": "group", "id": str(event.group_id)}
