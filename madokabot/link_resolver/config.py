from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    """链接解析器配置。

    `resolver_proxy` 为空时视为不走代理
    """

    model_config = ConfigDict(extra="ignore")

    xhs_ck: str = "" # 小红书 Cookie
    douyin_ck: str = "" # 抖音 Cookie
    bili_sessdata: str = "" # Bilibili 登录凭据
    global_prefix_nickname: str = "" # 全局昵称
    resolver_proxy: str | None = None # 解析器代理地址，为空时直连
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
    video_duration_maximum: int = 300 # 可获取时长的平台上限，单位秒；超限时仅跳过视频下载
    global_resolve_controller: str = "" # 全局解析器开关控制

    video_message_max_mb: float = 95 # 不超过此大小的视频直接发送，单位 MiB
    video_compress_max_mb: float = 300 # 超过直发上限且不超过此大小的视频压缩发送，单位 MiB
    video_compress_target_mb: float = 90 # FFmpeg压缩后的视频目标大小，单位 MiB

    group_file_max_mb: float = 1024 # 允许上传为群文件的大小上限，单位 MiB
    group_file_upload_timeout: int = 3000 # 群文件上传 API 的等待超时，单位秒
