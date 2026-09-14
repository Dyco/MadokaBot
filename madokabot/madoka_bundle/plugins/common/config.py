from nonebot import get_plugin_config
from pydantic import BaseModel


class CommonConfig(BaseModel):
    initial_chara: str = "樋口円香_SSR_通常服【アイドルロード】.png" # 初始角色
    shop_page_size: int = 12 # 商店每页显示数量
    shop_session_timeout: float = 60.0 # 商店会话超时时间，单位秒
    file_cleanup_retention_hours: float = 12.0 # 通用缓存文件保留时间
    file_cleanup_interval_minutes: float = 60.0 # 通用文件清理间隔


config = get_plugin_config(CommonConfig)
