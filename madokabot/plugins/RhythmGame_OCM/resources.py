"""通过公共资源目录准备舞萌 B50 所需素材。"""

import asyncio
import threading
import time

import httpx
from nonebot import logger

from madokabot.core.resources import ResourceFolder, ResourceType, assets

from .config import config
from .models import Best50, Player
from .update_resources import (
    download_image,
    read_catalog,
    refresh_catalog,
    update_resources,
)

IMAGE_ROOT = assets.get_dir(ResourceType.IMAGE, ResourceFolder.MAIMAI)
FONT_ROOT = assets.get_dir(ResourceType.FONT, ResourceFolder.MAIMAI)
DATA_ROOT = assets.get_dir(ResourceType.JSON, ResourceFolder.MAIMAI)
_resource_lock = threading.Lock()
_update_lock = asyncio.Lock()


def _prepare(player: Player, bests: Best50) -> dict:
    """串行补齐本次 B50 的素材，失败时允许使用本地占位图。"""
    with _resource_lock, httpx.Client(
        timeout=config.rhythmgame_request_timeout, follow_redirects=True
    ) as client:
        catalog = read_catalog(DATA_ROOT)
        if time.time() - catalog.get("updated_at", 0) > 86400:
            try:
                catalog = refresh_catalog(client, DATA_ROOT)
            except (httpx.HTTPError, ValueError):
                logger.warning("舞萌曲目快照刷新失败，本次使用已有数据")
        requests = {("jacket", score.id) for score in bests.standard + bests.dx}
        if player.icon:
            requests.add(("icon", player.icon.id))
        if player.name_plate:
            requests.add(("plate", player.name_plate.id))
        for kind, resource_id in sorted(requests):
            try:
                download_image(
                    client, IMAGE_ROOT, kind, resource_id, config.rhythmgame_asset_interval
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    logger.warning("舞萌资源服务限流，停止本次补齐")
                    break
                logger.warning(f"舞萌资源下载失败：{kind}/{resource_id}")
            except (httpx.RequestError, OSError, ValueError):
                logger.warning(f"舞萌资源暂不可用：{kind}/{resource_id}")
        return catalog


async def prepare_resources(player: Player, bests: Best50) -> dict:
    """在线程中准备素材，避免图片处理和下载阻塞机器人事件循环。"""
    if _update_lock.locked():
        return read_catalog(DATA_ROOT)
    return await asyncio.to_thread(_prepare, player, bests)


def _update_all() -> dict[str, int]:
    """与查分素材准备共用锁，防止同一文件并发写入。"""
    with _resource_lock:
        return update_resources(
            IMAGE_ROOT, DATA_ROOT,
            timeout=config.rhythmgame_request_timeout,
            interval=config.rhythmgame_asset_interval,
        )


async def update_all_resources() -> dict[str, int]:
    """执行管理员触发的完整增量更新，重复请求直接提示。"""
    if _update_lock.locked():
        raise ValueError("舞萌资源正在更新，请等待本次更新完成。")
    async with _update_lock:
        return await asyncio.to_thread(_update_all)
