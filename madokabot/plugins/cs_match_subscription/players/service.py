"""玩家绑定与战绩查询的业务编排。"""

from __future__ import annotations

from typing import Any

from madokabot.plugins.steam.bindings import (
    bind_global_user,
    get_global_binding,
    unbind_user,
)

from .constants import SUPPORTED_PLATFORM_TEXT
from .five_e import fetch_five_e_stats, resolve_five_e_identity
from .models import PlayerBinding, PlayerStatsError
from .perfect_world import fetch_pw_stats
from .platforms import normalize_platform, platform_label
from .storage import get_5e_binding, remove_5e_binding, save_5e_binding
from .values import parse_pw_steam_id


async def bind_player(
    user_id: str, platform: str, player: str, qq_nickname: str = ""
) -> PlayerBinding:
    """保存 5E 绑定，或共用 Steam 的全局账号绑定。"""
    normalized = normalize_platform(platform)
    identifier = player.strip()
    if normalized is None or normalized not in {"5e", "pw"}:
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")
    if normalized == "5e":
        if not identifier:
            raise PlayerStatsError("缺少玩家昵称")
        binding = await resolve_five_e_identity(identifier)
        binding.user_id = str(user_id)
        return await save_5e_binding(binding, qq_nickname)
    requested = str(parse_pw_steam_id(identifier)) if identifier else None
    try:
        steam_id, _ = await bind_global_user(user_id, requested, qq_nickname)
    except ValueError as exc:
        raise PlayerStatsError(str(exc)) from exc
    return PlayerBinding(
        user_id=str(user_id), platform="pw", player_name=steam_id, uuid=steam_id
    )


async def unbind_player(user_id: str, platform: str) -> PlayerBinding | None:
    """5E 单独解绑；完美平台与 Steam 共用全局解绑。"""
    normalized = normalize_platform(platform)
    if normalized not in {"5e", "pw"}:
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")
    if normalized == "5e":
        return await remove_5e_binding(user_id)
    steam_id = await get_global_binding(user_id)
    if steam_id is None or not await unbind_user(user_id):
        return None
    return PlayerBinding(
        user_id=str(user_id), platform="pw", player_name=steam_id, uuid=steam_id
    )


async def get_binding(user_id: str, platform: str) -> PlayerBinding | None:
    """从公共数据库读取 5E 或共用 Steam 绑定。"""
    normalized = normalize_platform(platform)
    if normalized == "5e":
        return await get_5e_binding(user_id)
    if normalized == "pw":
        steam_id = await get_global_binding(user_id)
        if steam_id is not None:
            return PlayerBinding(
                user_id=str(user_id), platform="pw", player_name=steam_id, uuid=steam_id
            )
    return None


async def fetch_player_stats(
    user_id: str,
    platform: str,
    nickname: str = "",
) -> dict[str, Any]:
    """查询指定昵称；昵称为空时查询当前用户已经绑定的玩家。"""
    normalized = normalize_platform(platform)
    if normalized not in {"5e", "pw"}:
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")

    query = nickname.strip()
    if query:
        if normalized == "5e":
            binding = await resolve_five_e_identity(query)
        else:
            binding = PlayerBinding(
                user_id="",
                platform="pw",
                player_name=query,
                uuid=str(parse_pw_steam_id(query)),
            )
    else:
        binding = await get_binding(user_id, normalized)
    if binding is None:
        if normalized == "pw":
            raise PlayerStatsError(
                "未绑定 Steam/CS 共用账号，请使用 CS bind pw <Steam ID> 或 steam bind <Steam ID>"
            )
        raise PlayerStatsError("未绑定 5E 账号，请先使用 CS bind 5e <玩家昵称>")

    return (
        await fetch_five_e_stats(binding)
        if normalized == "5e"
        else await fetch_pw_stats(binding)
    )
