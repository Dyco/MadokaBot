from nonebot import get_plugin_config
from pydantic import BaseModel


class CommonConfig(BaseModel):
    initial_chara: str = "樋口円香_SSR_通常服【アイドルロード】.png" # 初始角色
    shop_page_size: int = 12 # 商店每页显示数量
    shop_session_timeout: float = 60.0 # 商店会话超时时间，单位秒
    auto_leave_group_min_members: int = 5 # 群人数少于此值时自动退群
    auto_leave_group_max_members: int = 200 # 群人数大于此值时自动退群
    file_cleanup_retention_hours: float = 12.0 # 通用缓存文件保留时间
    file_cleanup_interval_minutes: float = 60.0 # 通用文件清理间隔
    response_emoji_id: str = "424" # 普通响应使用的续标识表情
    status_response_emoji_id: str = "86" # 状态响应开始使用的爱心表情
    status_complete_emoji_id: str = "478" # 状态响应完成使用的对的表情


config = get_plugin_config(CommonConfig)
