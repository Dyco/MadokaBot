"""跨插件的过期文件清理器。

各插件只需注册自己的专用缓存目录；清理器不跟踪业务任务，
仅根据文件的最后修改时间清理过期文件。
"""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from nonebot import logger, require

from madokabot.core.config import config

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler  # noqa: E402


@dataclass(frozen=True)
class CleanupTarget:
    name: str
    path: Path
    max_age_seconds: int


_cleanup_targets: dict[str, CleanupTarget] = {}


def register_cleanup_path(
    name: str,
    path: str | Path,
    *,
    max_age_seconds: int | None = None,
) -> Path:
    """注册需要定期清理的专用目录。"""
    target_path = Path(path).expanduser().resolve()
    if target_path == Path(target_path.anchor) or target_path == Path.home():
        raise ValueError(f"拒绝注册过于宽泛的清理目录：{target_path}")

    retention = (
        int(max_age_seconds)
        if max_age_seconds is not None
        else int(config.file_cleanup_retention_hours * 3600)
    )
    if retention <= 0:
        raise ValueError("文件保留时间必须大于 0")

    _cleanup_targets[name] = CleanupTarget(name, target_path, retention)
    logger.debug(
        f"已注册过期文件清理目录[{name}]：{target_path}，"
        f"保留 {retention / 3600:g} 小时"
    )
    return target_path


def _cleanup_target(target: CleanupTarget, now: float) -> tuple[int, int]:
    if not target.path.is_dir():
        return 0, 0

    cutoff = now - target.max_age_seconds
    removed_files = 0
    failed_files = 0
    directories: list[tuple[Path, float]] = []

    try:
        entries = list(target.path.rglob("*"))
    except OSError as exc:
        logger.warning(f"扫描清理目录失败[{target.name}][{target.path}]：{exc}")
        return 0, 1

    for entry in entries:
        try:
            stat = entry.lstat()
            if entry.is_dir() and not entry.is_symlink():
                directories.append((entry, stat.st_mtime))
                continue
            if stat.st_mtime > cutoff:
                continue
            entry.unlink(missing_ok=True)
            removed_files += 1
        except OSError as exc:
            failed_files += 1
            logger.warning(f"清理过期文件失败[{target.name}][{entry}]：{exc}")

    for directory, modified_at in sorted(
        directories,
        key=lambda item: len(item[0].parts),
        reverse=True,
    ):
        if modified_at > cutoff:
            continue
        try:
            directory.rmdir()
        except OSError:
            pass

    return removed_files, failed_files


async def cleanup_expired_files() -> None:
    """扫描所有已注册目录，删除过期文件。"""
    now = time.time()
    for target in tuple(_cleanup_targets.values()):
        removed, failed = await asyncio.to_thread(_cleanup_target, target, now)
        if removed or failed:
            logger.info(
                f"过期文件清理完成[{target.name}]："
                f"删除 {removed} 个，失败 {failed} 个"
            )


_cleanup_interval_seconds = max(
    60,
    int(config.file_cleanup_interval_minutes * 60),
)
scheduler.add_job(
    cleanup_expired_files,
    trigger="interval",
    seconds=_cleanup_interval_seconds,
    id="madoka-common-file-cleanup",
    max_instances=1,
    coalesce=True,
    replace_existing=True,
)
