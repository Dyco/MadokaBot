"""编排 RSS 下载任务、状态轮询及群文件上传。"""

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

import arrow
from apscheduler.triggers.interval import IntervalTrigger
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from madokabot.core.files.cleanup import register_cleanup_path
from madokabot.core.messaging.notifications import send_message_to_admin

from .aria2_client import (
    Aria2Error,
    DownloadAcquireTimeout,
    _rpc_call,
    add_download,
    aria2_version,
    get_status,
)
from .config import config
from .download_cleanup import _remove_download, cancel_download
from .download_details import (
    _task_name,
    _task_summary,
)
from .download_notices import _whitelisted_group_ids, send_msg
from .download_progress import (
    delete_messages,
    schedule_progress_recall,
    send_download_progress,
    send_file_selection,
)
from .download_state import (
    DownloadStatus,
    _clear_download_tracking,
    _stop_status_check,
    download_tasks,
)
from .download_validation import (
    DownloadSizeLimitExceeded,
    _int_value,
    _size_limit_message,
    _status_files,
    parse_file_selection,
)
from .subscription import Rss
from .torrent_sources import (
    _attach_torrent_to_status,
    _delete_torrent_source,
    _save_torrent_source,
    is_torrent_link,
)
from .uploads.service import upload_files_to_groups
from .utils import (
    get_bot,
)

if config.aria2_download_path:
    register_cleanup_path("rss-downloads", config.aria2_download_path)


# 下载进度消息的撤回任务保存在进程内。

SelectionHandler = Callable[
    [Bot, str, List[Dict[str, Any]], List[str], str], Awaitable[None]
]


async def _reject_content_and_queue_torrent(
    gid: str,
    status: Dict[str, Any],
    task_info: Dict[str, Any],
    group_ids: Sequence[str],
    name: str,
) -> int:
    """停止超限内容，但保留种子并送入原有上传队列。"""
    torrent_file = _attach_torrent_to_status(task_info, status)
    await _remove_download(gid, str(status.get("status", "")))
    _clear_download_tracking(gid)

    valid_group_ids = _whitelisted_group_ids(group_ids)
    if torrent_file is None:
        logger.warning(f"超限任务[{gid}]没有找到可上传的 torrent 文件")
        return 0
    if not valid_group_ids:
        logger.warning(f"超限任务[{gid}]没有可上传种子的白名单群组")
        return 0

    status["status"] = "removed"
    task_info.update(
        {
            "status": DownloadStatus.UPLOAD_QUEUED,
            "name": name,
            "group_ids": valid_group_ids,
            "download_status": status,
            "torrent_upload_queued": True,
        }
    )
    download_tasks[gid] = task_info
    return await upload_files_to_groups(
        valid_group_ids,
        [torrent_file],
        name,
        gid,
    )


def _torrent_queue_result(queued_count: int) -> str:
    if queued_count:
        return f"内容文件不会下载，种子文件已加入上传队列（{queued_count} 个任务）。"
    return "内容文件不会下载，但没有找到可上传的种子文件或目标群。"


# 发送下载通知


async def _abandon_metadata_after_timeout(
    bot: Bot,
    gid: str,
    group_ids: List[str],
    name: str,
    timeout_seconds: float,
) -> None:
    await asyncio.sleep(max(timeout_seconds, 0))
    task_info = download_tasks.get(gid)
    if task_info is None or task_info.get("status") != DownloadStatus.METADATA:
        return

    _clear_download_tracking(gid)
    try:
        await send_msg(
            bot,
            f"❌ {name}\nGID：{gid}\n"
            f"获取磁力元数据超过 {config.aria2_acquire_timeout} 秒，已放弃任务。",
            group_ids,
        )
    finally:
        try:
            await cancel_download(gid)
        except Aria2Error:
            await _remove_download(gid)


def _track_download(
    bot: Bot,
    gid: str,
    group_ids: List[str],
    name: str,
    task_info: Dict[str, Any],
) -> None:
    task_info["status"] = DownloadStatus.DOWNLOADING
    task_info["group_ids"] = group_ids
    task_info["name"] = name
    download_tasks[gid] = task_info
    schedule_status_check(bot, gid, group_ids, name)


async def _prepare_manual_download(
    bot: Bot,
    gid: str,
    info: Dict[str, Any],
    group_ids: List[str],
    name: str,
    task_info: Dict[str, Any],
) -> bool:
    """暂停多文件任务等待选择；单文件任务直接开始。"""
    files = _status_files(info)
    if len(files) > 1:
        task_info["status"] = DownloadStatus.WAITING_SELECTION
        task_info["group_ids"] = group_ids
        task_info["name"] = name
        download_tasks[gid] = task_info
        prompt_messages = await send_file_selection(bot, gid, info, group_ids, name)
        selection_handler = task_info.get("selection_handler")
        if callable(selection_handler):
            await selection_handler(bot, gid, prompt_messages, group_ids, name)
        return False

    if size_limit_message := _size_limit_message(info):
        queued_count = await _reject_content_and_queue_torrent(
            gid, info, task_info, group_ids, name
        )
        raise DownloadSizeLimitExceeded(
            f"{size_limit_message}\n{_torrent_queue_result(queued_count)}"
        )

    if str(info.get("status", "")) == "paused":
        await _rpc_call("aria2.unpause", [gid])
    task_name = _task_name(info, name)
    task_summary = _task_summary(gid, info, task_name)
    _track_download(bot, gid, group_ids, task_name, task_info)
    await send_msg(bot, f"👏 {name}\n{task_summary}\n下载任务添加成功！", group_ids)
    return True


async def select_download_files(
    bot: Bot,
    gid: str,
    selection: str,
    group_ids: List[str],
    name: str = "手动上传",
) -> Dict[str, Any]:
    """为暂停的多文件任务设置文件编号并开始下载。"""
    info = await get_status(gid)
    if str(info.get("status", "")) != "paused":
        raise Aria2Error("该任务未处于等待选择状态，无法修改下载文件")

    files = _status_files(info)
    indices = [
        _int_value(file_info.get("index"))
        for file_info in files
        if _int_value(file_info.get("index")) > 0
    ]
    selected_indices = parse_file_selection(selection, indices)
    selected_value = ",".join(map(str, selected_indices))
    await _rpc_call("aria2.changeOption", [gid, {"select-file": selected_value}])

    updated_info = await get_status(gid)
    task_info = download_tasks.get(gid) or {
        "start_time": arrow.now(),
        "downing_tips_msg_id": [],
        "manual_selection": True,
    }
    if size_limit_message := _size_limit_message(updated_info):
        queued_count = await _reject_content_and_queue_torrent(
            gid, updated_info, task_info, group_ids, name
        )
        raise DownloadSizeLimitExceeded(
            f"{size_limit_message}\n{_torrent_queue_result(queued_count)}"
        )
    task_name = _task_name(updated_info, name)
    task_summary = _task_summary(gid, updated_info, task_name)
    await _rpc_call("aria2.unpause", [gid])
    _track_download(bot, gid, group_ids, task_name, task_info)
    return {
        "gid": gid,
        "name": task_name,
        "summary": task_summary,
        "selected_count": len(selected_indices),
    }


async def _follow_metadata_download(
    bot: Bot,
    metadata_gid: str,
    child_gid: str,
    task_info: Dict[str, Any],
) -> None:
    """把磁力元数据任务切换到 aria2 随后创建的 BT 下载任务。"""
    group_ids = list(task_info.get("group_ids") or [])
    name = str(task_info.get("name") or "下载任务")
    child_info = await get_status(child_gid)

    download_tasks[child_gid] = task_info
    _attach_torrent_to_status(task_info, child_info)

    if task_info.get("manual_selection"):
        try:
            await _prepare_manual_download(
                bot, child_gid, child_info, group_ids, name, task_info
            )
        except DownloadSizeLimitExceeded:
            _clear_download_tracking(metadata_gid)
            await _remove_download(metadata_gid, "complete")
            raise
        _clear_download_tracking(metadata_gid)
        await _remove_download(metadata_gid, "complete")
        return

    if size_limit_message := _size_limit_message(child_info):
        queued_count = await _reject_content_and_queue_torrent(
            child_gid,
            child_info,
            task_info,
            group_ids,
            name,
        )
        _clear_download_tracking(metadata_gid)
        await _remove_download(metadata_gid, "complete")
        await send_msg(
            bot,
            f"{name}\nGID：{child_gid}\n❌ 已停止内容下载：\n"
            f"{size_limit_message}\n{_torrent_queue_result(queued_count)}",
            group_ids,
        )
        return

    if str(child_info.get("status", "")) == "paused":
        await _rpc_call("aria2.unpause", [child_gid])
    task_name = _task_name(child_info, name)
    task_summary = _task_summary(child_gid, child_info, task_name)
    _track_download(bot, child_gid, group_ids, task_name, task_info)
    _clear_download_tracking(metadata_gid)
    await _remove_download(metadata_gid, "complete")
    await send_msg(
        bot,
        f"👏 {name}\n磁力元数据获取完成。\n{task_summary}",
        group_ids,
    )


async def check_download_status(
    bot: Bot, gid: str, group_ids: List[str], name: str
) -> None:
    task_info = download_tasks.get(gid)
    if task_info is None:
        _clear_download_tracking(gid)
        return

    try:
        info = await get_status(gid)
    except Aria2Error as exc:
        logger.warning(f"获取 aria2 任务[{gid}]状态失败：{exc}")
        return

    status = str(info.get("status", ""))
    followed_by = info.get("followedBy")
    if (
        task_info.get("status") == DownloadStatus.METADATA
        and isinstance(followed_by, list)
        and followed_by
    ):
        try:
            await _follow_metadata_download(bot, gid, str(followed_by[0]), task_info)
        except DownloadSizeLimitExceeded as exc:
            child_gid = str(followed_by[0])
            await send_msg(
                bot,
                f"{name}\nGID：{child_gid}\n❌ 已拒绝下载：\n{exc}",
                group_ids,
            )
        except Aria2Error as exc:
            logger.warning(f"接管磁力下载任务[{gid}]失败：{exc}")
        return

    # 磁力元数据完成后，aria2 可能稍晚才写入 followedBy。
    if task_info.get("status") == DownloadStatus.METADATA and status not in {
        "error",
        "removed",
    }:
        return

    if size_limit_message := _size_limit_message(info):
        queued_count = await _reject_content_and_queue_torrent(
            gid, info, task_info, group_ids, name
        )
        msg = (
            f"{name}\nGID：{gid}\n❌ 已停止内容下载：\n"
            f"{size_limit_message}\n{_torrent_queue_result(queued_count)}"
        )
        await send_msg(bot, msg, group_ids)
        return

    if status in {"error", "removed"}:
        error_code = info.get("errorCode", "?")
        error_message = info.get("errorMessage", "未知错误")
        msg = f"{name}\nGID：{gid}\naria2 下载失败[{error_code}]：{error_message}"
        await send_msg(bot, msg, group_ids)
        _clear_download_tracking(gid)
        return

    is_seeding = status == "active" and str(info.get("seeder", "")).lower() == "true"
    if status == "complete" or is_seeding:
        if is_seeding:
            await _remove_download(gid, status)
        await delete_messages(bot, task_info["downing_tips_msg_id"])
        files = [
            file_info
            for file_info in _status_files(info, selected_only=True)
            if file_info.get("path")
        ]
        torrent_file = _attach_torrent_to_status(task_info, info)
        if torrent_file:
            files.insert(0, torrent_file)
        start_time = task_info.get("start_time", arrow.now())
        all_time = arrow.now() - start_time
        task_info["status"] = DownloadStatus.UPLOAD_QUEUED
        task_info["name"] = name
        task_info["download_status"] = info
        await send_msg(
            bot,
            f"👏 {name}\nGID：{gid}\n下载完成！耗时：{str(all_time).split('.', 2)[0]}",
            group_ids,
        )
        valid_group_ids = _whitelisted_group_ids(group_ids)
        if valid_group_ids and files:
            queued_count = await upload_files_to_groups(
                valid_group_ids, files, name, gid
            )
            _stop_status_check(gid)
            await send_msg(
                bot,
                f"{name}\nGID：{gid}\n已加入群文件上传队列："
                f"{queued_count} 个任务，并发数 {config.rss_upload_concurrency}。",
                valid_group_ids,
            )
            return

        _clear_download_tracking(gid)
        return

    await delete_messages(bot, task_info["downing_tips_msg_id"])
    if status in {"active", "waiting", "paused"}:
        progress_messages = await send_download_progress(
            bot, gid, info, name, group_ids
        )
        task_info["downing_tips_msg_id"] = progress_messages
        schedule_progress_recall(bot, progress_messages)


def schedule_status_check(bot: Bot, gid: str, group_ids: List[str], name: str) -> None:
    trigger = IntervalTrigger(
        seconds=max(int(config.down_status_msg_date), 1), jitter=10
    )
    scheduler.add_job(
        func=check_download_status,
        trigger=trigger,
        args=(bot, gid, group_ids, name),
        id=gid,
        misfire_grace_time=60,
        max_instances=1,
        executor="default",
        replace_existing=True,
    )


async def start_download(
    bot: Bot,
    url: str,
    group_ids: List[str],
    name: str,
    proxy: Optional[str],
    manual_selection: bool = False,
    selection_handler: Optional[SelectionHandler] = None,
) -> Optional[Dict[str, str]]:
    """提交 aria2 下载任务并安排完成检查。"""
    is_magnet = url.lower().startswith("magnet:?")
    acquire_started = asyncio.get_running_loop().time()
    gid: Optional[str] = None
    torrent_content: Optional[bytes] = None
    try:
        async with asyncio.timeout(config.aria2_acquire_timeout):
            await aria2_version()
            gid, torrent_content = await add_download(
                url=url,
                proxy=proxy,
            )
            info = await get_status(gid)
    except (Aria2Error, TimeoutError) as exc:
        if isinstance(exc, TimeoutError):
            exc = DownloadAcquireTimeout(
                f"获取下载信息超过 {config.aria2_acquire_timeout} 秒"
            )
        if isinstance(exc, DownloadAcquireTimeout):
            msg = f"❌ {exc}，已放弃任务。"
        else:
            msg = (
                "❌ 无法使用 aria2 下载：\n"
                f"{exc}\n"
                "请检查 aria2c 是否运行、RPC 地址及密钥是否正确。"
            )
        logger.error(msg)
        await send_message_to_admin(msg, bot)
        await send_msg(bot, msg, group_ids)
        if gid:
            await _remove_download(gid)
        return None

    task_name = _task_name(info, f"aria2-{gid}")
    task_summary = _task_summary(gid, info, task_name)
    task_info: Dict[str, Any] = {
        "status": (
            DownloadStatus.METADATA if is_magnet else DownloadStatus.DOWNLOADING
        ),
        "start_time": arrow.now(),
        "downing_tips_msg_id": [],
        "group_ids": group_ids,
        "name": name,
        "manual_selection": manual_selection,
        "selection_handler": selection_handler,
    }
    try:
        if torrent_content is not None:
            torrent_path, torrent_name = _save_torrent_source(
                gid, url, torrent_content, info
            )
            task_info["torrent_path"] = torrent_path
            task_info["torrent_name"] = torrent_name
            _attach_torrent_to_status(task_info, info)
        download_tasks[gid] = task_info

        if is_magnet:
            elapsed = asyncio.get_running_loop().time() - acquire_started
            remaining = config.aria2_acquire_timeout - elapsed
            task_info["acquire_timeout_task"] = asyncio.create_task(
                _abandon_metadata_after_timeout(
                    bot,
                    gid,
                    group_ids,
                    name,
                    remaining,
                ),
                name=f"rss-metadata-timeout-{gid}",
            )
            schedule_status_check(bot, gid, group_ids, name)
            await send_msg(
                bot,
                f"👏 {name}\nGID：{gid}\n正在获取磁力链接的种子元数据……",
                group_ids,
            )
        elif manual_selection:
            await _prepare_manual_download(bot, gid, info, group_ids, name, task_info)
        else:
            if size_limit_message := _size_limit_message(info):
                queued_count = await _reject_content_and_queue_torrent(
                    gid, info, task_info, group_ids, name
                )
                raise DownloadSizeLimitExceeded(
                    f"{size_limit_message}\n{_torrent_queue_result(queued_count)}"
                )
            if str(info.get("status", "")) == "paused":
                await _rpc_call("aria2.unpause", [gid])
            _track_download(bot, gid, group_ids, task_name, task_info)
            await send_msg(
                bot,
                f"👏 订阅：{name}\n{task_summary}\n下载任务添加成功！",
                group_ids,
            )
    except Aria2Error as exc:
        if not task_info.get("torrent_upload_queued"):
            await _remove_download(gid, str(info.get("status", "")))
            _delete_torrent_source(task_info)
            _clear_download_tracking(gid)
        if isinstance(exc, DownloadSizeLimitExceeded):
            msg = f"❌ 已拒绝下载：\n{exc}"
        else:
            msg = f"❌ 创建下载任务失败：\n{exc}"
        logger.error(msg)
        await send_message_to_admin(msg, bot)
        await send_msg(bot, msg, group_ids)
        return None

    return {"gid": gid, "name": task_name, "summary": task_summary}


async def download_torrents(
    rss: Rss, item: Dict[str, Any], proxy: Optional[str]
) -> List[Dict[str, str]]:
    """Submit all torrent links in one RSS entry to the download backend."""
    bot = await get_bot()
    if bot is None:
        raise ValueError("没有可用的 Bot，无法创建下载任务")

    group_ids = _whitelisted_group_ids(rss.group_id) if rss.is_open_upload_group else []
    if rss.is_open_upload_group and rss.group_id and not group_ids:
        logger.info(f"{rss.name} 没有 RSS 白名单群组，跳过种子下载")
        return []
    download_infos: List[Dict[str, str]] = []
    for link in item.get("links", []):
        if not is_torrent_link(link):
            continue
        if info := await start_download(
            bot=bot,
            url=str(link["href"]),
            group_ids=group_ids,
            name=rss.name,
            proxy=proxy,
        ):
            download_infos.append(info)
    return download_infos
