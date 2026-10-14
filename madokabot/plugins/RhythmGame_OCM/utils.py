"""音游图片与时间展示的公共工具。"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def image_uri(path: Path | None) -> str:
    """将存在的本地素材转换为浏览器可用的文件地址。"""
    return path.resolve().as_uri() if path and path.is_file() else ""


def display_time(value: str) -> str:
    """将接口提供的 UTC 同步时间转换为上海时间。"""
    if not value:
        return "未提供"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        ZoneInfo("Asia/Shanghai")
    ).strftime("%Y-%m-%d %H:%M")
