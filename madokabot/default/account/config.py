"""账号默认资源与用户卡片模板配置。"""

from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel


class AccountConfig(BaseModel):
    """新账号的初始立绘配置。"""

    initial_chara: str = "樋口円香_SSR_通常服【アイドルロード】.png"  # 初始立绘


config = get_plugin_config(AccountConfig)
HTML_FILE_PATH = Path(__file__).parent / "templates" / "daily_sign.html"
