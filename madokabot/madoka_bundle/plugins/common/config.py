from nonebot import get_plugin_config
from pydantic import BaseModel, Field, PositiveFloat, PositiveInt


class CommonConfig(BaseModel):
    register_keywords: list[str] = Field(default_factory=lambda: ["注册", "register"])
    initial_chara: str = "樋口円香_SSR_通常服【アイドルロード】.png"
    shop_page_size: PositiveInt = 12
    shop_session_timeout: PositiveFloat = 60.0


config = get_plugin_config(CommonConfig)
