"""数据库基础设施，不导入具体业务模型。"""

from nonebot_plugin_datastore.db import get_engine

from .base import data


async def init_database() -> None:
    """为已加载模块注册的模型创建缺失数据表。"""
    async with get_engine().begin() as connection:
        await connection.run_sync(data.Model.metadata.create_all)
