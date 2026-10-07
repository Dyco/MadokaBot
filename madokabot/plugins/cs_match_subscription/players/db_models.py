"""CS 玩家绑定在项目数据库中的持久化模型。"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data


class FiveEBinding(data.Model):
    """5E玩家绑定。"""

    __tablename__ = "madoka_cs_5e_binding"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("madoka_user_profile.user_id"), primary_key=True
    )
    player_name: Mapped[str] = mapped_column(String, nullable=False)
    domain: Mapped[str] = mapped_column(String, default="", nullable=False)
    uuid: Mapped[str] = mapped_column(String, default="", nullable=False)
    avatar_url: Mapped[str] = mapped_column(String, default="", nullable=False)
