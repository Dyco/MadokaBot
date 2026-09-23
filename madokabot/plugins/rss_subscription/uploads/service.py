"""RSS 上传任务的创建与手动重试。"""

from typing import Any, Dict, List

from nonebot.adapters.onebot.v11 import Bot

from ..aria2_client import Aria2Error, get_status
from ..download_details import _task_name
from ..download_notices import _whitelisted_group_ids
from ..download_records import (
    _migrate_legacy_upload_items,
    _new_upload_item,
    _save_upload_record,
    download_records,
)
from ..download_state import DownloadStatus, download_tasks
from ..download_validation import _int_value, _status_files
from .queue import _enqueue_upload_item


async def upload_files_to_groups(
    group_ids: List[str],
    files: List[Dict[str, Any]],
    name: str,
    gid: str,
) -> int:
    """持久化所有上传项并加入单并发上传队列。"""
    valid_group_ids = _whitelisted_group_ids(group_ids)
    upload_items = [
        _new_upload_item(gid, group_id, file_info)
        for group_id in valid_group_ids
        for file_info in files
        if file_info.get("path")
    ]
    task_info = download_tasks.get(gid, {})
    record: Dict[str, Any] = {
        **task_info,
        "status": DownloadStatus.UPLOAD_QUEUED.value,
        "name": name,
        "group_ids": valid_group_ids,
        "download_status": task_info.get("download_status") or {},
        "upload_failures": {},
        "upload_items": upload_items,
    }
    download_tasks[gid] = record
    _save_upload_record(gid, record)
    for item in upload_items:
        _enqueue_upload_item(gid, str(item["id"]))
    return len(upload_items)


async def retry_upload_to_group(bot: Bot, gid: str, group_id: str) -> bool:
    """把当前群已失败的文件重新加入上传队列。"""
    record = download_records.get(gid)
    if record is None:
        try:
            info = await get_status(gid)
        except Aria2Error as exc:
            raise Aria2Error("没有找到该任务的持久化上传记录") from exc
        if str(info.get("status", "")) != "complete":
            raise Aria2Error("该 aria2 任务尚未下载完成，无法重试上传")
        files = [
            file_info
            for file_info in _status_files(info, selected_only=True)
            if file_info.get("path")
        ]
        if not files:
            raise Aria2Error("该任务没有可上传的文件")
        task_info = {
            "name": _task_name(info, "重试上传"),
            "download_status": info,
        }
        download_tasks[gid] = task_info
        return bool(
            await upload_files_to_groups([group_id], files, task_info["name"], gid)
        )

    items = _migrate_legacy_upload_items(gid, record)
    group_items = [item for item in items if str(item.get("group_id")) == group_id]
    if not group_items:
        raise Aria2Error("该任务在当前群没有文件上传记录")
    if any(
        str(item.get("status"))
        in {
            DownloadStatus.UPLOAD_QUEUED.value,
            DownloadStatus.UPLOADING.value,
            DownloadStatus.UPLOAD_VERIFYING.value,
        }
        for item in group_items
    ):
        raise Aria2Error("该任务仍在排队、上传或等待核验，请稍后再试")

    failed_items = [
        item
        for item in group_items
        if str(item.get("status")) == DownloadStatus.UPLOAD_FAILED.value
    ]
    if not failed_items:
        raise Aria2Error("该任务在当前群没有需要重试的文件")
    for item in failed_items:
        item["status"] = DownloadStatus.UPLOAD_QUEUED.value
        item["manual_retry_count"] = _int_value(item.get("manual_retry_count")) + 1
        item["verified_at"] = None
        item["next_verify_at"] = None
        item["verification_error_count"] = 0
        item["last_error"] = None
    _save_upload_record(gid, record)
    for item in failed_items:
        _enqueue_upload_item(gid, str(item["id"]))
    return True
