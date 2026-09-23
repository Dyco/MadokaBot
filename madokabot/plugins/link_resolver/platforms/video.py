"""各平台共用的视频时长判断和并发下载。"""

import asyncio

from nonebot import logger

from .runtime import VIDEO_DURATION_MAXIMUM


def _duration_seconds(value: object, *, milliseconds: bool = False) -> float | None:
    """将接口返回的视频时长转换为秒。"""
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if milliseconds:
        duration /= 1000
    return duration if duration > 0 else None


def _find_video_duration_seconds(value: object) -> float | None:
    """从嵌套的视频元数据中查找时长。"""
    if isinstance(value, dict):
        for key in (
            "duration_ms",
            "durationMs",
            "duration_millis",
            "durationMillis",
        ):
            duration = _duration_seconds(value.get(key), milliseconds=True)
            if duration is not None:
                return duration
        for key in ("duration_seconds", "durationSeconds", "duration"):
            duration = _duration_seconds(value.get(key))
            if duration is not None:
                return duration
        for nested in value.values():
            duration = _find_video_duration_seconds(nested)
            if duration is not None:
                return duration
    elif isinstance(value, list):
        for nested in value:
            duration = _find_video_duration_seconds(nested)
            if duration is not None:
                return duration
    return None


def _skip_video_for_duration(
    platform: str,
    duration_seconds: float | None,
) -> bool:
    """判断视频是否超时，并在超时时跳过视频下载。"""
    if duration_seconds is None or duration_seconds <= VIDEO_DURATION_MAXIMUM:
        return False
    logger.warning(
        f"[{platform}] 视频时长超过限制，已跳过视频下载和发送："
        f"当前 {duration_seconds / 60:.1f} 分钟，"
        f"上限 {VIDEO_DURATION_MAXIMUM / 60:g} 分钟"
    )
    return True


async def _gather_downloads(*coroutines):
    """任一并发下载失败时，先取消并回收其余下载任务。"""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
