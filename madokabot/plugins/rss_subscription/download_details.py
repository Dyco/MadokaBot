"""RSS 下载任务状态的名称和文件摘要。"""

from pathlib import Path
from typing import Any, Dict

from .download_validation import _int_value, _total_download_size
from .utils import convert_size


def _task_name(status: Dict[str, Any], fallback: str) -> str:
    """从 aria2 状态提取任务名称。"""
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
    """生成下载任务的名称、大小和 GID 摘要。"""
    name = _task_name(status, fallback)
    total = _total_download_size(status)
    size = convert_size(total) if total else "获取中"
    return f"{name}\n文件大小：{size}\nGID：{gid}"


def _display_file_path(status: Dict[str, Any], file_info: Dict[str, Any]) -> str:
    """将文件路径显示为下载目录下的相对路径。"""
    raw_path = str(file_info.get("path") or "未知文件")
    download_dir = status.get("dir")
    if download_dir:
        try:
            return str(Path(raw_path).relative_to(Path(str(download_dir))))
        except ValueError:
            pass
    return Path(raw_path).name or raw_path


def _compact_file_size(file_info: Dict[str, Any]) -> str:
    """生成文件列表中的紧凑大小文本。"""
    size = convert_size(_int_value(file_info.get("length")))
    return size.replace(" ", "").lower()
