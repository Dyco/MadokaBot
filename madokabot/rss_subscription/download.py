"""aria2 RPC 下载及下载完成后的群文件上传。"""

import asyncio
import base64
import hashlib
import json
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence
from urllib.parse import unquote, urlsplit

import aiohttp
import arrow
from apscheduler.triggers.interval import IntervalTrigger
from nonebot.adapters.onebot.v11 import ActionFailed, Bot, NetworkError
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from ..madoka_bundle.plugins.common import (
    MediaDeliveryMode,
    is_group_whitelisted,
    media_delivery,
)
from .config import DOWNLOAD_RECORD_PATH, config
from .subscription import Rss
from .utils import (
    convert_size,
    get_bot,
    get_bot_group_list,
    send_message_to_admin,
)


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


class Aria2Error(RuntimeError):
    """aria2 RPC 或下载任务返回的错误。"""


class DownloadSizeLimitExceeded(Aria2Error):
    """下载任务中存在超过配置大小上限的文件。"""


class DownloadAcquireTimeout(Aria2Error):
    """下载链接、种子文件或磁力元数据获取超时。"""


ARIA2_STATUS_FIELDS = [
    "status",
    "errorCode",
    "errorMessage",
    "totalLength",
    "completedLength",
    "downloadSpeed",
    "seeder",
    "dir",
    "files",
    "bittorrent",
    "infoHash",
    "followedBy",
]

# 任务状态保存在进程内，和原下载后端保持一致。
download_tasks: Dict[str, Dict[str, Any]] = {}
progress_recall_tasks: set[asyncio.Task[None]] = set()

SelectionHandler = Callable[
    [Bot, str, List[Dict[str, Any]], List[str], str], Awaitable[None]
]


def _load_download_records() -> Dict[str, Dict[str, Any]]:
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
        str(gid): record
        for gid, record in payload.items()
        if isinstance(record, dict)
    }


download_records: Dict[str, Dict[str, Any]] = _load_download_records()
upload_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
queued_upload_items: set[tuple[str, str]] = set()
upload_workers: set[asyncio.Task[None]] = set()


def _write_download_records() -> None:
    DOWNLOAD_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = DOWNLOAD_RECORD_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(download_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(DOWNLOAD_RECORD_PATH)


def _save_download_record(gid: str, task_info: Dict[str, Any]) -> None:
    previous = download_records.get(gid, {})
    status = task_info.get("status", DownloadStatus.UPLOAD_FAILED)
    if isinstance(status, DownloadStatus):
        status = status.value
    failures = task_info.get("upload_failures")
    group_ids = {
        str(group_id) for group_id in task_info.get("group_ids", [])
    }
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
        download_status.get("files", [])
        if isinstance(download_status, dict)
        else []
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
    if download_records.pop(gid, None) is None:
        return
    try:
        _write_download_records()
    except OSError as exc:
        logger.error(f"更新下载文件记录失败[{DOWNLOAD_RECORD_PATH}]：{exc}")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _upload_item_id(gid: str, group_id: str, path: str) -> str:
    value = f"{gid}\0{group_id}\0{path}".encode("utf-8")
    return hashlib.sha1(value).hexdigest()[:16]


def _upload_item_size(file_info: Dict[str, Any], path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return _int_value(file_info.get("length"))


def _new_upload_item(
    gid: str,
    group_id: str,
    file_info: Dict[str, Any],
) -> Dict[str, Any]:
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
        "retry_count": 0,
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
    _refresh_upload_record_status(record)
    _save_download_record(gid, record)
    if task_info := download_tasks.get(gid):
        task_info["status"] = record["status"]
        task_info["upload_items"] = record.get("upload_items", [])


def _find_upload_item(
    record: Dict[str, Any], item_id: str
) -> Optional[Dict[str, Any]]:
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


def _rpc_url() -> str:
    url = str(config.aria2_rpc_url or "http://127.0.0.1:6800/jsonrpc").strip()
    if not url:
        return "http://127.0.0.1:6800/jsonrpc"
    if not url.rstrip("/").endswith("/jsonrpc"):
        url = f"{url.rstrip('/')}/jsonrpc"
    return url


def _rpc_params(params: Sequence[Any]) -> List[Any]:
    result = list(params)
    if config.aria2_rpc_secret:
        result.insert(0, f"token:{config.aria2_rpc_secret}")
    return result


async def _rpc_call(method: str, params: Sequence[Any] = ()) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": "madokabot-rss",
        "method": method,
        "params": _rpc_params(params),
    }
    timeout = aiohttp.ClientTimeout(total=config.aria2_acquire_timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(_rpc_url(), json=payload) as response:
                response.raise_for_status()
                result = await response.json()
    except asyncio.TimeoutError as exc:
        raise DownloadAcquireTimeout(
            f"aria2 RPC 请求超过 {config.aria2_acquire_timeout} 秒"
        ) from exc
    except aiohttp.ClientError as exc:
        raise Aria2Error(f"无法连接 aria2 RPC：{exc}") from exc
    except ValueError as exc:
        raise Aria2Error("aria2 RPC 返回了无效的 JSON") from exc

    if not isinstance(result, dict):
        raise Aria2Error("aria2 RPC 返回格式错误")
    if error := result.get("error"):
        if isinstance(error, dict):
            code = error.get("code", "?")
            message = error.get("message", "未知错误")
            raise Aria2Error(f"aria2 错误[{code}]：{message}")
        raise Aria2Error(f"aria2 错误：{error}")
    if "result" not in result:
        raise Aria2Error("aria2 RPC 返回中缺少 result")
    return result["result"]


def _download_options(proxy: Optional[str] = None) -> Dict[str, str]:
    options: Dict[str, str] = {
        "seed-time": "0",
        "bt-save-metadata": "true",
    }
    if config.aria2_download_path:
        download_path = Path(config.aria2_download_path).expanduser().resolve()
        try:
            download_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Aria2Error(f"无法创建 aria2 下载目录：{download_path}：{exc}") from exc
        options["dir"] = str(download_path)
    if proxy:
        options["all-proxy"] = proxy
    return options


async def _fetch_torrent(url: str, proxy: Optional[str]) -> bytes:
    timeout = aiohttp.ClientTimeout(total=config.aria2_acquire_timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, proxy=proxy) as response:
                response.raise_for_status()
                return await response.read()
    except asyncio.TimeoutError as exc:
        raise DownloadAcquireTimeout(
            f"torrent 文件获取超过 {config.aria2_acquire_timeout} 秒"
        ) from exc
    except aiohttp.ClientError as exc:
        raise Aria2Error(f"下载 torrent 文件失败：{exc}") from exc


async def aria2_version() -> str:
    result = await _rpc_call("aria2.getVersion")
    if isinstance(result, dict):
        return str(result.get("version", "unknown"))
    return "unknown"


async def add_download(
    url: str,
    proxy: Optional[str] = None,
) -> tuple[str, Optional[bytes]]:
    """把磁力链接或 torrent 地址提交给 aria2，并保留原种子内容。"""
    options = _download_options(proxy)
    torrent_content: Optional[bytes] = None
    if url.lower().startswith("magnet:?"):
        # 元数据本身仍需下载，实际 BT 任务保持暂停直至完成大小校验。
        options["pause-metadata"] = "true"
        result = await _rpc_call("aria2.addUri", [[url], options])
    else:
        options["pause"] = "true"
        torrent_content = await _fetch_torrent(url, proxy)
        torrent = base64.b64encode(torrent_content).decode("ascii")
        result = await _rpc_call("aria2.addTorrent", [torrent, [], options])
    if not isinstance(result, str) or not result:
        raise Aria2Error(f"aria2 未返回有效 GID：{result!r}")
    return result, torrent_content


def _torrent_file_name(url: str, fallback: str) -> str:
    name = Path(unquote(urlsplit(url).path)).name
    if not name.lower().endswith(".torrent"):
        name = f"{fallback}.torrent"
    return media_delivery.sanitize_file_name(name)


def _save_torrent_source(
    gid: str,
    url: str,
    content: bytes,
    status: Dict[str, Any],
) -> tuple[str, str]:
    raw_dir = status.get("dir") or config.aria2_download_path
    if not raw_dir:
        raise Aria2Error("aria2 未返回下载目录，无法保留 torrent 文件")
    file_name = _torrent_file_name(url, gid)
    download_dir = Path(str(raw_dir)).expanduser().resolve()
    rpc_saved_path = download_dir / f"{hashlib.sha1(content).hexdigest()}.torrent"
    if rpc_saved_path.is_file():
        return str(rpc_saved_path), file_name
    torrent_dir = (
        download_dir / ".madokabot-torrents" / gid
    )
    torrent_path = torrent_dir / file_name
    try:
        torrent_dir.mkdir(parents=True, exist_ok=True)
        torrent_path.write_bytes(content)
    except OSError as exc:
        raise Aria2Error(f"保存 torrent 文件失败：{exc}") from exc
    return str(torrent_path), file_name


def _find_saved_magnet_torrent(status: Dict[str, Any]) -> Optional[Path]:
    raw_dir = status.get("dir")
    info_hash = str(status.get("infoHash") or "").strip()
    if not raw_dir or not info_hash:
        return None
    download_dir = Path(str(raw_dir)).expanduser().resolve()
    candidates = (
        download_dir / f"{info_hash}.torrent",
        download_dir / f"{info_hash.lower()}.torrent",
        download_dir / f"{info_hash.upper()}.torrent",
    )
    return next((path for path in candidates if path.is_file()), None)


def _attach_torrent_to_status(
    task_info: Dict[str, Any], status: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    torrent_path_value = task_info.get("torrent_path")
    torrent_path = Path(str(torrent_path_value)) if torrent_path_value else None
    if torrent_path is None or not torrent_path.is_file():
        torrent_path = _find_saved_magnet_torrent(status)
        if torrent_path is not None:
            task_info["torrent_path"] = str(torrent_path)
            task_info["torrent_name"] = media_delivery.sanitize_file_name(
                f"{_task_name(status, torrent_path.stem)}.torrent"
            )
    if torrent_path is None or not torrent_path.is_file():
        return None

    torrent_name = str(task_info.get("torrent_name") or torrent_path.name)
    status["_torrent_path"] = str(torrent_path)
    status["_torrent_name"] = torrent_name
    return {
        "path": str(torrent_path),
        "length": str(torrent_path.stat().st_size),
        "selected": "true",
        "upload_name": torrent_name,
        "is_torrent_source": True,
    }


def _delete_torrent_source(task_info: Dict[str, Any]) -> None:
    raw_path = task_info.get("torrent_path")
    if not raw_path:
        return
    path = Path(str(raw_path))
    try:
        path.unlink(missing_ok=True)
        if path.parent.parent.name == ".madokabot-torrents":
            path.parent.rmdir()
    except OSError as exc:
        logger.warning(f"清理 torrent 源文件失败[{path}]：{exc}")


async def get_status(gid: str) -> Dict[str, Any]:
    result = await _rpc_call("aria2.tellStatus", [gid, ARIA2_STATUS_FIELDS])
    if not isinstance(result, dict):
        raise Aria2Error(f"aria2 任务状态格式错误：{result!r}")
    return result


def _int_value(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _is_selected(file_info: Dict[str, Any]) -> bool:
    selected = file_info.get("selected", "true")
    if isinstance(selected, bool):
        return selected
    return str(selected).lower() != "false"


def _status_files(
    status: Dict[str, Any], selected_only: bool = False
) -> List[Dict[str, Any]]:
    files = status.get("files")
    if not isinstance(files, list):
        return []
    return [
        file_info
        for file_info in files
        if isinstance(file_info, dict)
        and (not selected_only or _is_selected(file_info))
    ]


def _max_file_size_bytes() -> int:
    """返回单个文件允许的最大字节数。"""
    return int(config.aria2_max_file_size_mb) * 1024 * 1024


def _max_total_size_bytes() -> int:
    """返回单个下载任务允许的最大总字节数。"""
    return int(config.aria2_max_total_size_mb) * 1024 * 1024


def _oversized_files(status: Dict[str, Any]) -> List[Dict[str, Any]]:
    """找出 aria2 状态中已知大小超过限制的文件。"""
    max_size = _max_file_size_bytes()
    return [
        file_info
        for file_info in _status_files(status, selected_only=True)
        if not media_delivery.is_video(str(file_info.get("path") or ""))
        and _int_value(file_info.get("length")) > max_size
    ]


def _oversized_videos(status: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        file_info
        for file_info in _status_files(status, selected_only=True)
        if media_delivery.is_video(str(file_info.get("path") or ""))
        and _int_value(file_info.get("length"))
        > media_delivery.video_compress_limit
    ]


def _total_download_size(status: Dict[str, Any]) -> int:
    """返回已选文件总大小；没有文件明细时使用任务总大小。"""
    files = _status_files(status, selected_only=True)
    if files:
        return sum(_int_value(file_info.get("length")) for file_info in files)
    return _int_value(status.get("totalLength"))


def _size_limit_message(status: Dict[str, Any]) -> Optional[str]:
    """生成超出单文件或总大小限制时的提示。"""
    messages: List[str] = []
    videos = _oversized_videos(status)
    if videos:
        details = "\n".join(
            f"- {file_info.get('path') or '未知视频'}："
            f"{convert_size(_int_value(file_info.get('length')))}"
            for file_info in videos
        )
        messages.append(
            "视频超过允许下载和压缩的大小限制（"
            f"{media_delivery.video_compress_limit / 1024 / 1024:g} MiB）：\n"
            f"{details}"
        )

    files = _oversized_files(status)
    if files:
        details = "\n".join(
            f"- {file_info.get('path') or '未知文件'}："
            f"{convert_size(_int_value(file_info.get('length')))}"
            for file_info in files
        )
        messages.append(
            "单个文件超过下载大小限制（"
            f"{config.aria2_max_file_size_mb} MiB）：\n{details}"
        )

    total_size = _total_download_size(status)
    if total_size > _max_total_size_bytes():
        messages.append(
            "下载任务总大小超过限制（"
            f"{config.aria2_max_total_size_mb} MiB）："
            f"{convert_size(total_size)}"
        )

    return "\n".join(messages) or None


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


def _clear_download_tracking(gid: str) -> None:
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
    if scheduler.get_job(gid):
        scheduler.remove_job(gid)


async def cancel_download(gid: str) -> str:
    """Stop an aria2 task and return its status before removal."""
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


def _task_name(status: Dict[str, Any], fallback: str) -> str:
    bittorrent = status.get("bittorrent")
    if isinstance(bittorrent, dict):
        info = bittorrent.get("info")
        if isinstance(info, dict) and info.get("name"):
            return str(info["name"])
    files = status.get("files")
    if isinstance(files, list) and files:
        path = files[0].get("path") if isinstance(files[0], dict) else None
        if path:
            path_obj = Path(str(path))
            if len(files) == 1:
                return path_obj.name
            return path_obj.parent.name or path_obj.name
    return fallback


def _task_summary(gid: str, status: Dict[str, Any], fallback: str) -> str:
    name = _task_name(status, fallback)
    total = _total_download_size(status)
    size = convert_size(total) if total else "获取中"
    return f"{name}\n文件大小：{size}\nGID：{gid}"


def parse_file_selection(selection: str, valid_indices: Sequence[int]) -> List[int]:
    """解析 `1,3-5` 形式的文件编号并校验范围。"""
    value = selection.strip().replace("，", ",")
    if not value:
        raise Aria2Error("请输入要下载的文件编号")

    valid = set(valid_indices)
    selected: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            raise Aria2Error("文件编号格式错误，请使用 1,3-5 这样的格式")
        if "-" in part:
            bounds = part.split("-", 1)
            if len(bounds) != 2 or not all(item.strip().isdigit() for item in bounds):
                raise Aria2Error("文件编号格式错误，请使用 1,3-5 这样的格式")
            start, end = (int(item.strip()) for item in bounds)
            if start > end:
                raise Aria2Error(f"文件编号范围不能倒序：{part}")
            selected.update(range(start, end + 1))
        elif part.isdigit():
            selected.add(int(part))
        else:
            raise Aria2Error("文件编号格式错误，请使用 1,3-5 这样的格式")

    invalid = sorted(selected - valid)
    if invalid:
        raise Aria2Error(f"不存在这些文件编号：{','.join(map(str, invalid))}")
    if not selected:
        raise Aria2Error("至少需要选择一个文件")
    return sorted(selected)


def _display_file_path(status: Dict[str, Any], file_info: Dict[str, Any]) -> str:
    raw_path = str(file_info.get("path") or "未知文件")
    download_dir = status.get("dir")
    if download_dir:
        try:
            return str(Path(raw_path).relative_to(Path(str(download_dir))))
        except ValueError:
            pass
    return Path(raw_path).name or raw_path


def _compact_file_size(file_info: Dict[str, Any]) -> str:
    size = convert_size(_int_value(file_info.get("length")))
    return size.replace(" ", "").lower()


def get_download_record_messages(group_id: Optional[str] = None) -> List[str]:
    """Build concise retained-file records visible to one group."""
    messages: List[str] = []
    records = sorted(
        download_records.items(),
        key=lambda item: str(item[1].get("updated_at") or ""),
        reverse=True,
    )
    for gid, record in records:
        status = str(record.get("status") or "")
        record_groups = {
            str(value) for value in record.get("group_ids", [])
        }
        upload_items = _migrate_legacy_upload_items(gid, record)
        if group_id is not None:
            upload_items = [
                item
                for item in upload_items
                if str(item.get("group_id")) == group_id
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
            retries = _int_value(item.get("retry_count"))
            verification_errors = _int_value(
                item.get("verification_error_count")
            )
            manual_retries = _int_value(item.get("manual_retry_count"))
            last_attempt = item.get("last_attempt_at") or "尚未尝试"
            next_verify = item.get("next_verify_at")
            verify_message = (
                f"，下次核验：{next_verify}" if next_verify else ""
            )
            file_lines.append(
                f"- {file_name}[{file_size}]：{status_label}（{delivery_mode}）\n"
                f"  尝试 {attempts} 次，自动重传 {retries} 次，"
                f"核验异常 {verification_errors} 次，"
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


def _whitelisted_group_ids(group_ids: Sequence[str]) -> List[str]:
    return [
        str(group_id)
        for group_id in group_ids
        if str(group_id).isdigit() and is_group_whitelisted(group_id)
    ]


# 发送下载通知
async def send_msg(
    bot: Bot, msg: str, notice_group: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    logger.info(msg)
    msg_id: List[Dict[str, Any]] = []
    configured_group_ids = notice_group or config.down_status_msg_group
    down_status_msg_group = _whitelisted_group_ids(configured_group_ids)
    if not down_status_msg_group:
        return msg_id
    group_list = await get_bot_group_list(bot)
    for group_id in down_status_msg_group:
        if int(group_id) not in group_list:
            logger.error(f"Bot[{bot.self_id}]未加入群组[{group_id}]")
            continue
        msg_id.append(await bot.send_group_msg(group_id=int(group_id), message=msg))
    return msg_id


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


async def send_download_progress(
    bot: Bot,
    gid: str,
    info: Dict[str, Any],
    name: str,
    group_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    total = _int_value(info.get("totalLength"))
    completed = _int_value(info.get("completedLength"))
    speed = _int_value(info.get("downloadSpeed"))
    percent = round(completed / total * 100, 2) if total else 0
    return await send_msg(
        bot,
        f"{name}\n"
        f"GID：{gid}\n"
        f"下载进度：{percent}%\n"
        f"当前速度：{convert_size(speed)}/s",
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
    header = (
        f"{name}\n检测到 {len(files)} 个文件，任务已暂停。\n"
        f"GID：{gid}\n文件列表："
    )
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


def _verification_job_id(gid: str, item_id: str) -> str:
    return f"rss-upload-verify-{gid}-{item_id}"


def _parse_record_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.astimezone()
    return result


def _upload_verify_delay_text() -> str:
    seconds = int(config.rss_upload_verify_delay)
    if seconds % 3600 == 0:
        return f"{seconds // 3600} 小时"
    if seconds % 60 == 0:
        return f"{seconds // 60} 分钟"
    return f"{seconds} 秒"


async def _safe_upload_notice(
    bot: Bot, message: str, group_id: str
) -> None:
    try:
        await send_msg(bot, message, [group_id])
    except Exception:
        logger.exception(f"发送群文件上传状态到群[{group_id}]时出错")


def _schedule_upload_verification(
    gid: str,
    item: Dict[str, Any],
    run_at: Optional[datetime] = None,
) -> None:
    item_id = str(item["id"])
    run_at = run_at or _parse_record_time(item.get("next_verify_at"))
    run_at = run_at or (
        datetime.now().astimezone()
        + timedelta(seconds=int(config.rss_upload_verify_delay))
    )
    item["next_verify_at"] = run_at.isoformat()
    scheduler.add_job(
        func=verify_uploaded_file,
        trigger="date",
        run_date=run_at,
        args=(gid, item_id),
        id=_verification_job_id(gid, item_id),
        misfire_grace_time=86400,
        replace_existing=True,
    )


async def _check_upload_preconditions(
    bot: Bot,
    item: Dict[str, Any],
) -> tuple[Path, MediaDeliveryMode, Optional[Dict[str, Any]]]:
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
            f"待上传文件大小不完整：预期 {expected_size} 字节，"
            f"实际 {file_size} 字节"
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


async def _finish_upload_record_if_complete(
    bot: Bot, gid: str, record: Dict[str, Any]
) -> bool:
    items = record.get("upload_items")
    if not isinstance(items, list) or not items:
        return False
    valid_items = [item for item in items if isinstance(item, dict)]
    if not valid_items:
        return False
    if not all(
        str(item.get("status")) == DownloadStatus.UPLOAD_COMPLETE.value
        for item in valid_items
    ):
        return False
    _save_upload_record(gid, record)
    info = record.get("download_status")
    if isinstance(info, dict):
        schedule_file_cleanup(gid, info)
    _clear_download_tracking(gid)
    message = (
        f"✅ {record.get('name', '下载任务')}\nGID：{gid}\n"
        "全部文件均已确认发送成功。"
    )
    group_ids = sorted(
        {
            str(item.get("group_id"))
            for item in items
            if isinstance(item, dict) and item.get("group_id")
        }
    )
    for group_id in group_ids:
        await _safe_upload_notice(bot, message, group_id)
    return True


async def _process_upload_item(bot: Bot, gid: str, item_id: str) -> None:
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
        retry_count = _int_value(item.get("retry_count"))
        if retry_count < int(config.rss_upload_max_retries):
            item["retry_count"] = retry_count + 1
            item["status"] = DownloadStatus.UPLOAD_QUEUED.value
            item["next_verify_at"] = None
            _save_upload_record(gid, record)
            await _safe_upload_notice(
                bot,
                f"⚠️ {record.get('name', '下载任务')}\nGID：{gid}\n"
                f"文件上传前检查未通过，开始第 {item['retry_count']} 次自动重试："
                f"{item.get('file_name')}\n原因：{exc}",
                group_id,
            )
            _enqueue_upload_item(gid, item_id)
            return

        item["status"] = DownloadStatus.UPLOAD_FAILED.value
        item["verified_at"] = _now_iso()
        item["next_verify_at"] = None
        _save_upload_record(gid, record)
        await _safe_upload_notice(
            bot,
            f"❌ {record.get('name', '下载任务')}\nGID：{gid}\n"
            f"文件上传前检查未通过：{item.get('file_name')}\n"
            f"原因：{exc}\n已达到自动重试上限，文件仍会保留，"
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
            response = await media_delivery.send_group_video(
                bot, group_id, prepared
            )
        except Exception as exc:
            retry_count = _int_value(item.get("retry_count"))
            item["upload_success"] = False
            item["last_error"] = f"视频消息发送失败：{type(exc).__name__}: {exc}"
            if retry_count < int(config.rss_upload_max_retries):
                item["retry_count"] = retry_count + 1
                item["status"] = DownloadStatus.UPLOAD_QUEUED.value
                _save_upload_record(gid, record)
                await _safe_upload_notice(
                    bot,
                    f"⚠️ {record.get('name', '下载任务')}\nGID：{gid}\n"
                    f"视频消息发送失败，开始第 {item['retry_count']} 次自动重试："
                    f"{item.get('file_name')}",
                    group_id,
                )
                _enqueue_upload_item(gid, item_id)
                return

            item["status"] = DownloadStatus.UPLOAD_FAILED.value
            item["verified_at"] = _now_iso()
            _save_upload_record(gid, record)
            await _safe_upload_notice(
                bot,
                f"❌ {record.get('name', '下载任务')}\nGID：{gid}\n"
                f"视频消息发送失败：{item.get('file_name')}\n原因：{exc}",
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
            f"群文件上传调用未确认[{group_id}][{item.get('file_name')}]："
            f"{upload_error}"
        )
    except Exception as exc:
        upload_error = f"{type(exc).__name__}: {exc}"
        logger.exception(
            f"群文件上传异常[{group_id}][{item.get('file_name')}]"
        )

    item["status"] = DownloadStatus.UPLOAD_VERIFYING.value
    item["reported_file_id"] = reported_file_id
    item["last_error"] = upload_error
    run_at = datetime.now().astimezone() + timedelta(
        seconds=int(config.rss_upload_verify_delay)
    )
    _schedule_upload_verification(gid, item, run_at)
    _save_upload_record(gid, record)

    result_text = (
        "上传接口已经返回，"
        if upload_error is None
        else "上传接口未能确认结果，"
    )
    await _safe_upload_notice(
        bot,
        f"{record.get('name', '下载任务')}\nGID：{gid}\n"
        f"群文件处理完成：{item.get('file_name')}\n"
        f"{result_text}将在 {_upload_verify_delay_text()}后通过群文件列表核验。",
        group_id,
    )


async def _upload_worker() -> None:
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
    key = (gid, item_id)
    if key in queued_upload_items:
        return
    queued_upload_items.add(key)
    upload_queue.put_nowait(key)
    _ensure_upload_workers()


async def verify_uploaded_file(gid: str, item_id: str) -> None:
    record = download_records.get(gid)
    if not record or not (item := _find_upload_item(record, item_id)):
        return
    if str(item.get("status")) != DownloadStatus.UPLOAD_VERIFYING.value:
        return

    async def handle_verification_error(
        message: str,
        bot: Optional[Bot],
    ) -> None:
        error_count = _int_value(item.get("verification_error_count")) + 1
        item["verification_error_count"] = error_count
        item["last_error"] = message
        if error_count <= int(config.rss_upload_max_retries):
            run_at = datetime.now().astimezone() + timedelta(minutes=10)
            _schedule_upload_verification(gid, item, run_at)
            _save_upload_record(gid, record)
            return

        item["status"] = DownloadStatus.UPLOAD_FAILED.value
        item["upload_success"] = False
        item["verified_at"] = _now_iso()
        item["next_verify_at"] = None
        _save_upload_record(gid, record)
        if bot is not None:
            await _safe_upload_notice(
                bot,
                f"❌ {record.get('name', '下载任务')}\nGID：{gid}\n"
                f"群文件核验连续失败：{item.get('file_name')}\n"
                f"原因：{message}\n已停止自动核验，可使用 /RSS 重试 {gid}。",
                str(item.get("group_id")),
            )

    bot = await get_bot()
    if bot is None:
        await handle_verification_error("当前没有可用的 Bot", None)
        return

    group_id = str(item.get("group_id"))
    try:
        remote_file = await media_delivery.find_same_group_file(
            bot,
            group_id,
            str(item.get("file_name") or ""),
            _int_value(item.get("file_size")),
            str(item.get("folder_id") or "/"),
        )
    except Exception as exc:
        message = f"群文件核验失败：{type(exc).__name__}: {exc}"
        await handle_verification_error(message, bot)
        logger.warning(f"群文件核验请求失败[{gid}][{item_id}]：{exc}")
        return

    item["verification_error_count"] = 0
    if remote_file:
        item["status"] = DownloadStatus.UPLOAD_COMPLETE.value
        item["upload_success"] = True
        item["remote_file_id"] = remote_file.get("file_id")
        item["verified_at"] = _now_iso()
        item["next_verify_at"] = None
        item["last_error"] = None
        _save_upload_record(gid, record)
        completed = await _finish_upload_record_if_complete(bot, gid, record)
        if not completed:
            await _safe_upload_notice(
                bot,
                f"✅ {record.get('name', '下载任务')}\nGID：{gid}\n"
                f"已确认群文件上传成功：{item.get('file_name')}",
                group_id,
            )
        return

    retry_count = _int_value(item.get("retry_count"))
    if retry_count < int(config.rss_upload_max_retries):
        item["retry_count"] = retry_count + 1
        item["status"] = DownloadStatus.UPLOAD_QUEUED.value
        item["next_verify_at"] = None
        item["last_error"] = "群文件中未找到同名且同大小的文件"
        _save_upload_record(gid, record)
        await _safe_upload_notice(
            bot,
            f"⚠️ {record.get('name', '下载任务')}\nGID：{gid}\n"
            f"{_upload_verify_delay_text()}后仍未找到群文件：{item.get('file_name')}\n"
            f"开始第 {item['retry_count']} 次自动重传。",
            group_id,
        )
        _enqueue_upload_item(gid, item_id)
        return

    item["status"] = DownloadStatus.UPLOAD_FAILED.value
    item["upload_success"] = False
    item["verified_at"] = _now_iso()
    item["next_verify_at"] = None
    item["last_error"] = "达到自动重传上限后仍未在群文件中找到文件"
    _save_upload_record(gid, record)
    await _safe_upload_notice(
        bot,
        f"❌ {record.get('name', '下载任务')}\nGID：{gid}\n"
        f"群文件上传未成功：{item.get('file_name')}\n"
        f"已达到自动重传上限 {config.rss_upload_max_retries} 次，"
        f"文件仍会保留，可使用 /RSS 重试 {gid}。",
        group_id,
    )


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
            await upload_files_to_groups(
                [group_id], files, task_info["name"], gid
            )
        )

    items = _migrate_legacy_upload_items(gid, record)
    group_items = [
        item for item in items if str(item.get("group_id")) == group_id
    ]
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
        item["manual_retry_count"] = (
            _int_value(item.get("manual_retry_count")) + 1
        )
        item["verified_at"] = None
        item["next_verify_at"] = None
        item["verification_error_count"] = 0
        item["last_error"] = None
    _save_upload_record(gid, record)
    for item in failed_items:
        _enqueue_upload_item(gid, str(item["id"]))
    return True


async def restore_upload_records(_: Bot) -> None:
    """恢复重启前尚未完成的上传、核验和自动重传任务。"""
    restored_queue = 0
    restored_verifications = 0
    now = datetime.now().astimezone()
    for gid, record in list(download_records.items()):
        items = _migrate_legacy_upload_items(gid, record)
        if not items:
            continue
        for item in items:
            item_id = str(item.get("id") or "")
            if not item_id:
                item_id = _upload_item_id(
                    gid,
                    str(item.get("group_id") or ""),
                    str(item.get("local_path") or ""),
                )
                item["id"] = item_id
            status = str(item.get("status") or "")
            if status == DownloadStatus.UPLOAD_QUEUED.value:
                _enqueue_upload_item(gid, item_id)
                restored_queue += 1
            elif status == DownloadStatus.UPLOADING.value:
                if (
                    str(item.get("delivery_mode"))
                    in {
                        MediaDeliveryMode.VIDEO_MESSAGE.value,
                        MediaDeliveryMode.VIDEO_COMPRESS.value,
                    }
                ):
                    item["status"] = DownloadStatus.UPLOAD_QUEUED.value
                    _enqueue_upload_item(gid, item_id)
                    restored_queue += 1
                    continue
                item["status"] = DownloadStatus.UPLOAD_VERIFYING.value
                last_attempt = _parse_record_time(item.get("last_attempt_at"))
                run_at = (
                    last_attempt
                    + timedelta(seconds=int(config.rss_upload_verify_delay))
                    if last_attempt
                    else now
                )
                _schedule_upload_verification(gid, item, max(run_at, now))
                restored_verifications += 1
            elif status == DownloadStatus.UPLOAD_VERIFYING.value:
                run_at = _parse_record_time(item.get("next_verify_at")) or now
                _schedule_upload_verification(gid, item, max(run_at, now))
                restored_verifications += 1
            elif (
                status == DownloadStatus.UPLOAD_FAILED.value
                and _int_value(item.get("retry_count"))
                < int(config.rss_upload_max_retries)
            ):
                item["status"] = DownloadStatus.UPLOAD_QUEUED.value
                _enqueue_upload_item(gid, item_id)
                restored_queue += 1
        _save_upload_record(gid, record)
        if str(record.get("status")) == DownloadStatus.UPLOAD_COMPLETE.value:
            info = record.get("download_status")
            if isinstance(info, dict):
                schedule_file_cleanup(gid, info)
    if restored_queue or restored_verifications:
        logger.info(
            f"已恢复群文件任务：上传队列 {restored_queue} 个，"
            f"等待核验 {restored_verifications} 个"
        )


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


async def cleanup_download_files(
    gid: str,
    download_dir: Path,
    paths: List[Path],
) -> None:
    """删除一个已完成任务的文件，并移除空的子目录。"""
    for path in paths:
        current_path = path.resolve()
        if current_path == download_dir or download_dir not in current_path.parents:
            logger.warning(f"跳过已离开下载目录的清理路径：{current_path}")
            continue
        try:
            current_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"自动清理下载文件失败[{current_path}]：{exc}")

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

    await _remove_download(gid, "complete")
    _remove_download_record(gid)
    logger.info(f"aria2 任务[{gid}]的下载文件已自动清理")


def schedule_file_cleanup(gid: str, status: Dict[str, Any]) -> None:
    """按照配置为已完成任务安排一次文件清理。"""
    delay = int(config.aria2_file_cleanup_delay)
    if delay <= 0:
        return

    download_dir, paths = _cleanup_paths(status)
    if not paths:
        logger.warning(f"aria2 任务[{gid}]没有可安全清理的文件路径")
        return
    scheduler.add_job(
        func=cleanup_download_files,
        trigger="date",
        run_date=datetime.now().astimezone() + timedelta(seconds=delay),
        args=(gid, download_dir, paths),
        id=f"rss-file-cleanup-{gid}",
        misfire_grace_time=300,
        replace_existing=True,
    )


async def delete_download_files(
    gid: str, group_id: Optional[str] = None
) -> tuple[int, List[Path]]:
    """Delete files belonging to one aria2 task and clear its tracking records."""
    task_info = download_tasks.get(gid)
    if not task_info and (stored_record := download_records.get(gid)):
        task_info = dict(stored_record)
    stored_status = task_info.get("download_status") if task_info else None
    info = stored_status if isinstance(stored_status, dict) else await get_status(gid)
    download_dir, paths = _cleanup_paths(info)
    if not paths:
        raise Aria2Error("该任务没有可安全删除的文件路径")

    cleanup_job_id = f"rss-file-cleanup-{gid}"
    if scheduler.get_job(cleanup_job_id):
        scheduler.remove_job(cleanup_job_id)
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
        group_ids = {
            str(value) for value in retained_info.get("group_ids", [])
        }
        if group_id:
            group_ids.add(group_id)
        retained_info["group_ids"] = sorted(group_ids)
        download_tasks[gid] = retained_info
        _save_download_record(gid, retained_info)
    else:
        _remove_download_record(gid)
        _clear_download_tracking(gid)
    return deleted_count, failed_paths


async def delete_messages(bot: Bot, msg_ids: List[Dict[str, Any]]) -> None:
    for msg_id in msg_ids:
        try:
            await bot.delete_msg(message_id=msg_id["message_id"])
        except Exception as exc:
            logger.debug(f"撤回下载进度消息失败：{exc}")


async def _recall_progress_messages(
    bot: Bot, msg_ids: List[Dict[str, Any]], delay: int
) -> None:
    await asyncio.sleep(delay)
    await delete_messages(bot, msg_ids)


def schedule_progress_recall(bot: Bot, msg_ids: List[Dict[str, Any]]) -> None:
    delay = int(config.down_status_msg_recall_delay)
    if delay <= 0 or not msg_ids:
        return
    task = asyncio.create_task(_recall_progress_messages(bot, msg_ids, delay))
    progress_recall_tasks.add(task)
    task.add_done_callback(progress_recall_tasks.discard)


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
            await _follow_metadata_download(
                bot, gid, str(followed_by[0]), task_info
            )
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

    is_seeding = (
        status == "active" and str(info.get("seeder", "")).lower() == "true"
    )
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

        schedule_file_cleanup(gid, info)
        _clear_download_tracking(gid)
        return

    await delete_messages(bot, task_info["downing_tips_msg_id"])
    if status in {"active", "waiting", "paused"}:
        progress_messages = await send_download_progress(
            bot, gid, info, name, group_ids
        )
        task_info["downing_tips_msg_id"] = progress_messages
        schedule_progress_recall(bot, progress_messages)


def schedule_status_check(
    bot: Bot, gid: str, group_ids: List[str], name: str
) -> None:
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
            await _prepare_manual_download(
                bot, gid, info, group_ids, name, task_info
            )
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


def is_torrent_link(link: Dict[str, Any]) -> bool:
    """Return whether an RSS link points to a magnet or torrent file."""
    href = str(link.get("href", ""))
    content_type = str(link.get("type", "")).lower()
    path = unquote(urlsplit(href).path).lower()
    return (
        href.lower().startswith("magnet:?")
        or content_type == "application/x-bittorrent"
        or path.endswith(".torrent")
    )


async def download_torrents(
    rss: Rss, item: Dict[str, Any], proxy: Optional[str]
) -> List[Dict[str, str]]:
    """Submit all torrent links in one RSS entry to the download backend."""
    bot = await get_bot()
    if bot is None:
        raise ValueError("没有可用的 Bot，无法创建下载任务")

    group_ids = (
        _whitelisted_group_ids(rss.group_id) if rss.is_open_upload_group else []
    )
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
