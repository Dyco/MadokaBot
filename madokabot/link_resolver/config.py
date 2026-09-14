from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    """链接解析器配置。

    `resolver_proxy` 为空时视为不走代理
    """

    model_config = ConfigDict(extra="ignore")

    xhs_ck: str = "" # 小红书 Cookie
    douyin_ck: str = "" # 抖音 Cookie
    is_oversea: bool = False # 是否使用海外网络环境
    bili_sessdata: str = "" # Bilibili 登录凭据
    r_global_nickname: str = "" # 全局昵称
    resolver_proxy: str | None = None # 解析器代理地址，为空时复用通用代理
    video_duration_maximum: int = 300 # 视频时长上限，单位秒
    global_resolve_controller: str = "" # 全局解析器开关控制
