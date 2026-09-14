from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    """链接解析器配置。

    `resolver_proxy` 为空时视为不走代理
    """

    model_config = ConfigDict(extra="ignore")

    xhs_ck: str = ""
    douyin_ck: str = ""
    is_oversea: bool = False
    bili_sessdata: str = ""
    r_global_nickname: str = ""
    resolver_proxy: str | None = None
    video_duration_maximum: int = 480
    global_resolve_controller: str = ""
