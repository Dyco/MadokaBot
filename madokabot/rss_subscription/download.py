"""aria2 RPC 下载及下载完成后的群文件上传。"""

import asyncio
import base64
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

from ..madoka_bundle.plugins.common import is_group_whitelisted
from .config import config
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
    UPLOADING = "uploading"
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
    "followedBy",
]

# 任务状态保存在进程内，和原下载后端保持一致。
download_tasks: Dict[str, Dict[str, Any]] = {}
progress_recall_tasks: set[asyncio.Task[None]] = set()

SelectionHandler = Callable[
    [Bot, str, List[Dict[str, Any]], List[str], str], Awaitable[None]
]


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
    options: Dict[str, str] = {"seed-time": "0"}
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
    manual_selection: bool = False,
) -> str:
    """把磁力链接或 torrent 地址提交给 aria2，返回 GID。"""
    options = _download_options(proxy)
    if url.lower().startswith("magnet:?"):
        if manual_selection:
            # 元数据本身仍需下载；pause-metadata 只暂停随后创建的 BT 任务。
            options["pause-metadata"] = "true"
        result = await _rpc_call("aria2.addUri", [[url], options])
    else:
        if manual_selection:
            options["pause"] = "true"
        content = await _fetch_torrent(url, proxy)
        torrent = base64.b64encode(content).decode("ascii")
        result = await _rpc_call("aria2.addTorrent", [torrent, [], options])
    if not isinstance(result, str) or not result:
        raise Aria2Error(f"aria2 未返回有效 GID：{result!r}")
    return result


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
        if _int_value(file_info.get("length")) > max_size
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


async def upload_files_to_groups(
    bot: Bot,
    group_ids: List[str],
    files: List[Dict[str, Any]],
    name: str,
    gid: str,
) -> Dict[str, List[Dict[str, Any]]]:
    failed_files: Dict[str, List[Dict[str, Any]]] = {}
    for group_id in _whitelisted_group_ids(group_ids):
        for file_info in files:
            raw_path = file_info.get("path")
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if not path.is_file():
                failed_files.setdefault(group_id, []).append(file_info)
                msg = (
                    f"❌ {name}\nGID：{gid}\n找不到待上传文件：{path}\n"
                    f"文件记录将保留，可使用 /RSS 重试 {gid} 再次检查并上传。"
                )
                await send_msg(bot, msg, [group_id])
                logger.error(msg)
                continue

            file_name = str(file_info.get("name") or path.name)
            await send_msg(
                bot,
                f"{name}\nGID：{gid}\n开始上传到群：{group_id}",
                [group_id],
            )
            try:
                await bot.call_api(
                    "upload_group_file",
                    group_id=group_id,
                    file=str(path),
                    name=file_name,
                )
            except ActionFailed as exc:
                failed_files.setdefault(group_id, []).append(file_info)
                msg = (
                    f"❌ {name}\nGID：{gid}\n上传到群：{group_id}失败。\n"
                    f"原因：{exc}\n"
                    f"文件将暂时保留，可使用 /RSS 重试 {gid} 再次上传。"
                )
                try:
                    await send_msg(bot, msg, [group_id])
                except Exception:
                    logger.exception(f"发送上传失败提醒到群[{group_id}]时出错")
                logger.exception(msg)
            except (NetworkError, TimeoutError) as exc:
                failed_files.setdefault(group_id, []).append(file_info)
                logger.warning(f"上传到群[{group_id}]网络异常：{exc}")
                msg = (
                    f"⚠️ {name}\nGID：{gid}\n上传到群：{group_id}调用超时，"
                    "无法确认服务端是否已经接收文件。\n"
                    "请先检查群文件；如果没有出现，再使用 "
                    f"/RSS 重试 {gid}。\n文件将暂时保留，不会自动清理。"
                )
                try:
                    await send_msg(bot, msg, [group_id])
                except Exception:
                    logger.exception(f"发送上传超时提醒到群[{group_id}]时出错")
    return failed_files


async def retry_upload_to_group(bot: Bot, gid: str, group_id: str) -> bool:
    """Retry failed files for one group and schedule cleanup after full success."""
    task_info = download_tasks.get(gid)
    if task_info and task_info.get("status") == DownloadStatus.UPLOAD_FAILED:
        failures = task_info.get("upload_failures")
        if not isinstance(failures, dict):
            raise Aria2Error("没有找到该任务的上传失败记录")
        files = failures.get(group_id)
        if not isinstance(files, list) or not files:
            raise Aria2Error("该任务在当前群没有待重试的文件")
        info = task_info.get("download_status")
        if not isinstance(info, dict):
            raise Aria2Error("该任务缺少下载状态，无法重试上传")
        name = str(task_info.get("name") or _task_name(info, "重试上传"))
    else:
        info = await get_status(gid)
        if str(info.get("status", "")) != "complete":
            raise Aria2Error("该 aria2 任务尚未下载完成，无法重试上传")
        files = [
            file_info
            for file_info in _status_files(info, selected_only=True)
            if file_info.get("path")
        ]
        if not files:
            raise Aria2Error("该任务没有可上传的文件")
        name = _task_name(info, "重试上传")
        failures = {}
        task_info = {
            "status": DownloadStatus.UPLOAD_FAILED,
            "name": name,
            "download_status": info,
            "upload_failures": failures,
        }
        download_tasks[gid] = task_info

    retried_failures = await upload_files_to_groups(
        bot=bot,
        group_ids=[group_id],
        files=files,
        name=name,
        gid=gid,
    )
    if retried_failures:
        failures[group_id] = retried_failures[group_id]
        task_info["upload_failures"] = failures
        return False

    failures.pop(group_id, None)
    if failures:
        task_info["upload_failures"] = failures
        return True

    schedule_file_cleanup(gid, info)
    _clear_download_tracking(gid)
    return True


def _cleanup_paths(status: Dict[str, Any]) -> tuple[Path, List[Path]]:
    """提取位于 aria2 任务下载目录内的文件路径。"""
    raw_dir = status.get("dir")
    if not raw_dir:
        return Path(), []

    download_dir = Path(str(raw_dir)).expanduser().resolve()
    if config.aria2_download_path:
        configured_dir = Path(config.aria2_download_path).expanduser().resolve()
        if download_dir != configured_dir and configured_dir not in download_dir.parents:
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


async def delete_download_files(gid: str) -> tuple[int, List[Path]]:
    """Delete files belonging to one aria2 task and clear its tracking records."""
    task_info = download_tasks.get(gid)
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
        download_tasks[gid] = retained_info
    else:
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
        await _remove_download(gid, str(info.get("status", "")))
        _clear_download_tracking(gid)
        raise DownloadSizeLimitExceeded(size_limit_message)

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
    if size_limit_message := _size_limit_message(updated_info):
        await _remove_download(gid, str(updated_info.get("status", "")))
        _clear_download_tracking(gid)
        raise DownloadSizeLimitExceeded(size_limit_message)

    task_info = download_tasks.get(gid) or {
        "start_time": arrow.now(),
        "downing_tips_msg_id": [],
        "manual_selection": True,
    }
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
        await _remove_download(child_gid, str(child_info.get("status", "")))
        _clear_download_tracking(child_gid)
        _clear_download_tracking(metadata_gid)
        await _remove_download(metadata_gid, "complete")
        await send_msg(
            bot,
            f"{name}\nGID：{child_gid}\n❌ 已停止下载：\n{size_limit_message}",
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
        await _remove_download(gid, status)
        msg = f"{name}\nGID：{gid}\n❌ 已停止下载：\n{size_limit_message}"
        await send_msg(bot, msg, group_ids)
        _clear_download_tracking(gid)
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
        start_time = task_info.get("start_time", arrow.now())
        all_time = arrow.now() - start_time
        task_info["status"] = DownloadStatus.UPLOADING
        await send_msg(
            bot,
            f"👏 {name}\nGID：{gid}\n下载完成！耗时：{str(all_time).split('.', 2)[0]}",
            group_ids,
        )
        upload_failures = await upload_files_to_groups(
            bot, group_ids, files, name, gid
        )
        if upload_failures:
            task_info["status"] = DownloadStatus.UPLOAD_FAILED
            task_info["name"] = name
            task_info["download_status"] = info
            task_info["upload_failures"] = upload_failures
            _stop_status_check(gid)
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
    try:
        async with asyncio.timeout(config.aria2_acquire_timeout):
            await aria2_version()
            gid = await add_download(
                url=url,
                proxy=proxy,
                manual_selection=manual_selection,
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
    download_tasks[gid] = task_info

    try:
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
                await _remove_download(gid, str(info.get("status", "")))
                _clear_download_tracking(gid)
                raise DownloadSizeLimitExceeded(size_limit_message)
            _track_download(bot, gid, group_ids, task_name, task_info)
            await send_msg(
                bot,
                f"👏 订阅：{name}\n{task_summary}\n下载任务添加成功！",
                group_ids,
            )
    except Aria2Error as exc:
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
