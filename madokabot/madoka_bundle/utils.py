import random
import time
from pathlib import Path

from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment

from .config import assets
from .constants import ResType, SubFolder


def get_latency_ms(event: MessageEvent) -> float:
    """计算从收到消息到当前时刻的延迟（毫秒）。"""
    latency = (time.time() - event.time) * 1000
    return max(0.0, latency)


def get_files(res_type: ResType, plugin: SubFolder) -> list[Path]:
    """获取目录下所有非隐藏文件"""
    directory = assets.get_dir(res_type, plugin)
    return [
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    ]


def get_file(res_type: ResType, plugin: SubFolder, name: str) -> Path | None:
    """获取特定文件"""
    path = assets.get_dir(res_type, plugin) / name
    return path if path.is_file() else None


def to_segment(res_type: ResType, file_path: Path) -> MessageSegment:
    resolved_path = file_path.resolve()

    if res_type == ResType.AUDIO:
        return MessageSegment.record(file=resolved_path.as_uri())
    if res_type == ResType.IMAGE:
        return MessageSegment.image(file=resolved_path.as_uri())
    return MessageSegment.text(str(resolved_path))


def get_random_res(res_type: ResType, plugin: SubFolder) -> MessageSegment:
    """一键随机发送"""
    files = get_files(res_type, plugin)
    if not files:
        return MessageSegment.text(f"缺少资源: {res_type.value}/{plugin.value}")
    return to_segment(res_type, random.choice(files))


def get_indexed_files(
    res_type: ResType,
    plugin: SubFolder,
    prefix: str = "image",
) -> dict[str, Path]:
    """
    按文件名排序，为目录中的资源生成连续运行时编号。

    例如：image01 -> xxx.png
    """
    files = sorted(get_files(res_type, plugin))
    return {f"{prefix}{index:02d}": path for index, path in enumerate(files, start=1)}
