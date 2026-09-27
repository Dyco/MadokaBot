"""机器人连接后补齐群资料，并缓存新群头像。"""

from io import BytesIO
from uuid import uuid4

import httpx
from PIL import Image
from nonebot import get_driver, logger
from nonebot.adapters import Bot as BaseBot
from nonebot.adapters.onebot.v11 import Bot

from madokabot.core.group.settings import group_settings
from madokabot.core.resources import ResourceFolder, ResourceType, assets


GROUP_INFO_NAME = "group_info"
GROUP_AVATAR_DIR = assets.get_dir(ResourceType.IMAGE, ResourceFolder.GROUP)


async def ensure_group_profile(
    bot: Bot, group_id: int, group_name: str | None = None
) -> None:
    """补齐群配置、群名称和头像，保留群内已有的插件数据。"""
    saved = group_settings.get(group_id, GROUP_INFO_NAME)
    profile = dict(saved) if isinstance(saved, dict) else {}

    name = group_name.strip() if isinstance(group_name, str) else ""
    if not name and not profile.get("group_name"):
        try:
            info = await bot.get_group_info(group_id=group_id, no_cache=True)
            name = str(info.get("group_name") or "").strip()
        except Exception:
            logger.exception(f"获取群 {group_id} 名称失败")

    if name and profile.get("group_name") != name:
        profile["group_name"] = name
    if saved is None or profile != saved:
        group_settings.set(group_id, GROUP_INFO_NAME, profile)

    avatar_path = GROUP_AVATAR_DIR / f"{group_id}.png"
    if avatar_path.is_file():
        return

    avatar_url = f"https://p.qlogo.cn/gh/{group_id}/{group_id}/640"
    temporary_path = GROUP_AVATAR_DIR / f".{group_id}.{uuid4().hex}.tmp"
    try:
        async with httpx.AsyncClient(
            timeout=10.0, follow_redirects=True, trust_env=False
        ) as client:
            response = await client.get(avatar_url)
            response.raise_for_status()
        with Image.open(BytesIO(response.content)) as avatar:
            avatar.save(temporary_path, format="PNG")
        temporary_path.replace(avatar_path)
    except Exception:
        logger.exception(f"保存群 {group_id} 头像失败")
    finally:
        temporary_path.unlink(missing_ok=True)


async def sync_joined_groups(bot: Bot) -> None:
    """机器人连接后扫描已加入的群，补齐缺失资料。"""
    try:
        groups = await bot.get_group_list()
    except Exception:
        logger.exception(f"获取机器人 {bot.self_id} 的群列表失败")
        return

    for group in groups:
        try:
            group_id = int(group["group_id"])
            await ensure_group_profile(bot, group_id, group.get("group_name"))
        except Exception:
            logger.exception(f"初始化群资料失败：{group!r}")


@get_driver().on_bot_connect
async def sync_groups_on_connect(bot: BaseBot) -> None:
    """仅在 OneBot 机器人连接时扫描群列表。"""
    if isinstance(bot, Bot):
        await sync_joined_groups(bot)
