"""Steam 全局绑定及按群订阅关系。"""

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data


class SteamBinding(data.Model):
    """一个 QQ 用户对应一份全局 Steam 绑定。"""

    __tablename__ = "madoka_steam_binding"

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("madoka_user_profile.user_id"), primary_key=True
    )
    steam_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)


class SteamGroupSubscription(data.Model):
    """群内推送状态与备注；Steam ID 始终从全局绑定读取。"""

    __tablename__ = "madoka_steam_group_subscription"

    group_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("madoka_steam_binding.user_id"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
