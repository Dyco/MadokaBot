"""商店及立绘持有记录。"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from madokabot.core.db.base import data


class UserInventory(data.Model):
    """按用户、资源分类与文件名保存持有数量。"""

    __tablename__ = "madoka_user_inventory"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_type: Mapped[str] = mapped_column("type", String(32), primary_key=True)
    content: Mapped[str] = mapped_column(String(32), primary_key=True)
    file_name: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
