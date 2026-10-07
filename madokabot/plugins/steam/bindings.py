"""Steam 绑定与群订阅的数据库操作。"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from madokabot.core.db import create_session
from madokabot.core.user.service import ensure_user_profile

from .db_models import SteamBinding, SteamGroupSubscription
from .monitor_state import mark_subscription_changed


def _as_binding(
    binding: SteamBinding, subscription: SteamGroupSubscription
) -> dict[str, Any]:
    """把全局账号与群设置合并为查询结果。"""
    return {
        "user_id": binding.user_id,
        "steam_id": binding.steam_id,
        "nickname": subscription.nickname,
        "enabled": subscription.enabled,
    }


async def get_global_binding(user_id: str) -> str | None:
    """读取 QQ 用户的全局 Steam ID。"""
    async with create_session() as session:
        binding = await session.get(SteamBinding, str(user_id))
        return binding.steam_id if binding else None


async def _ensure_global_binding(
    session: AsyncSession, user_id: str, steam_id: str | None, qq_nickname: str
) -> tuple[SteamBinding, bool]:
    """Steam全局绑定检查方法。"""
    binding = await session.get(SteamBinding, user_id)
    created = binding is None
    if binding is None:
        if steam_id is None:
            raise ValueError("尚未绑定 Steam，请先提供 Steam ID。")
        owner = await session.scalar(
            select(SteamBinding.user_id).where(SteamBinding.steam_id == steam_id)
        )
        if owner is not None:
            raise ValueError(f"该 Steam ID 已由 QQ 用户 {owner} 绑定。")
        await ensure_user_profile(session, user_id, qq_nickname)
        binding = SteamBinding(user_id=user_id, steam_id=steam_id)
        session.add(binding)
    else:
        if steam_id is not None and steam_id != binding.steam_id:
            raise ValueError("已绑定其他 Steam ID；请先解绑后重新绑定。")
        await ensure_user_profile(session, user_id, qq_nickname)
    return binding, created


async def bind_global_user(
    user_id: str, steam_id: str | None, qq_nickname: str = ""
) -> tuple[str, bool]:
    """Steam全局绑定方法。"""
    async with create_session() as session:
        binding, created = await _ensure_global_binding(
            session, str(user_id), steam_id, qq_nickname
        )
        resolved_steam_id = binding.steam_id
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("绑定冲突，请检查 Steam ID 是否已被他人使用。") from exc
        return resolved_steam_id, created


async def bind_user(
    group_id: str, user_id: str, steam_id: str | None, qq_nickname: str = ""
) -> tuple[str, bool]:
    """在同一事务中创建全局绑定并加入或恢复当前群订阅。"""
    group_id, user_id = str(group_id), str(user_id)
    async with create_session() as session:
        binding, created = await _ensure_global_binding(
            session, user_id, steam_id, qq_nickname
        )
        resolved_steam_id = binding.steam_id
        try:
            subscription = await session.get(
                SteamGroupSubscription, (group_id, user_id)
            )
            if subscription is None:
                session.add(
                    SteamGroupSubscription(group_id=group_id, user_id=user_id)
                )
            else:
                subscription.enabled = True
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("绑定冲突，请检查 Steam ID 是否已被他人使用。") from exc
        mark_subscription_changed(group_id, user_id)
        return resolved_steam_id, created


async def unbind_user(user_id: str) -> bool:
    """在同一事务中删除全局绑定和该用户的所有群订阅。"""
    user_id = str(user_id)
    async with create_session() as session:
        binding = await session.get(SteamBinding, user_id)
        if binding is None:
            return False
        group_ids = (
            await session.scalars(
                select(SteamGroupSubscription.group_id).where(
                    SteamGroupSubscription.user_id == user_id
                )
            )
        ).all()
        await session.execute(
            delete(SteamGroupSubscription).where(
                SteamGroupSubscription.user_id == user_id
            )
        )
        await session.delete(binding)
        await session.commit()
        for group_id in group_ids:
            mark_subscription_changed(group_id, user_id)
        return True


async def hide_user(group_id: str, user_id: str) -> bool:
    """只关闭指定群订阅的自动播报。"""
    async with create_session() as session:
        subscription = await session.get(
            SteamGroupSubscription, (str(group_id), str(user_id))
        )
        if subscription is None:
            return False
        subscription.enabled = False
        await session.commit()
        mark_subscription_changed(group_id, user_id)
        return True


async def online_user(group_id: str, user_id: str) -> bool:
    """只开启指定群订阅的自动播报。"""
    async with create_session() as session:
        subscription = await session.get(
            SteamGroupSubscription, (str(group_id), str(user_id))
        )
        if subscription is None:
            return False
        subscription.enabled = True
        await session.commit()
        mark_subscription_changed(group_id, user_id)
        return True


async def set_group_nickname(
    group_id: str, user_id: str, nickname: str | None
) -> bool:
    """只修改当前群的 Steam 备注。"""
    async with create_session() as session:
        subscription = await session.get(
            SteamGroupSubscription, (str(group_id), str(user_id))
        )
        if subscription is None:
            return False
        subscription.nickname = nickname[:64] if nickname is not None else None
        await session.commit()
        return True


async def get_group_binding(
    group_id: str, user_id: str
) -> dict[str, Any] | None:
    """群Steam绑定查询方法。"""
    async with create_session() as session:
        row = (
            await session.execute(
                select(SteamBinding, SteamGroupSubscription)
                .join(
                    SteamGroupSubscription,
                    SteamGroupSubscription.user_id == SteamBinding.user_id,
                )
                .where(
                    SteamGroupSubscription.group_id == str(group_id),
                    SteamGroupSubscription.user_id == str(user_id),
                )
            )
        ).first()
        return _as_binding(*row) if row else None


async def list_group_bindings(group_id: str) -> list[dict[str, Any]]:
    """读取当前群全部订阅。"""
    async with create_session() as session:
        rows = (
            await session.execute(
                select(SteamBinding, SteamGroupSubscription)
                .join(
                    SteamGroupSubscription,
                    SteamGroupSubscription.user_id == SteamBinding.user_id,
                )
                .where(SteamGroupSubscription.group_id == str(group_id))
                .order_by(SteamGroupSubscription.user_id)
            )
        ).all()
        return [_as_binding(*row) for row in rows]


async def list_active_bindings_by_group() -> dict[str, list[dict[str, Any]]]:
    """一次查询所有开启推送的群订阅并关联全局绑定。"""
    async with create_session() as session:
        rows = (
            await session.execute(
                select(SteamBinding, SteamGroupSubscription)
                .join(
                    SteamGroupSubscription,
                    SteamGroupSubscription.user_id == SteamBinding.user_id,
                )
                .where(SteamGroupSubscription.enabled.is_(True))
            )
        ).all()
    result: dict[str, list[dict[str, Any]]] = {}
    for binding, subscription in rows:
        result.setdefault(subscription.group_id, []).append(
            _as_binding(binding, subscription)
        )
    return result
