"""5E 玩家绑定的公共数据库操作。"""

from __future__ import annotations

from madokabot.core.db import create_session
from madokabot.core.user.service import ensure_user_profile

from .db_models import FiveEBinding
from .models import PlayerBinding


def _as_binding(row: FiveEBinding) -> PlayerBinding:
    """把数据库记录转为战绩查询使用的玩家对象。"""
    return PlayerBinding(
        user_id=row.user_id,
        platform="5e",
        player_name=row.player_name,
        domain=row.domain,
        uuid=row.uuid,
        avatar_url=row.avatar_url,
    )


async def save_5e_binding(
    binding: PlayerBinding, qq_nickname: str = ""
) -> PlayerBinding:
    """在项目数据库中创建或更新用户的 5E 绑定。"""
    async with create_session() as session:
        await ensure_user_profile(session, binding.user_id, qq_nickname)
        row = await session.get(FiveEBinding, binding.user_id)
        if row is None:
            row = FiveEBinding(user_id=binding.user_id)
            session.add(row)
        row.player_name = binding.player_name
        row.domain = binding.domain
        row.uuid = binding.uuid
        row.avatar_url = binding.avatar_url
        await session.commit()
    return binding


async def get_5e_binding(user_id: str) -> PlayerBinding | None:
    """读取用户的 5E 绑定。"""
    async with create_session() as session:
        row = await session.get(FiveEBinding, str(user_id))
        return _as_binding(row) if row else None


async def remove_5e_binding(user_id: str) -> PlayerBinding | None:
    """5E绑定删除方法。"""
    async with create_session() as session:
        row = await session.get(FiveEBinding, str(user_id))
        if row is None:
            return None
        binding = _as_binding(row)
        await session.delete(row)
        await session.commit()
        return binding
