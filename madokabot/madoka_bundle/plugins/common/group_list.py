# -*- coding: utf-8 -*-
"""群组白名单和黑名单的 JSON 存储及管理指令。"""

from __future__ import annotations

import time
from enum import IntEnum
from pathlib import Path
from typing import Any

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Arparma, Match, MsgTarget, Target, UniMessage
from nonebot_plugin_waiter import waiter

from ...config import assets
from ...constants import ResType, SubFolder
from .config import config
from .json_data import JsonDataStore
from .matchers import (
    BLACKLIST_USAGE,
    WHITELIST_USAGE,
    group_blacklist_cmd,
    group_whitelist_cmd,
)
from .shop import _extract_message_id
from .utils import parse_page_command

GROUP_ACCESS_PATH = assets.get_dir(ResType.JSON, SubFolder.GROUP) / "group_access.json"
# 白名单和黑名单唯一使用的 JSON 文件路径。

_ACCESS_LIST_NAMES = ("whitelist", "blacklist")


class GroupAccessType(IntEnum):
    """群组访问类型，1 代表白名单，2 代表黑名单。"""

    WHITELIST = 1  # 1：白名单
    BLACKLIST = 2  # 2：黑名单


class GroupAccessStore:
    """管理群组白名单和黑名单。"""

    def __init__(self, save_path: Path = GROUP_ACCESS_PATH) -> None:
        """初始化群组访问名单存储。"""
        self.data_store = JsonDataStore(
            save_path,
            {list_name: [] for list_name in _ACCESS_LIST_NAMES},
        )
        self.content = self._normalize_access(self.data_store.content)

    @staticmethod
    def _normalize_group_id(group_id: str | int) -> str:
        """统一群 ID 格式，并拒绝空值。"""
        value = str(group_id).strip()
        if not value:
            raise ValueError("群 ID 不能为空")
        return value

    @staticmethod
    def _normalize_access_type(access_type: int) -> int:
        """校验访问类型，1 代表白名单，2 代表黑名单。"""
        if isinstance(access_type, bool) or not isinstance(access_type, int):
            raise TypeError("访问类型必须是 1（白名单）或 2（黑名单）")
        if access_type not in {
            GroupAccessType.WHITELIST,
            GroupAccessType.BLACKLIST,
        }:
            raise ValueError("访问类型只能是 1（白名单）或 2（黑名单）")
        return access_type

    @staticmethod
    def _list_name(access_type: int) -> str:
        """将访问类型转换为 JSON 中对应的名单名称。"""
        return (
            "whitelist"
            if access_type == GroupAccessType.WHITELIST
            else "blacklist"
        )

    @staticmethod
    def _normalize_access(data: Any) -> dict[str, set[str]]:
        """清洗白名单和黑名单，只保留非空群 ID。"""
        if not isinstance(data, dict):
            data = {}
        return {
            list_name: {
                str(group_id).strip()
                for group_id in data.get(list_name, [])
                if str(group_id).strip()
            }
            if isinstance(data.get(list_name), list)
            else set()
            for list_name in _ACCESS_LIST_NAMES
        }

    def reload(self) -> None:
        """从磁盘重新读取访问名单。"""
        self.data_store.reload()
        self.content = self._normalize_access(self.data_store.content)

    def save(self) -> None:
        """保存访问名单到 group_access.json。"""
        self.data_store.write(
            {
                list_name: sorted(self.content[list_name])
                for list_name in _ACCESS_LIST_NAMES
            }
        )

    def get(self, access_type: int) -> list[str]:
        """获取指定类型的群组列表。"""
        normalized_access_type = self._normalize_access_type(access_type)
        return sorted(self.content[self._list_name(normalized_access_type)])

    def add(self, group_id: str | int, access_type: int) -> bool:
        """将群 ID 写入指定名单，并返回数据是否发生变化。"""
        normalized_group_id = self._normalize_group_id(group_id)
        normalized_access_type = self._normalize_access_type(access_type)
        target_name = self._list_name(normalized_access_type)
        other_name = self._list_name(
            GroupAccessType.BLACKLIST
            if normalized_access_type == GroupAccessType.WHITELIST
            else GroupAccessType.WHITELIST
        )

        changed = normalized_group_id not in self.content[target_name]
        self.content[target_name].add(normalized_group_id)
        if normalized_group_id in self.content[other_name]:
            self.content[other_name].remove(normalized_group_id)
            changed = True
        if not changed:
            return False

        self.save()
        return True

    def remove(self, group_id: str | int) -> bool:
        """从白名单和黑名单移除群 ID，并返回是否实际删除。"""
        normalized_group_id = self._normalize_group_id(group_id)
        changed = False
        for groups in self.content.values():
            if normalized_group_id in groups:
                groups.remove(normalized_group_id)
                changed = True
        if not changed:
            return False

        self.save()
        return True

    def contains(self, group_id: str | int, access_type: int) -> bool:
        """判断群 ID 是否在指定访问名单中。"""
        normalized_group_id = self._normalize_group_id(group_id)
        normalized_access_type = self._normalize_access_type(access_type)
        return normalized_group_id in self.content[
            self._list_name(normalized_access_type)
        ]

    def is_whitelisted(self, group_id: str | int) -> bool:
        """判断群组是否为白名单。"""
        return self.contains(group_id, GroupAccessType.WHITELIST)

    def is_blacklisted(self, group_id: str | int) -> bool:
        """判断群组是否为黑名单。"""
        return self.contains(group_id, GroupAccessType.BLACKLIST)

    def is_allowed(self, group_id: str | int) -> bool:
        """根据访问名单判断群组是否允许使用机器人功能。"""
        normalized_group_id = self._normalize_group_id(group_id)
        if normalized_group_id in self.content["blacklist"]:
            return False

        whitelist = self.content["whitelist"]
        return not whitelist or normalized_group_id in whitelist


group_list = GroupAccessStore()
# 群组访问名单存储实例，实际数据保存于 group_access.json。

group_access = group_list
# 保留 group_access 名称，兼容现有业务代码。


def is_group_whitelisted(group_id: str | int) -> bool:
    """判断群组是否在白名单中。"""

    return group_access.contains(group_id, 1)


def is_group_blacklisted(group_id: str | int) -> bool:
    """判断群组是否在黑名单中。"""

    return group_access.contains(group_id, 2)


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
    reply_message_id = _extract_message_id(send_result)
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

    deadline = time.monotonic() + config.shop_session_timeout
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
        next_message_id = _extract_message_id(send_result)
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


__all__ = [
    "GROUP_ACCESS_PATH",
    "GroupAccessStore",
    "GroupAccessType",
    "group_access",
    "group_list",
    "is_group_blacklisted",
    "is_group_whitelisted",
]
