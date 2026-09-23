import random
from pathlib import Path

from nonebot.adapters.onebot.v11 import MessageSegment

from ..resources import ResourceFolder, ResourceType, get_files


def resource_to_segment(res_type: ResourceType, file_path: Path) -> MessageSegment:
    """将本地资源转换为 OneBot 消息段。"""
    resolved_path = file_path.resolve()
    if res_type == ResourceType.AUDIO:
        return MessageSegment.record(file=resolved_path.as_uri())
    if res_type == ResourceType.IMAGE:
        return MessageSegment.image(file=resolved_path.as_uri())
    return MessageSegment.text(str(resolved_path))


def get_random_resource_segment(
    res_type: ResourceType, plugin: ResourceFolder
) -> MessageSegment:
    """随机选取目录内的资源，缺失时返回文字提示。"""
    files = get_files(res_type, plugin)
    if not files:
        return MessageSegment.text(f"缺少资源: {res_type.value}/{plugin.value}")
    return resource_to_segment(res_type, random.choice(files))
