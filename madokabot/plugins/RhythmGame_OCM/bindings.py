"""舞萌与中二好友码的独立全局数据库绑定。"""

from typing import Literal

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db import create_session
from madokabot.core.db.base import data


class MaimaiBinding(data.Model):
    """按 QQ 保存舞萌绑定，群聊和私聊共用。"""

    __tablename__ = "madoka_rhythmgame_maimai_binding"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    friend_code: Mapped[str] = mapped_column(String(15), nullable=False)


class ChunithmBinding(data.Model):
    """按 QQ 保存中二绑定，与舞萌账号独立。"""

    __tablename__ = "madoka_rhythmgame_chunithm_binding"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    friend_code: Mapped[str] = mapped_column(String(15), nullable=False)


Game = Literal["maimai", "chunithm"]
_binding_models = {"maimai": MaimaiBinding, "chunithm": ChunithmBinding}


async def get_binding(user_id: str, *, game: Game = "maimai") -> str | None:
    """读取所选游戏的好友码，保持现有舞萌调用方式。"""
    async with create_session() as session:
        binding = await session.get(_binding_models[game], user_id)
        return binding.friend_code if binding else None


async def bind_player(user_id: str, friend_code: int, *, game: Game = "maimai") -> None:
    """将已通过 LXNS 验证的好友码保存到所选游戏的绑定表。"""
    async with create_session() as session:
        await session.merge(_binding_models[game](user_id=user_id, friend_code=str(friend_code)))
        await session.commit()


async def unbind_player(user_id: str, *, game: Game = "maimai") -> bool:
    """仅删除机器人内所选游戏的好友码绑定。"""
    async with create_session() as session:
        binding = await session.get(_binding_models[game], user_id)
        if binding is None:
            return False
        await session.delete(binding)
        await session.commit()
        return True
