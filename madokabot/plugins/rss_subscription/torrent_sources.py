"""RSS 种子源文件的保存、关联与清理。"""

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlsplit

from nonebot.log import logger

from madokabot.core.messaging.media import media_delivery

from .aria2_client import Aria2Error
from .config import config
from .download_details import _task_name


def _torrent_file_name(url: str, fallback: str) -> str:
    """从种子链接生成安全的文件名。"""
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
    """保存下载时获取的原始种子文件。"""
    raw_dir = status.get("dir") or config.aria2_download_path
    if not raw_dir:
        raise Aria2Error("aria2 未返回下载目录，无法保留 torrent 文件")
    file_name = _torrent_file_name(url, gid)
    download_dir = Path(str(raw_dir)).expanduser().resolve()
    rpc_saved_path = download_dir / f"{hashlib.sha1(content).hexdigest()}.torrent"
    if rpc_saved_path.is_file():
        return str(rpc_saved_path), file_name
    torrent_dir = download_dir / ".madokabot-torrents" / gid
    torrent_path = torrent_dir / file_name
    try:
        torrent_dir.mkdir(parents=True, exist_ok=True)
        torrent_path.write_bytes(content)
    except OSError as exc:
        raise Aria2Error(f"保存 torrent 文件失败：{exc}") from exc
    return str(torrent_path), file_name


def _find_saved_magnet_torrent(status: Dict[str, Any]) -> Optional[Path]:
    """查找 aria2 保存的磁链种子文件。"""
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
    """将种子源文件附加到任务上传状态。"""
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
    """删除本插件保存的种子源文件。"""
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


def is_torrent_link(link: Dict[str, Any]) -> bool:
    """判断 RSS 链接是否为磁链或种子文件。"""
    href = str(link.get("href", ""))
    content_type = str(link.get("type", "")).lower()
    path = unquote(urlsplit(href).path).lower()
    return (
        href.lower().startswith("magnet:?")
        or content_type == "application/x-bittorrent"
        or path.endswith(".torrent")
    )
