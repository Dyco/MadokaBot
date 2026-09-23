"""RSS 下载任务的取消与本地文件清理。"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from nonebot.log import logger

from .aria2_client import Aria2Error, _rpc_call, get_status
from .config import config
from .download_records import (
    _remove_download_record,
    _save_download_record,
    download_records,
)
from .download_state import (
    DownloadStatus,
    _clear_download_tracking,
    _stop_status_check,
    download_tasks,
)
from .download_validation import _status_files


async def _remove_download(gid: str, status: str = "") -> None:
    """取消或清理 aria2 任务，避免超限任务继续下载。"""
    method = (
        "aria2.removeDownloadResult"
        if status in {"complete", "error", "removed"}
        else "aria2.forceRemove"
    )
    try:
        await _rpc_call(method, [gid])
    except Aria2Error as exc:
        logger.warning(f"清理超限 aria2 任务[{gid}]失败：{exc}")


async def cancel_download(gid: str) -> str:
    """终止任务及其后续任务并返回原状态。"""
    info = await get_status(gid)
    status = str(info.get("status", ""))
    followed_by = info.get("followedBy")
    if isinstance(followed_by, list):
        for child_gid in followed_by:
            child_gid = str(child_gid)
            try:
                child_info = await get_status(child_gid)
                await _remove_download(child_gid, str(child_info.get("status", "")))
            except Aria2Error as exc:
                logger.warning(f"终止 aria2 后续任务[{child_gid}]失败：{exc}")
            finally:
                _clear_download_tracking(child_gid)
    method = (
        "aria2.removeDownloadResult"
        if status in {"complete", "error", "removed"}
        else "aria2.forceRemove"
    )
    await _rpc_call(method, [gid])
    _clear_download_tracking(gid)
    return status


def _cleanup_paths(status: Dict[str, Any]) -> tuple[Path, List[Path]]:
    """提取位于 aria2 任务下载目录内的文件路径。"""
    raw_dir = status.get("dir")
    if not raw_dir:
        return Path(), []

    download_dir = Path(str(raw_dir)).expanduser().resolve()
    if config.aria2_download_path:
        configured_dir = Path(config.aria2_download_path).expanduser().resolve()
        if (
            download_dir != configured_dir
            and configured_dir not in download_dir.parents
        ):
            logger.warning(f"跳过配置下载目录外的任务清理：{download_dir}")
            return download_dir, []

    paths: List[Path] = []
    for file_info in _status_files(status):
        raw_path = file_info.get("path")
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser().resolve()
        if path == download_dir or download_dir not in path.parents:
            logger.warning(f"跳过下载目录外的清理路径：{path}")
            continue
        paths.append(path)
    raw_torrent_path = status.get("_torrent_path")
    if raw_torrent_path:
        torrent_path = Path(str(raw_torrent_path)).expanduser().resolve()
        if torrent_path != download_dir and download_dir in torrent_path.parents:
            if torrent_path not in paths:
                paths.append(torrent_path)
        else:
            logger.warning(f"跳过下载目录外的种子清理路径：{torrent_path}")
    return download_dir, paths


async def delete_download_files(
    gid: str, group_id: Optional[str] = None
) -> tuple[int, List[Path]]:
    """删除指定任务的本地文件并更新记录。"""
    task_info = download_tasks.get(gid)
    if not task_info and (stored_record := download_records.get(gid)):
        task_info = dict(stored_record)
    stored_status = task_info.get("download_status") if task_info else None
    info = stored_status if isinstance(stored_status, dict) else await get_status(gid)
    download_dir, paths = _cleanup_paths(info)
    if not paths:
        raise Aria2Error("该任务没有可安全删除的文件路径")

    _stop_status_check(gid)
    aria2_status = str(info.get("status", ""))
    if aria2_status not in {"complete", "error", "removed"}:
        try:
            await _rpc_call("aria2.forceRemove", [gid])
        except Aria2Error as exc:
            raise Aria2Error(
                f"无法先停止仍在运行的 aria2 任务，未删除任何文件：{exc}"
            ) from exc
        info["status"] = "removed"
    else:
        await _remove_download(gid, aria2_status)

    deleted_count = 0
    failed_paths: List[Path] = []
    for path in paths:
        current_path = path.resolve()
        if current_path == download_dir or download_dir not in current_path.parents:
            logger.warning(f"跳过已离开下载目录的删除路径：{current_path}")
            failed_paths.append(current_path)
            continue
        if not current_path.exists():
            continue
        try:
            current_path.unlink()
            deleted_count += 1
        except OSError as exc:
            failed_paths.append(current_path)
            logger.warning(f"删除下载文件失败[{current_path}]：{exc}")

    parent_dirs = sorted(
        {path.parent for path in paths},
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for parent in parent_dirs:
        while parent != download_dir and download_dir in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    if failed_paths:
        retained_info = task_info or {}
        retained_info["status"] = DownloadStatus.DELETE_FAILED
        retained_info["download_status"] = info
        group_ids = {str(value) for value in retained_info.get("group_ids", [])}
        if group_id:
            group_ids.add(group_id)
        retained_info["group_ids"] = sorted(group_ids)
        download_tasks[gid] = retained_info
        _save_download_record(gid, retained_info)
    else:
        _remove_download_record(gid)
        _clear_download_tracking(gid)
    return deleted_count, failed_paths
