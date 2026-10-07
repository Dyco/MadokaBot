"""数据库基础设施。"""

from nonebot_plugin_datastore import create_session
from nonebot_plugin_datastore.db import get_engine

from .base import data


async def init_database() -> None:
    """数据表创建方法。"""
    async with get_engine().begin() as connection:
        await connection.run_sync(data.Model.metadata.create_all)
