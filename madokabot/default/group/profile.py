"""群资料补齐模块。"""

import asyncio
from io import BytesIO
from uuid import uuid4

import httpx
from PIL import Image
from nonebot import logger
from nonebot.adapters import Bot as BaseBot, Event as BaseEvent
from nonebot.adapters.onebot.v11 import Bot
from nonebot.message import event_preprocessor

from madokabot.core.group.settings import group_settings
from madokabot.core.resources import ResourceFolder, ResourceType, assets


GROUP_INFO_NAME = "group_info"
GROUP_AVATAR_DIR = assets.get_dir(ResourceType.IMAGE, ResourceFolder.GROUP)
_profile_tasks: dict[int, asyncio.Task[None]] = {}


async def ensure_group_profile(
    bot: Bot, group_id: int, group_name: str | None = None
) -> None:
    """群资料补齐方法。"""
    saved = group_settings.get(group_id, GROUP_INFO_NAME)
    profile = dict(saved) if isinstance(saved, dict) else {}

    name = group_name.strip() if isinstance(group_name, str) else ""
    saved_name = profile.get("group_name")
    if not name and not (isinstance(saved_name, str) and saved_name.strip()):
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


async def _fill_group_profile(bot: Bot, group_id: int) -> None:
    """群资料后台补齐方法。"""
    try:
        await ensure_group_profile(bot, group_id)
    except Exception:
        logger.exception(f"补齐群 {group_id} 资料失败")
    finally:
        _profile_tasks.pop(group_id, None)


def schedule_group_profile(bot: Bot, group_id: int) -> None:
    """群资料任务调度方法。"""
    if group_id in _profile_tasks:
        return

    saved = group_settings.get(group_id, GROUP_INFO_NAME)
    name = saved.get("group_name") if isinstance(saved, dict) else None
    avatar_path = GROUP_AVATAR_DIR / f"{group_id}.png"
    if isinstance(name, str) and name.strip() and avatar_path.is_file():
        return

    _profile_tasks[group_id] = asyncio.create_task(
        _fill_group_profile(bot, group_id), name=f"group-profile-{group_id}"
    )


@event_preprocessor
async def _collect_event_group_profile(bot: BaseBot, event: BaseEvent) -> None:
    """群资料事件处理方法。"""
    if not isinstance(bot, Bot) or event.get_type() not in {"message", "notice"}:
        return
    group_id = getattr(event, "group_id", None)
    if isinstance(group_id, int) and group_id > 0:
        schedule_group_profile(bot, group_id)
