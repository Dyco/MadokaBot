"""RSS 下载文件的选择与大小校验。"""

from typing import Any, Dict, List, Optional, Sequence

from madokabot.core.messaging.media import media_delivery

from .aria2_client import Aria2Error
from .config import config
from .utils import convert_size


class DownloadSizeLimitExceeded(Aria2Error):
    """下载任务中存在超过配置大小上限的文件。"""


def _int_value(value: Any) -> int:
    """将外部数值转换为非负整数。"""
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _is_selected(file_info: Dict[str, Any]) -> bool:
    """判断文件是否被 aria2 选中。"""
    selected = file_info.get("selected", "true")
    if isinstance(selected, bool):
        return selected
    return str(selected).lower() != "false"


def _status_files(
    status: Dict[str, Any], selected_only: bool = False
) -> List[Dict[str, Any]]:
    """提取 aria2 状态中的文件列表。"""
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
    """找出超过视频处理上限的文件。"""
    return [
        file_info
        for file_info in _status_files(status, selected_only=True)
        if media_delivery.is_video(str(file_info.get("path") or ""))
        and _int_value(file_info.get("length")) > media_delivery.video_compress_limit
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
