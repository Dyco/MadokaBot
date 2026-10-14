"""中二节奏曲目、曲绘和玩家装饰资源管理。"""

import asyncio
import threading
import time

import httpx
from nonebot import logger

from madokabot.core.resources import ResourceFolder, ResourceType, assets

from ..config import config
from ..update_resources import (
    download_image,
    read_catalog,
    refresh_catalog,
    update_resources,
)
from .models import Best50, Player

IMAGE_ROOT = assets.get_dir(ResourceType.IMAGE, ResourceFolder.CHUNITHM)
FONT_ROOT = assets.get_dir(ResourceType.FONT, ResourceFolder.CHUNITHM)
DATA_ROOT = assets.get_dir(ResourceType.JSON, ResourceFolder.CHUNITHM)
_resource_lock = threading.Lock()
_update_lock = asyncio.Lock()


def _prepare(player: Player, bests: Best50) -> dict:
    """补齐成绩卡所需曲绘与玩家装饰，下载失败时继续使用本地素材。"""
    with _resource_lock, httpx.Client(
        timeout=config.rhythmgame_request_timeout, follow_redirects=True
    ) as client:
        catalog = read_catalog(DATA_ROOT)
        if time.time() - catalog.get("updated_at", 0) > 86400:
            try:
                catalog = refresh_catalog(client, DATA_ROOT, game="chunithm")
            except (httpx.HTTPError, ValueError):
                logger.warning("中二曲目快照刷新失败，使用已有数据")
        requests = {("jacket", score.id) for score in bests.bests + bests.new_bests + bests.selections}
        for kind, collection in (
            ("character", player.character), ("icon", player.map_icon), ("plate", player.name_plate),
        ):
            if collection:
                requests.add((kind, collection.id))
        if player.trophy and player.trophy.color == "image":
            requests.add(("trophy", player.trophy.id))
        for kind, resource_id in sorted(requests):
            try:
                download_image(
                    client, IMAGE_ROOT, kind, resource_id, config.rhythmgame_asset_interval,
                    game="chunithm",
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    logger.warning("中二资源服务限流，停止本次补齐")
                    break
                logger.warning(f"中二资源下载失败：{kind}/{resource_id}")
            except (httpx.RequestError, OSError, ValueError):
                logger.warning(f"中二资源暂不可用：{kind}/{resource_id}")
        return catalog


async def prepare_resources(player: Player, bests: Best50) -> dict:
    """在线程中准备本次查分资源，全量更新期间直接使用本地快照。"""
    if _update_lock.locked():
        return read_catalog(DATA_ROOT)
    return await asyncio.to_thread(_prepare, player, bests)


def _update_all() -> dict[str, int]:
    """在中二资源锁内刷新曲目并增量补齐曲绘。"""
    with _resource_lock:
        return update_resources(
            IMAGE_ROOT, DATA_ROOT, timeout=config.rhythmgame_request_timeout,
            interval=config.rhythmgame_asset_interval, game="chunithm",
        )


async def update_all_resources() -> dict[str, int]:
    """执行中二资源增量更新，拒绝重复启动同一任务。"""
    if _update_lock.locked():
        raise ValueError("中二资源正在更新，请等待本次更新完成。")
    async with _update_lock:
        return await asyncio.to_thread(_update_all)
