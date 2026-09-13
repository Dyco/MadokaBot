"""Resolver 使用的接口地址与请求头常量。"""

from .bilibili import BILIBILI_HEADER
from .common import (
    COMMON_HEADER,
    GENERAL_REQ_LINK,
    PLUGIN_NAME,
    RESOLVE_SHUTDOWN_LIST_NAME,
)
from .kugou import KUGOU_TEMP_API
from .netease import NETEASE_API_CN, NETEASE_TEMP_API, NETEASE_TEMP_API_FALLBACK
from .tiktok import (
    DOUYIN_VIDEO,
    DY_TOUTIAO_INFO,
    TIKTOK_VIDEO,
    URL_TYPE_CODE_DICT,
)
from .weibo import WEIBO_SINGLE_INFO
from .xiaohongshu import XHS_REQ_LINK

__all__ = [
    "BILIBILI_HEADER",
    "COMMON_HEADER",
    "DOUYIN_VIDEO",
    "DY_TOUTIAO_INFO",
    "GENERAL_REQ_LINK",
    "KUGOU_TEMP_API",
    "NETEASE_API_CN",
    "NETEASE_TEMP_API",
    "NETEASE_TEMP_API_FALLBACK",
    "PLUGIN_NAME",
    "RESOLVE_SHUTDOWN_LIST_NAME",
    "TIKTOK_VIDEO",
    "URL_TYPE_CODE_DICT",
    "WEIBO_SINGLE_INFO",
    "XHS_REQ_LINK",
]
