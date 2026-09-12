from pydantic import BaseModel


class Config(BaseModel):
    steam_api_key: str
    steam_request_interval: int = 60  # seconds
    steam_broadcast_type: str = "part"  # all, part, none
    steam_disable_broadcast_on_startup: bool = False
    steam_command_priority: int = 10
    steam_query_use_proxy: bool = True  # 主动查询使用全局代理
    steam_monitor_use_proxy: bool = False  # 定时在线状态监控使用全局代理
    steam_query_cooldown: int = 600  # 主动资料查询冷却秒数
