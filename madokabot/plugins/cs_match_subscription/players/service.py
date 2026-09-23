"""玩家绑定与战绩查询的业务编排。"""

from __future__ import annotations

from typing import Any

from .constants import SUPPORTED_PLATFORM_TEXT
from .five_e import fetch_five_e_stats, resolve_five_e_identity, resolve_five_e_uuid
from .http import create_client
from .models import PlayerBinding, PlayerStatsError
from .perfect_world import fetch_pw_stats, resolve_pw_identity
from .platforms import normalize_platform, platform_label
from .storage import binding_store
from .values import parse_pw_steam_id


async def bind_player(user_id: str, platform: str, nickname: str) -> PlayerBinding:
    """解析并保存 5E/PW 昵称绑定。"""
    normalized = normalize_platform(platform)
    name = nickname.strip()
    if normalized is None or normalized not in {"5e", "pw"}:
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")
    if not name:
        raise PlayerStatsError("缺少玩家昵称")

    if normalized == "5e":
        binding = await resolve_five_e_identity(name)
    else:
        binding = await resolve_pw_identity(name)
    binding.user_id = str(user_id)
    return binding_store.save(binding)


def unbind_player(user_id: str, platform: str) -> PlayerBinding | None:
    """解除当前 QQ 用户指定平台的绑定。"""
    normalized = normalize_platform(platform)
    if normalized not in {"5e", "pw"}:
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")
    return binding_store.remove(str(user_id), normalized)


def get_binding(user_id: str, platform: str) -> PlayerBinding | None:
    """读取当前用户已经绑定的平台账号。"""
    normalized = normalize_platform(platform)
    return binding_store.get(str(user_id), normalized) if normalized else None


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
        binding = get_binding(user_id, normalized)
    if binding is None:
        raise PlayerStatsError(
            f"未绑定{platform_label(normalized)}账号，请先使用 CS bind {normalized} <昵称>"
        )

    if normalized == "5e" and not binding.uuid:
        async with create_client() as client:
            binding.uuid = await resolve_five_e_uuid(client, binding.domain)
    if normalized == "pw" and not binding.uuid:
        resolved = await resolve_pw_identity(binding.player_name)
        binding.domain = resolved.domain
        binding.uuid = resolved.uuid
        binding.player_name = resolved.player_name
        binding.avatar_url = binding.avatar_url or resolved.avatar_url

    if binding.user_id:
        binding_store.save(binding)
    return (
        await fetch_five_e_stats(binding)
        if normalized == "5e"
        else await fetch_pw_stats(binding)
    )
