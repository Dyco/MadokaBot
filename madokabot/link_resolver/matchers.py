"""Resolver 各平台链接 matcher。"""

import re

from nonebot import on_regex
from nonebot.adapters.onebot.v11 import Event
from nonebot.rule import Rule

from .commands import resolver_group_rule
from .messages import get_resolver_message


def _resolver_rule(pattern: str) -> Rule:
    """仅使用非图片消息段判断是否包含可解析链接。"""
    compiled = re.compile(pattern)

    async def contains_resolver_link(event: Event) -> bool:
        return compiled.search(get_resolver_message(event)) is not None

    return Rule(resolver_group_rule, contains_resolver_link)


BILIBILI_PATTERN = r"(bilibili\.com|b23\.tv|bili2233\.cn|BV[0-9a-zA-Z]{10})"
DOUYIN_PATTERN = r"(v\.douyin\.com|iesdouyin\.com|douyin\.com\/(video|note))"
TIKTOK_PATTERN = r"(www\.tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)"
ACFUN_PATTERN = r"(acfun\.cn)"
TWITTER_PATTERN = r"((?:x|twitter)\.com)"
XIAOHONGSHU_PATTERN = r"(xhslink\.com|xiaohongshu\.com)"
YOUTUBE_PATTERN = r"(youtube\.com|youtu\.be)"
NETEASE_PATTERN = r"(music\.163\.com|163cn\.tv)"
WEIBO_PATTERN = r"(weibo\.com|m\.weibo\.cn)"
KUGOU_PATTERN = r"(kugou\.com)"


bilibili_matcher = on_regex(
    BILIBILI_PATTERN,
    rule=_resolver_rule(BILIBILI_PATTERN),
    priority=1,
)
douyin_matcher = on_regex(
    DOUYIN_PATTERN,
    rule=_resolver_rule(DOUYIN_PATTERN),
    priority=1,
    block=True,
)
tiktok_matcher = on_regex(
    TIKTOK_PATTERN,
    rule=_resolver_rule(TIKTOK_PATTERN),
    priority=1,
)
acfun_matcher = on_regex(ACFUN_PATTERN, rule=_resolver_rule(ACFUN_PATTERN))
twitter_matcher = on_regex(
    TWITTER_PATTERN,
    rule=_resolver_rule(TWITTER_PATTERN),
    priority=1,
)
xiaohongshu_matcher = on_regex(
    XIAOHONGSHU_PATTERN,
    rule=_resolver_rule(XIAOHONGSHU_PATTERN),
    priority=1,
)
youtube_matcher = on_regex(
    YOUTUBE_PATTERN,
    rule=_resolver_rule(YOUTUBE_PATTERN),
    priority=1,
)
netease_matcher = on_regex(
    NETEASE_PATTERN,
    rule=_resolver_rule(NETEASE_PATTERN),
)
weibo_matcher = on_regex(
    WEIBO_PATTERN,
    rule=_resolver_rule(WEIBO_PATTERN),
)
kugou_matcher = on_regex(KUGOU_PATTERN, rule=_resolver_rule(KUGOU_PATTERN))
