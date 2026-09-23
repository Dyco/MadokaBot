"""商店列表与交互配置。"""

from nonebot import get_plugin_config
from pydantic import BaseModel


class ShopConfig(BaseModel):
    """商店分页与回复会话设置。"""

    shop_page_size: int = 12  # 每页商品数量
    shop_session_timeout: float = 60.0  # 翻页会话超时秒数


config = get_plugin_config(ShopConfig)
