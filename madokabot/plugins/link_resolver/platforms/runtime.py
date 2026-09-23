"""链接解析平台共用的运行时配置。"""

from nonebot import get_plugin_config

from ..config import Config

global_config = get_plugin_config(Config)
GLOBAL_NICKNAME = global_config.global_prefix_nickname.strip()
VIDEO_DURATION_MAXIMUM = global_config.video_duration_maximum
BILI_SESSDATA = global_config.bili_sessdata.strip()

resolver_proxy = str(global_config.resolver_proxy or "").strip() or None
if resolver_proxy and "://" not in resolver_proxy:
    resolver_proxy = f"http://{resolver_proxy}"


def _platform_proxy(enabled: bool) -> str | None:
    """按平台开关选择统一代理地址。"""
    return resolver_proxy if enabled else None


BILIBILI_PROXY = _platform_proxy(global_config.bilibili_use_proxy)
DOUYIN_PROXY = _platform_proxy(global_config.douyin_use_proxy)
TIKTOK_PROXY = _platform_proxy(global_config.tiktok_use_proxy)
ACFUN_PROXY = _platform_proxy(global_config.acfun_use_proxy)
TWITTER_PROXY = _platform_proxy(global_config.twitter_use_proxy)
XIAOHONGSHU_PROXY = _platform_proxy(global_config.xiaohongshu_use_proxy)
YOUTUBE_PROXY = _platform_proxy(global_config.youtube_use_proxy)
NETEASE_PROXY = _platform_proxy(global_config.netease_use_proxy)
KUGOU_PROXY = _platform_proxy(global_config.kugou_use_proxy)
WEIBO_PROXY = _platform_proxy(global_config.weibo_use_proxy)
