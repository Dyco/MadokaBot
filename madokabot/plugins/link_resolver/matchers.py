"""Resolver 各平台链接 matcher。"""

import re

from nonebot import get_driver, on_type
from nonebot.adapters.onebot.v11 import Event, GroupMessageEvent
from nonebot.rule import Rule

from .commands import resolver_group_rule
from .messages import get_resolver_message

# 自动监听跳过命令消息，空起始符不影响普通分享链接。
COMMAND_STARTS = tuple(start for start in get_driver().config.command_start if start)


def _resolver_rule(pattern: str) -> Rule:
    """仅匹配普通群消息中的分享链接，排除带命令起始符的消息。"""
    compiled = re.compile(pattern, re.IGNORECASE)

    async def contains_resolver_link(event: Event) -> bool:
        """识别普通分享消息，防止管理指令触发平台解析。"""
        if not isinstance(event, GroupMessageEvent):
            return False
        message = get_resolver_message(event)
        return (
            not message.startswith(COMMAND_STARTS)
            and compiled.search(message) is not None
        )

    return Rule(resolver_group_rule, contains_resolver_link)


def _on_group_resolver(pattern: str, **kwargs):
    """群解析器注册方法。"""
    return on_type(
        GroupMessageEvent,
        rule=_resolver_rule(pattern),
        block=True,
        **kwargs,
    )


def _url_pattern(hosts: str) -> str:
    """限定完整域名及非空路径，避免普通域名文字和相似域名触发解析。"""
    return rf"https?://(?:{hosts})/[A-Za-z\d._?%&+\-=/#@]+"


BILIBILI_PATTERN = (
    _url_pattern(r"(?:(?:space|www|live|t)\.)?bilibili\.com|b23\.tv|bili2233\.cn")
    + r"|^BV[1-9a-zA-Z]{10}$"
)
DOUYIN_PATTERN = _url_pattern(r"v\.douyin\.com|(?:www\.)?(?:iesdouyin|douyin)\.com")
TIKTOK_PATTERN = _url_pattern(r"(?:www|vt|vm)\.tiktok\.com")
ACFUN_PATTERN = _url_pattern(r"(?:(?:www|m)\.)?acfun\.cn")
TWITTER_PATTERN = _url_pattern(r"(?:(?:www|mobile)\.)?(?:x|twitter)\.com")
XIAOHONGSHU_PATTERN = _url_pattern(r"xhslink\.(?:com|cn)|(?:www\.)?xiaohongshu\.com")
YOUTUBE_PATTERN = (
    r"(?<![\w./-])(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be)/"
    r"[A-Za-z\d._?%&+\-=/#@]+"
)
NETEASE_PATTERN = _url_pattern(r"music\.163\.com|163cn\.tv")
WEIBO_PATTERN = (
    r"https?://(?:(?:www\.)?weibo\.com|m\.weibo\.cn|mapp\.api\.weibo\.cn)/"
    r"[A-Za-z\d._?%&+\-=/#@:]+"
)
KUGOU_PATTERN = _url_pattern(r"(?:[A-Za-z0-9-]+\.)*kugou\.com")


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
