from nonebot import get_plugin_config
from pydantic import BaseModel
from typing import List


class CommonConfig(BaseModel):
    register_keywords: List[str] = ["注册", "register"]
    initial_chara: str = "樋口円香_SSR_通常服【アイドルロード】.png"
    shop_page_size: int = 12
    shop_session_timeout: float = 60.0


config = get_plugin_config(CommonConfig)
