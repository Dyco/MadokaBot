from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    """链接解析器配置。"""

    model_config = ConfigDict(extra="ignore")

    xhs_ck: str = ""
    douyin_ck: str = ""
    ytb_ck: str = ""
    bili_sessdata: str = ""
    global_prefix_nickname: str = ""
    resolver_proxy: str | None = None
    bilibili_use_proxy: bool = False
    douyin_use_proxy: bool = False
    tiktok_use_proxy: bool = False
    acfun_use_proxy: bool = False
    twitter_use_proxy: bool = False
    xiaohongshu_use_proxy: bool = False
    youtube_use_proxy: bool = False
    netease_use_proxy: bool = False
    kugou_use_proxy: bool = False
    weibo_use_proxy: bool = False
    video_duration_maximum: int = 300 # 单位：秒
    global_resolve_controller: str = ""

    video_message_max_mb: float = 95 # 单位：MiB
    video_compress_max_mb: float = 300 # 单位：MiB
    video_compress_target_mb: float = 90 # 单位：MiB

    group_file_max_mb: float = 1024 # 单位：MiB
    group_file_upload_timeout: int = 3000 # 单位：秒
