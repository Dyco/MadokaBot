import json
import time
from pathlib import Path

import nonebot_plugin_localstore as store
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Arparma, Match, MsgTarget, Target, UniMessage
from nonebot_plugin_waiter import waiter

from .config import config
from .matchers import WHITELIST_USAGE, group_whitelist_cmd
from .shop import _extract_message_id
from .utils import parse_page_command


class GroupWhitelist:
    def __init__(self, save_path: Path) -> None:
        self._save_path = save_path
        self.content: set[str] = set()

        if save_path.exists():
            try:
                data = json.loads(save_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = []
            if isinstance(data, list):
                self.content = {
                    str(group_id).strip()
                    for group_id in data
                    if str(group_id).strip().isdigit()
                }
        else:
            self.save()

    def save(self) -> None:
        self._save_path.parent.mkdir(parents=True, exist_ok=True)
        self._save_path.write_text(
            json.dumps(sorted(self.content), ensure_ascii=False, indent=4),
            encoding="utf-8",
        )

    def add(self, group_id: str) -> bool:
        if group_id in self.content:
            return False
        self.content.add(group_id)
        self.save()
        return True

    def remove(self, group_id: str) -> bool:
        if group_id not in self.content:
            return False
        self.content.remove(group_id)
        self.save()
        return True

    def contains(self, group_id: str) -> bool:
        return str(group_id).strip() in self.content

    def get_page(self, page: int, page_size: int = 20) -> tuple[list[str], int]:
        groups = sorted(self.content)
        total_pages = max(1, (len(groups) + page_size - 1) // page_size)
        start = (page - 1) * page_size
        return groups[start : start + page_size], total_pages


group_whitelist = GroupWhitelist(
    store.get_data_file("madoka_bundle", "group_whitelist.json")
)


def is_group_whitelisted(group_id: str | int) -> bool:
    return group_whitelist.contains(str(group_id))


async def _get_group_id(target: Target, group_id: Match[str]) -> str:
    if group_id.available:
        group_id_value = group_id.result.strip()
        if not group_id_value.isdigit():
            await group_whitelist_cmd.finish("群号必须是数字")
        return group_id_value

    if target.private or target.channel:
        await group_whitelist_cmd.finish("请提供群号，或在群聊中使用该指令")
    return str(target.id)


@group_whitelist_cmd.handle()
async def _handle_group_whitelist_root(result: Arparma):
    if not result.subcommands:
        await group_whitelist_cmd.finish(WHITELIST_USAGE)


@group_whitelist_cmd.assign("add")
async def _add_group_whitelist(
    bot: Bot,
    event: Event,
    target: MsgTarget,
    group_id: Match[str],
):
    if not await SUPERUSER(bot, event):
        await group_whitelist_cmd.finish("只有超级用户可以修改群白名单")

    group_id_value = await _get_group_id(target, group_id)
    if group_whitelist.add(group_id_value):
        await group_whitelist_cmd.finish(f"已添加群白名单：{group_id_value}")
    await group_whitelist_cmd.finish(f"群 {group_id_value} 已在白名单中")


@group_whitelist_cmd.assign("delete")
async def _delete_group_whitelist(
    bot: Bot,
    event: Event,
    target: MsgTarget,
    group_id: Match[str],
):
    if not await SUPERUSER(bot, event):
        await group_whitelist_cmd.finish("只有超级用户可以修改群白名单")

    group_id_value = await _get_group_id(target, group_id)
    if group_whitelist.remove(group_id_value):
        await group_whitelist_cmd.finish(f"已删除群白名单：{group_id_value}")
    await group_whitelist_cmd.finish(f"群 {group_id_value} 不在白名单中")


@group_whitelist_cmd.assign("list")
async def _list_group_whitelist():
    current_page = 1

    def build_page(page: int) -> tuple[str | None, int]:
        groups, total_pages = group_whitelist.get_page(page)
        if not groups:
            return None, total_pages
        return (
            f"群白名单（第 {page}/{total_pages} 页，共 {len(group_whitelist.content)} 个）：\n"
            + "\n".join(groups)
            + "\n\n回复上一页/下一页 或 数字 进行翻页",
            total_pages,
        )

    message, total_pages = build_page(current_page)
    if message is None:
        await group_whitelist_cmd.finish("当前没有已添加的群白名单")

    send_result = await group_whitelist_cmd.send(message, reply_message=True)
    reply_message_id = _extract_message_id(send_result)
    if reply_message_id is None:
        return

    @waiter(waits=["message"], keep_session=True, block=True)
    async def wait_group_whitelist_page(reply_event: MessageEvent):
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
        result = await wait_group_whitelist_page.wait(timeout=remaining)
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
