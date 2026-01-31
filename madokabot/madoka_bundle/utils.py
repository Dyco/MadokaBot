import time
import os
import random
from pathlib import Path
from typing import Dict, List, Optional

from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from .constants import ResType, SubFolder
from .config import assets

# 获取消息延迟时间
def get_latency_ms(event: MessageEvent) -> float:
    """
    计算从收到消息到当前时刻的毫秒级延迟
    """
    latency = (time.time() - event.time) * 1000
    return max(0.0, latency) 

# 文件类
def get_files(res_type: ResType, plugin: SubFolder) -> List[Path]:
    """获取目录下所有非隐藏文件"""
    path = assets.get_dir(res_type, plugin)
    return [path / f for f in os.listdir(path) if os.path.isfile(path / f) and not f.startswith(".")]

def get_file(res_type: ResType, plugin: SubFolder, name: str) -> Optional[Path]:
    """获取特定文件"""
    path = assets.get_dir(res_type, plugin) / name
    return path if path.exists() else None

# 处理文件
def to_segment(res_type: ResType, file_path: Path) -> MessageSegment:
    abs_p = file_path.resolve()
    abs_str = str(abs_p)
    
    file_uri = f"file://{abs_str}" 

    if res_type == ResType.AUDIO:
        return MessageSegment.record(file=file_uri)
    if res_type == ResType.IMAGE:
        return MessageSegment.image(file=file_uri)
    return MessageSegment.text(abs_str)

# 随机文件
def get_random_res(res_type: ResType, plugin: SubFolder) -> MessageSegment:
    """一键随机发送"""
    files = get_files(res_type, plugin)
    if not files:
        return MessageSegment.text(f"缺少资源: {res_type.value}/{plugin.value}")
    return to_segment(res_type, random.choice(files))

def get_indexed_files(res_type: ResType, plugin: SubFolder, prefix: str = "image") -> Dict[str, Path]:
    """
    自动为目录下的文件生成稳定编号映射
    例如：image01 -> xxx.png
    """
    files = sorted(get_files(res_type, plugin))
    return {
        f"{prefix}{i:02d}": path
        for i, path in enumerate(files, start=1)
    }