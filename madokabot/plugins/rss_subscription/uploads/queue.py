"""RSS 群文件上传队列与上传前检查。"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from nonebot.adapters.onebot.v11 import ActionFailed, Bot, NetworkError
from nonebot.log import logger

from madokabot.core.group.access import is_group_whitelisted
from madokabot.core.messaging.media import MediaDeliveryMode, media_delivery

from ..aria2_client import Aria2Error
from ..config import config
from ..download_notices import _safe_upload_notice
from ..download_records import (
    _find_upload_item,
    _now_iso,
    _save_upload_record,
    download_records,
)
from ..download_state import DownloadStatus
from ..download_validation import _int_value
from ..utils import get_bot, get_bot_group_list
from .completion import _finish_upload_record_if_complete
from .verification import _schedule_upload_verification, _upload_verify_delay_text

upload_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
queued_upload_items: set[tuple[str, str]] = set()
upload_workers: set[asyncio.Task[None]] = set()


async def _check_upload_preconditions(
    bot: Bot,
    item: Dict[str, Any],
) -> tuple[Path, MediaDeliveryMode, Optional[Dict[str, Any]]]:
    """确认群权限、文件完整性和群文件空间。"""
    group_id = str(item.get("group_id") or "")
    if not group_id.isdigit() or not is_group_whitelisted(group_id):
        raise Aria2Error(f"群号无效或不在白名单中：{group_id or '未知'}")

    group_list = await get_bot_group_list(bot)
    if int(group_id) not in group_list:
        raise Aria2Error(f"Bot[{bot.self_id}]未加入群组[{group_id}]")

    path = Path(str(item.get("local_path") or ""))
    if not path.is_file():
        raise Aria2Error(f"找不到待上传文件：{path}")
    file_size = path.stat().st_size
    if file_size <= 0:
        raise Aria2Error(f"待上传文件大小为 0：{path}")
    expected_size = _int_value(item.get("expected_size"))
    if expected_size > 0 and file_size != expected_size:
        raise Aria2Error(
            f"待上传文件大小不完整：预期 {expected_size} 字节，实际 {file_size} 字节"
        )

    file_name = str(item.get("file_name") or path.name)
    if not file_name or "/" in file_name or "\\" in file_name:
        raise Aria2Error(f"群文件名不合法：{file_name or '空文件名'}")
    item["file_name"] = file_name
    item["file_size"] = file_size
    media = media_delivery.inspect(path, file_name)
    item["file_name"] = media.name
    item["delivery_mode"] = media.mode.value

    if media.mode in {
        MediaDeliveryMode.VIDEO_MESSAGE,
        MediaDeliveryMode.VIDEO_COMPRESS,
    }:
        return path, media.mode, None

    duplicate = await media_delivery.find_same_group_file(
        bot,
        group_id,
        media.name,
        file_size,
        str(item.get("folder_id") or "/"),
    )
    if duplicate:
        return path, media.mode, duplicate

    system_info = await media_delivery.get_group_file_system_info(bot, group_id)
    file_count = _int_value(system_info.get("file_count"))
    limit_count = _int_value(system_info.get("limit_count"))
    used_space = _int_value(system_info.get("used_space"))
    total_space = _int_value(system_info.get("total_space"))
    if limit_count and file_count >= limit_count:
        logger.warning(f"群[{group_id}]群文件数量已达到上限")
    if total_space and total_space - used_space < file_size:
        logger.warning(
            f"群[{group_id}]永久文件剩余空间可能不足，LLBot 将自行决定"
            "是否改用临时群文件"
        )
    return path, media.mode, None


async def _process_upload_item(bot: Bot, gid: str, item_id: str) -> None:
    """处理一个上传项并安排后续核验。"""
    record = download_records.get(gid)
    if not record or not (item := _find_upload_item(record, item_id)):
        return
    if str(item.get("status")) != DownloadStatus.UPLOAD_QUEUED.value:
        return

    group_id = str(item.get("group_id"))
    item["status"] = DownloadStatus.UPLOADING.value
    item["last_error"] = None
    item["verification_error_count"] = 0
    _save_upload_record(gid, record)

    try:
        path, delivery_mode, duplicate = await _check_upload_preconditions(
            bot,
            item,
        )
    except Exception as exc:
        item["last_error"] = f"上传前检查失败：{type(exc).__name__}: {exc}"
        item["status"] = DownloadStatus.UPLOAD_FAILED.value
        item["verified_at"] = _now_iso()
        item["next_verify_at"] = None
        _save_upload_record(gid, record)
        await _safe_upload_notice(
            bot,
            f"❌ {record.get('name', '下载任务')}\nGID：{gid}\n"
            f"文件上传前检查未通过：{item.get('file_name')}\n"
            f"原因：{exc}\n文件会保留等待定期清理，"
            f"可使用 /RSS 重试 {gid}。",
            group_id,
        )
        return

    if duplicate:
        item["status"] = DownloadStatus.UPLOAD_COMPLETE.value
        item["upload_success"] = True
        item["verified_at"] = _now_iso()
        item["next_verify_at"] = None
        item["remote_file_id"] = duplicate.get("file_id")
        item["last_error"] = None
        _save_upload_record(gid, record)
        await _safe_upload_notice(
            bot,
            f"ℹ️ {record.get('name', '下载任务')}\nGID：{gid}\n"
            f"群文件中已存在同名且同大小的文件，已跳过上传："
            f"{item.get('file_name')}",
            group_id,
        )
        await _finish_upload_record_if_complete(bot, gid, record)
        return

    item["attempt_count"] = _int_value(item.get("attempt_count")) + 1
    item["last_attempt_at"] = _now_iso()
    _save_upload_record(gid, record)

    if delivery_mode in {
        MediaDeliveryMode.VIDEO_MESSAGE,
        MediaDeliveryMode.VIDEO_COMPRESS,
    }:
        media = media_delivery.inspect(path, str(item["file_name"]))
        prepared = media
        try:
            if media.mode is MediaDeliveryMode.VIDEO_COMPRESS:
                await _safe_upload_notice(
                    bot,
                    f"{record.get('name', '下载任务')}\nGID：{gid}\n"
                    f"正在使用 FFmpeg 压缩：{item.get('file_name')}",
                    group_id,
                )
            prepared = await media_delivery.prepare(media)
            response = await media_delivery.send_group_video(bot, group_id, prepared)
        except Exception as exc:
            item["upload_success"] = False
            item["last_error"] = f"视频消息发送失败：{type(exc).__name__}: {exc}"
            item["status"] = DownloadStatus.UPLOAD_FAILED.value
            item["verified_at"] = _now_iso()
            _save_upload_record(gid, record)
            await _safe_upload_notice(
                bot,
                f"❌ {record.get('name', '下载任务')}\nGID：{gid}\n"
                f"视频消息发送失败：{item.get('file_name')}\n"
                f"原因：{exc}\n文件会保留等待定期清理，"
                f"可使用 /RSS 重试 {gid}。",
                group_id,
            )
            return
        finally:
            media_delivery.discard_prepared(media, prepared)

        item["status"] = DownloadStatus.UPLOAD_COMPLETE.value
        item["upload_success"] = True
        item["verified_at"] = _now_iso()
        item["next_verify_at"] = None
        item["last_error"] = None
        if isinstance(response, dict):
            item["remote_message_id"] = response.get("message_id")
        _save_upload_record(gid, record)
        completed = await _finish_upload_record_if_complete(bot, gid, record)
        if not completed:
            await _safe_upload_notice(
                bot,
                f"✅ {record.get('name', '下载任务')}\nGID：{gid}\n"
                f"已通过视频消息发送：{item.get('file_name')}",
                group_id,
            )
        return

    await _safe_upload_notice(
        bot,
        f"{record.get('name', '下载任务')}\nGID：{gid}\n"
        f"开始上传群文件：{item.get('file_name')}\n"
        f"队列并发：{config.rss_upload_concurrency}",
        group_id,
    )

    reported_file_id: Optional[str] = None
    upload_error: Optional[str] = None
    try:
        media = media_delivery.inspect(path, str(item["file_name"]))
        response = await media_delivery.upload_group_file(
            bot,
            group_id,
            media,
        )
        if isinstance(response, dict) and response.get("file_id"):
            reported_file_id = str(response["file_id"])
    except (ActionFailed, NetworkError, TimeoutError) as exc:
        upload_error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            f"群文件上传调用未确认[{group_id}][{item.get('file_name')}]：{upload_error}"
        )
    except Exception as exc:
        upload_error = f"{type(exc).__name__}: {exc}"
        logger.exception(f"群文件上传异常[{group_id}][{item.get('file_name')}]")

    item["status"] = DownloadStatus.UPLOAD_VERIFYING.value
    item["reported_file_id"] = reported_file_id
    item["last_error"] = upload_error
    run_at = datetime.now().astimezone() + timedelta(
        seconds=int(config.rss_upload_verify_delay)
    )
    _schedule_upload_verification(gid, item, run_at)
    _save_upload_record(gid, record)

    result_text = (
        "上传接口已经返回，" if upload_error is None else "上传接口未能确认结果，"
    )
    await _safe_upload_notice(
        bot,
        f"{record.get('name', '下载任务')}\nGID：{gid}\n"
        f"群文件处理完成：{item.get('file_name')}\n"
        f"{result_text}将在 {_upload_verify_delay_text()}后通过群文件列表核验。",
        group_id,
    )


async def _upload_worker() -> None:
    """持续消费群文件上传队列。"""
    while True:
        gid, item_id = await upload_queue.get()
        queued_upload_items.discard((gid, item_id))
        try:
            bot = await get_bot()
            while bot is None:
                await asyncio.sleep(10)
                bot = await get_bot()
            await _process_upload_item(bot, gid, item_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"处理群文件上传队列任务失败[{gid}][{item_id}]")
        finally:
            upload_queue.task_done()


def _ensure_upload_workers() -> None:
    """按配置确保上传队列的工作任务数量。"""
    active_workers = {task for task in upload_workers if not task.done()}
    upload_workers.clear()
    upload_workers.update(active_workers)
    worker_count = max(int(config.rss_upload_concurrency), 1)
    while len(upload_workers) < worker_count:
        task = asyncio.create_task(
            _upload_worker(),
            name=f"rss-upload-worker-{len(upload_workers) + 1}",
        )
        upload_workers.add(task)


def _enqueue_upload_item(gid: str, item_id: str) -> None:
    """将未排队的上传项加入工作队列。"""
    key = (gid, item_id)
    if key in queued_upload_items:
        return
    queued_upload_items.add(key)
    upload_queue.put_nowait(key)
    _ensure_upload_workers()
