"""RSS 下载进度、文件选择提示与消息撤回。"""

import asyncio
from typing import Any, Dict, List, Optional

from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from .config import config
from .download_details import _compact_file_size, _display_file_path
from .download_notices import send_msg
from .download_validation import _int_value, _status_files
from .utils import convert_size

progress_recall_tasks: set[asyncio.Task[None]] = set()


async def send_download_progress(
    bot: Bot,
    gid: str,
    info: Dict[str, Any],
    name: str,
    group_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """向目标群发送下载进度。"""
    total = _int_value(info.get("totalLength"))
    completed = _int_value(info.get("completedLength"))
    speed = _int_value(info.get("downloadSpeed"))
    percent = round(completed / total * 100, 2) if total else 0
    return await send_msg(
        bot,
        f"{name}\nGID：{gid}\n下载进度：{percent}%\n当前速度：{convert_size(speed)}/s",
        group_ids,
    )


async def send_file_selection(
    bot: Bot,
    gid: str,
    status: Dict[str, Any],
    group_ids: List[str],
    name: str,
) -> List[Dict[str, Any]]:
    """分段发送多文件任务的可选文件列表。"""
    files = _status_files(status)
    lines = [
        f"{file_info.get('index', '?')}."
        f"{_display_file_path(status, file_info)}"
        f"[{_compact_file_size(file_info)}]"
        for file_info in files
    ]
    header = f"{name}\n检测到 {len(files)} 个文件，任务已暂停。\nGID：{gid}\n文件列表："
    chunk_size = 25
    for offset in range(0, len(lines), chunk_size):
        body = "\n".join(lines[offset : offset + chunk_size])
        prefix = header if offset == 0 else f"{name}\nGID：{gid}\n文件列表（续）："
        await send_msg(bot, f"{prefix}\n{body}", group_ids)
    return await send_msg(
        bot,
        "请引用回复本条消息，输入要下载的文件编号。\n"
        "支持 1,2,3 或 1,3-5 这样的写法。\n"
        f"也可以使用 /RSS 选择文件 {gid} <编号>。",
        group_ids,
    )


async def delete_messages(bot: Bot, msg_ids: List[Dict[str, Any]]) -> None:
    """撤回先前发送的下载进度消息。"""
    for msg_id in msg_ids:
        try:
            await bot.delete_msg(message_id=msg_id["message_id"])
        except Exception as exc:
            logger.debug(f"撤回下载进度消息失败：{exc}")


async def _recall_progress_messages(
    bot: Bot, msg_ids: List[Dict[str, Any]], delay: int
) -> None:
    """延迟撤回下载进度消息。"""
    await asyncio.sleep(delay)
    await delete_messages(bot, msg_ids)


def schedule_progress_recall(bot: Bot, msg_ids: List[Dict[str, Any]]) -> None:
    """按配置安排下载进度消息的撤回。"""
    delay = int(config.down_status_msg_recall_delay)
    if delay <= 0 or not msg_ids:
        return
    task = asyncio.create_task(_recall_progress_messages(bot, msg_ids, delay))
    progress_recall_tasks.add(task)
    task.add_done_callback(progress_recall_tasks.discard)
