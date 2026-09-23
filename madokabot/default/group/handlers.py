# -*- coding: utf-8 -*-
"""群组白名单和黑名单的管理指令。"""

from __future__ import annotations

import time

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Arparma, Match, MsgTarget, Target, UniMessage
from nonebot_plugin_waiter import waiter

from .config import config
from madokabot.core.group.access import group_access
from .matchers import (
    BLACKLIST_USAGE,
    WHITELIST_USAGE,
    group_blacklist_cmd,
    group_whitelist_cmd,
)
from madokabot.core.messaging.pagination import extract_message_id
from madokabot.core.messaging.pagination import parse_page_command


async def _get_group_id(target: Target, group_id: Match[str], command) -> str:
    """解析群号参数，没有参数时使用当前群号。"""

    if group_id.available:
        group_id_value = group_id.result.strip()
        if not group_id_value.isdigit():
            await command.finish("群号必须是数字")
        return group_id_value

    if target.private or target.channel:
        await command.finish("请提供群号，或在群聊中使用该指令")
    return str(target.id)


async def _list_group_groups(command, access_type: int, list_name: str):
    """分页显示指定类型的群组名单。"""

    current_page = 1

    def build_page(page: int) -> tuple[str | None, int]:
        """构建当前群访问名单的指定分页。"""
        all_groups = group_access.get(access_type)
        page_size = 20
        total_pages = max(1, (len(all_groups) + page_size - 1) // page_size)
        start = (page - 1) * page_size
        groups = all_groups[start : start + page_size]
        if not groups:
            return None, total_pages
        return (
            f"{list_name}（第 {page}/{total_pages} 页，共 "
            f"{len(all_groups)} 个）：\n"
            + "\n".join(groups)
            + "\n\n回复上一页/下一页 或 数字 进行翻页",
            total_pages,
        )

    message, total_pages = build_page(current_page)
    if message is None:
        await command.finish(f"当前没有已添加的{list_name}")

    send_result = await command.send(message, reply_message=True)
    reply_message_id = extract_message_id(send_result)
    if reply_message_id is None:
        return

    @waiter(waits=["message"], keep_session=True, block=True)
    async def wait_group_page(reply_event: MessageEvent):
        """筛选当前群组名单分页会话的回复。"""

        if not reply_event.reply:
            return None
        try:
            replied_message_id = int(reply_event.reply.message_id)
        except (TypeError, ValueError):
            return None
        if replied_message_id != reply_message_id:
            return None

        target_page, invalid_page = parse_page_command(
            reply_event.get_plaintext(),
            current_page,
            total_pages,
        )
        if target_page is None and not invalid_page:
            return None
        return reply_event, target_page, invalid_page

    deadline = time.monotonic() + config.group_session_timeout
    while (remaining := deadline - time.monotonic()) > 0:
        result = await wait_group_page.wait(timeout=remaining)
        if result is None:
            return

        reply_event, target_page, invalid_page = result
        if invalid_page:
            await UniMessage(f"页码无效，当前共 {total_pages} 页").send(
                target=reply_event,
                reply_to=True,
            )
            continue

        if target_page is None:
            continue
        current_page = target_page
        message, total_pages = build_page(current_page)
        if message is None:
            return
        send_result = await UniMessage(message).send(
            target=reply_event,
            reply_to=True,
        )
        next_message_id = extract_message_id(send_result)
        if next_message_id is None:
            return
        reply_message_id = next_message_id


@group_whitelist_cmd.handle()
async def _handle_group_whitelist_root(result: Arparma):
    """处理白名单指令的帮助信息。"""

    if not result.subcommands:
        await group_whitelist_cmd.finish(WHITELIST_USAGE)


@group_whitelist_cmd.assign("add")
async def _add_group_whitelist(
    bot: Bot,
    event: Event,
    target: MsgTarget,
    group_id: Match[str],
):
    """将群组加入白名单。"""

    if not await SUPERUSER(bot, event):
        await group_whitelist_cmd.finish("只有超级用户可以修改群白名单")

    group_id_value = await _get_group_id(target, group_id, group_whitelist_cmd)
    if group_access.add(group_id_value, 1):
        await group_whitelist_cmd.finish(f"已添加群白名单：{group_id_value}")
    await group_whitelist_cmd.finish(f"群 {group_id_value} 已在白名单中")


@group_whitelist_cmd.assign("delete")
async def _delete_group_whitelist(
    bot: Bot,
    event: Event,
    target: MsgTarget,
    group_id: Match[str],
):
    """从白名单移除群组。"""

    if not await SUPERUSER(bot, event):
        await group_whitelist_cmd.finish("只有超级用户可以修改群白名单")

    group_id_value = await _get_group_id(target, group_id, group_whitelist_cmd)
    if not group_access.contains(group_id_value, 1):
        await group_whitelist_cmd.finish(f"群 {group_id_value} 不在白名单中")
    group_access.remove(group_id_value)
    await group_whitelist_cmd.finish(f"已删除群白名单：{group_id_value}")


@group_whitelist_cmd.assign("list")
async def _list_group_whitelist():
    """显示白名单。"""

    await _list_group_groups(group_whitelist_cmd, 1, "群白名单")


@group_blacklist_cmd.handle()
async def _handle_group_blacklist_root(result: Arparma):
    """处理黑名单指令的帮助信息。"""

    if not result.subcommands:
        await group_blacklist_cmd.finish(BLACKLIST_USAGE)


@group_blacklist_cmd.assign("add")
async def _add_group_blacklist(
    bot: Bot,
    event: Event,
    target: MsgTarget,
    group_id: Match[str],
):
    """将群组加入黑名单。"""

    if not await SUPERUSER(bot, event):
        await group_blacklist_cmd.finish("只有超级用户可以修改群黑名单")

    group_id_value = await _get_group_id(target, group_id, group_blacklist_cmd)
    if group_access.add(group_id_value, 2):
        await group_blacklist_cmd.finish(f"已添加群黑名单：{group_id_value}")
    await group_blacklist_cmd.finish(f"群 {group_id_value} 已在黑名单中")


@group_blacklist_cmd.assign("delete")
async def _delete_group_blacklist(
    bot: Bot,
    event: Event,
    target: MsgTarget,
    group_id: Match[str],
):
    """从黑名单移除群组。"""

    if not await SUPERUSER(bot, event):
        await group_blacklist_cmd.finish("只有超级用户可以修改群黑名单")

    group_id_value = await _get_group_id(target, group_id, group_blacklist_cmd)
    if not group_access.contains(group_id_value, 2):
        await group_blacklist_cmd.finish(f"群 {group_id_value} 不在黑名单中")
    group_access.remove(group_id_value)
    await group_blacklist_cmd.finish(f"已删除群黑名单：{group_id_value}")


@group_blacklist_cmd.assign("list")
async def _list_group_blacklist():
    """显示黑名单。"""

    await _list_group_groups(group_blacklist_cmd, 2, "群黑名单")
