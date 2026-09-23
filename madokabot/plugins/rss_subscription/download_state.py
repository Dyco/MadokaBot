"""RSS 下载任务在进程内共享的状态。"""

import asyncio
from enum import Enum
from typing import Any, Dict

from nonebot_plugin_apscheduler import scheduler


class DownloadStatus(str, Enum):
    """插件侧记录的下载状态。"""

    METADATA = "metadata"
    WAITING_SELECTION = "waiting_selection"
    DOWNLOADING = "downloading"
    UPLOAD_QUEUED = "upload_queued"
    UPLOADING = "uploading"
    UPLOAD_VERIFYING = "upload_verifying"
    UPLOAD_COMPLETE = "upload_complete"
    UPLOAD_FAILED = "upload_failed"
    DELETE_FAILED = "delete_failed"


# 下载任务状态保存在进程内，与原有下载后端保持一致。
download_tasks: Dict[str, Dict[str, Any]] = {}


def _clear_download_tracking(gid: str) -> None:
    """清除任务状态并取消元数据超时计时。"""
    _stop_status_check(gid)
    task_info = download_tasks.pop(gid, None)
    if task_info is None:
        return
    timeout_task = task_info.pop("acquire_timeout_task", None)
    if (
        isinstance(timeout_task, asyncio.Task)
        and timeout_task is not asyncio.current_task()
    ):
        timeout_task.cancel()


def _stop_status_check(gid: str) -> None:
    """移除指定 GID 的下载状态轮询任务。"""
    if scheduler.get_job(gid):
        scheduler.remove_job(gid)
