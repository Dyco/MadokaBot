"""Resolver 各平台链接 matcher。"""

import re

from nonebot import on_type
from nonebot.adapters.onebot.v11 import Event, GroupMessageEvent
from nonebot.rule import Rule

from .commands import resolver_group_rule
from .messages import get_resolver_message


def _resolver_rule(pattern: str) -> Rule:
    """仅使用非图片消息段判断是否包含可解析链接。"""
    compiled = re.compile(pattern)

    async def contains_resolver_link(event: Event) -> bool:
        if not isinstance(event, GroupMessageEvent):
            return False
        return compiled.search(get_resolver_message(event)) is not None

    return Rule(resolver_group_rule, contains_resolver_link)


def _on_group_resolver(pattern: str, **kwargs):
    """注册仅匹配群消息的平台 Resolver matcher。"""
    return on_type(
        GroupMessageEvent,
        rule=_resolver_rule(pattern),
        block=True,
        **kwargs,
    )


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


bilibili_matcher = _on_group_resolver(BILIBILI_PATTERN, priority=1)
douyin_matcher = _on_group_resolver(DOUYIN_PATTERN, priority=1)
tiktok_matcher = _on_group_resolver(TIKTOK_PATTERN, priority=1)
acfun_matcher = _on_group_resolver(ACFUN_PATTERN)
twitter_matcher = _on_group_resolver(TWITTER_PATTERN, priority=1)
xiaohongshu_matcher = _on_group_resolver(XIAOHONGSHU_PATTERN, priority=1)
youtube_matcher = _on_group_resolver(YOUTUBE_PATTERN, priority=1)
netease_matcher = _on_group_resolver(NETEASE_PATTERN)
weibo_matcher = _on_group_resolver(WEIBO_PATTERN)
kugou_matcher = _on_group_resolver(KUGOU_PATTERN)
