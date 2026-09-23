"""RSS 下载文件与群上传记录的持久化。"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from nonebot.log import logger

from madokabot.core.messaging.media import MediaDeliveryMode

from .config import DOWNLOAD_RECORD_PATH
from .download_state import DownloadStatus, download_tasks
from .download_validation import _int_value
from .utils import convert_size


def _load_download_records() -> Dict[str, Dict[str, Any]]:
    """从原有 JSON 路径加载保留的下载记录。"""
    if not DOWNLOAD_RECORD_PATH.is_file():
        return {}
    try:
        payload = json.loads(DOWNLOAD_RECORD_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error(f"读取下载文件记录失败[{DOWNLOAD_RECORD_PATH}]：{exc}")
        return {}
    if not isinstance(payload, dict):
        logger.error(f"下载文件记录格式错误[{DOWNLOAD_RECORD_PATH}]")
        return {}
    return {
        str(gid): record for gid, record in payload.items() if isinstance(record, dict)
    }


download_records: Dict[str, Dict[str, Any]] = _load_download_records()


def _write_download_records() -> None:
    """使用临时文件原子保存下载记录。"""
    DOWNLOAD_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = DOWNLOAD_RECORD_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(download_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(DOWNLOAD_RECORD_PATH)


def _save_download_record(gid: str, task_info: Dict[str, Any]) -> None:
    """更新单个下载任务的持久化记录。"""
    previous = download_records.get(gid, {})
    status = task_info.get("status", DownloadStatus.UPLOAD_FAILED)
    if isinstance(status, DownloadStatus):
        status = status.value
    failures = task_info.get("upload_failures")
    group_ids = {str(group_id) for group_id in task_info.get("group_ids", [])}
    if isinstance(failures, dict):
        group_ids.update(str(group_id) for group_id in failures)
    download_records[gid] = {
        "status": str(status),
        "name": str(task_info.get("name") or "下载任务"),
        "group_ids": sorted(group_ids),
        "download_status": task_info.get("download_status") or {},
        "torrent_path": task_info.get("torrent_path") or previous.get("torrent_path"),
        "torrent_name": task_info.get("torrent_name") or previous.get("torrent_name"),
        "upload_failures": failures if isinstance(failures, dict) else {},
        "upload_items": task_info.get("upload_items") or [],
        "created_at": (
            task_info.get("created_at")
            or previous.get("created_at")
            or datetime.now().astimezone().isoformat()
        ),
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    try:
        _write_download_records()
    except OSError as exc:
        logger.error(f"保存下载文件记录失败[{DOWNLOAD_RECORD_PATH}]：{exc}")
        return
    download_status = download_records[gid]["download_status"]
    files = (
        download_status.get("files", []) if isinstance(download_status, dict) else []
    )
    file_names = [
        Path(str(file_info.get("path"))).name
        for file_info in files
        if isinstance(file_info, dict) and file_info.get("path")
    ]
    if torrent_name := download_records[gid].get("torrent_name"):
        file_names.insert(0, str(torrent_name))
    logger.info(
        f"已保存下载文件记录[{gid}]："
        f"{', '.join(file_names) or '没有文件名'}；{DOWNLOAD_RECORD_PATH}"
    )


def _remove_download_record(gid: str) -> None:
    """移除指定 GID 的持久化记录。"""
    if download_records.pop(gid, None) is None:
        return
    try:
        _write_download_records()
    except OSError as exc:
        logger.error(f"更新下载文件记录失败[{DOWNLOAD_RECORD_PATH}]：{exc}")


def _now_iso() -> str:
    """生成带时区的当前时间字符串。"""
    return datetime.now().astimezone().isoformat()


def _upload_item_id(gid: str, group_id: str, path: str) -> str:
    """按任务、群和路径生成稳定的上传项标识。"""
    value = f"{gid}\0{group_id}\0{path}".encode("utf-8")
    return hashlib.sha1(value).hexdigest()[:16]


def _upload_item_size(file_info: Dict[str, Any], path: Path) -> int:
    """优先读取本地文件大小，失败时使用 aria2 状态。"""
    try:
        return path.stat().st_size
    except OSError:
        return _int_value(file_info.get("length"))


def _new_upload_item(
    gid: str,
    group_id: str,
    file_info: Dict[str, Any],
) -> Dict[str, Any]:
    """建立一个待上传文件的记录。"""
    path = Path(str(file_info.get("path") or ""))
    file_name = str(file_info.get("upload_name") or path.name)
    return {
        "id": _upload_item_id(gid, group_id, str(path)),
        "group_id": group_id,
        "folder_id": "/",
        "local_path": str(path),
        "file_name": file_name,
        "file_size": _upload_item_size(file_info, path),
        "expected_size": _int_value(file_info.get("length")),
        "delivery_mode": None,
        "status": DownloadStatus.UPLOAD_QUEUED.value,
        "upload_success": False,
        "attempt_count": 0,
        "verification_error_count": 0,
        "manual_retry_count": 0,
        "last_attempt_at": None,
        "next_verify_at": None,
        "verified_at": None,
        "remote_file_id": None,
        "remote_message_id": None,
        "last_error": None,
    }


def _refresh_upload_record_status(record: Dict[str, Any]) -> None:
    """按各文件状态汇总任务的上传状态。"""
    items = record.get("upload_items")
    if not isinstance(items, list) or not items:
        record["status"] = DownloadStatus.UPLOAD_FAILED.value
        return
    statuses = {str(item.get("status") or "") for item in items}
    if statuses == {DownloadStatus.UPLOAD_COMPLETE.value}:
        record["status"] = DownloadStatus.UPLOAD_COMPLETE.value
    elif DownloadStatus.UPLOADING.value in statuses:
        record["status"] = DownloadStatus.UPLOADING.value
    elif DownloadStatus.UPLOAD_QUEUED.value in statuses:
        record["status"] = DownloadStatus.UPLOAD_QUEUED.value
    elif DownloadStatus.UPLOAD_VERIFYING.value in statuses:
        record["status"] = DownloadStatus.UPLOAD_VERIFYING.value
    else:
        record["status"] = DownloadStatus.UPLOAD_FAILED.value


def _save_upload_record(gid: str, record: Dict[str, Any]) -> None:
    """保存上传进度并同步进程内任务状态。"""
    _refresh_upload_record_status(record)
    _save_download_record(gid, record)
    if task_info := download_tasks.get(gid):
        task_info["status"] = record["status"]
        task_info["upload_items"] = record.get("upload_items", [])


def _find_upload_item(record: Dict[str, Any], item_id: str) -> Optional[Dict[str, Any]]:
    """按文件标识从任务记录中查找上传项。"""
    items = record.get("upload_items")
    if not isinstance(items, list):
        return None
    return next(
        (
            item
            for item in items
            if isinstance(item, dict) and str(item.get("id")) == item_id
        ),
        None,
    )


def _migrate_legacy_upload_items(
    gid: str, record: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """把旧版失败文件列表补成可恢复的上传项。"""
    items = record.get("upload_items")
    if isinstance(items, list) and items:
        return [item for item in items if isinstance(item, dict)]

    failures = record.get("upload_failures")
    migrated: List[Dict[str, Any]] = []
    if isinstance(failures, dict):
        for group_id, files in failures.items():
            if not isinstance(files, list):
                continue
            for file_info in files:
                if isinstance(file_info, dict) and file_info.get("path"):
                    item = _new_upload_item(gid, str(group_id), file_info)
                    item["status"] = DownloadStatus.UPLOAD_VERIFYING.value
                    item["next_verify_at"] = _now_iso()
                    item["last_error"] = "由旧版上传记录迁移，先核验后决定是否重传"
                    migrated.append(item)
    record["upload_items"] = migrated
    return migrated


def get_download_record_messages(group_id: Optional[str] = None) -> List[str]:
    """生成指定群可见的下载记录摘要。"""
    messages: List[str] = []
    records = sorted(
        download_records.items(),
        key=lambda item: str(item[1].get("updated_at") or ""),
        reverse=True,
    )
    for gid, record in records:
        status = str(record.get("status") or "")
        record_groups = {str(value) for value in record.get("group_ids", [])}
        upload_items = _migrate_legacy_upload_items(gid, record)
        if group_id is not None:
            upload_items = [
                item for item in upload_items if str(item.get("group_id")) == group_id
            ]
            if not upload_items:
                continue

        file_lines = []
        for item in upload_items[:10]:
            item_status = str(item.get("status") or "未知")
            status_label = {
                DownloadStatus.UPLOAD_QUEUED.value: "排队中",
                DownloadStatus.UPLOADING.value: "上传中",
                DownloadStatus.UPLOAD_VERIFYING.value: "等待核验",
                DownloadStatus.UPLOAD_COMPLETE.value: "上传成功",
                DownloadStatus.UPLOAD_FAILED.value: "上传失败",
            }.get(item_status, item_status)
            file_name = str(item.get("file_name") or "未知文件")
            file_size = convert_size(_int_value(item.get("file_size")))
            delivery_mode = {
                MediaDeliveryMode.VIDEO_MESSAGE.value: "视频消息",
                MediaDeliveryMode.VIDEO_COMPRESS.value: "压缩后发送视频",
                MediaDeliveryMode.GROUP_FILE.value: "群文件",
            }.get(str(item.get("delivery_mode") or ""), "待判定")
            attempts = _int_value(item.get("attempt_count"))
            verification_errors = _int_value(item.get("verification_error_count"))
            manual_retries = _int_value(item.get("manual_retry_count"))
            last_attempt = item.get("last_attempt_at") or "尚未尝试"
            next_verify = item.get("next_verify_at")
            verify_message = f"，下次核验：{next_verify}" if next_verify else ""
            file_lines.append(
                f"- {file_name}[{file_size}]：{status_label}（{delivery_mode}）\n"
                f"  尝试 {attempts} 次，核验异常 {verification_errors} 次，"
                f"手动重试 {manual_retries} 次\n"
                f"  上次尝试：{last_attempt}{verify_message}"
            )
            if item.get("last_error"):
                file_lines.append(f"  最近错误：{item['last_error']}")
        if len(upload_items) > 10:
            file_lines.append(f"- 另有 {len(upload_items) - 10} 个文件")

        status_names = {
            DownloadStatus.UPLOAD_QUEUED.value: "等待上传",
            DownloadStatus.UPLOADING.value: "正在上传或状态未知",
            DownloadStatus.UPLOAD_VERIFYING.value: "等待群文件核验",
            DownloadStatus.UPLOAD_COMPLETE.value: "全部上传成功",
            DownloadStatus.UPLOAD_FAILED.value: "等待重试上传",
            DownloadStatus.DELETE_FAILED.value: "等待再次删除",
        }
        status_name = status_names.get(status, status)
        name = str(record.get("name") or "下载任务")
        updated_at = str(record.get("updated_at") or "未知")
        groups_message = (
            f"\n目标群：{', '.join(sorted(record_groups)) or '无'}"
            if group_id is None
            else ""
        )
        messages.append(
            f"{name}\nGID：{gid}\n状态：{status_name}\n"
            f"记录时间：{updated_at}{groups_message}\n文件：\n"
            + ("\n".join(file_lines) if file_lines else "- 无可用文件信息")
        )
        if len(messages) >= 20:
            break
    return messages
