"""Resolver 各平台链接 matcher。"""

from nonebot import on_regex

from .commands import resolver_group_rule

bilibili_matcher = on_regex(
    r"(bilibili\.com|b23\.tv|bili2233\.cn|BV[0-9a-zA-Z]{10})",
    rule=resolver_group_rule,
    priority=1,
)
douyin_matcher = on_regex(
    r"(v\.douyin\.com|iesdouyin\.com|douyin\.com\/(video|note))",
    rule=resolver_group_rule,
    priority=1,
    block=True,
)
tiktok_matcher = on_regex(
    r"(www\.tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com)",
    rule=resolver_group_rule,
    priority=1,
)
acfun_matcher = on_regex(r"(acfun\.cn)", rule=resolver_group_rule)
twitter_matcher = on_regex(r"(x\.com)", rule=resolver_group_rule, priority=1)
xiaohongshu_matcher = on_regex(
    r"(xhslink\.com|xiaohongshu\.com)",
    rule=resolver_group_rule,
    priority=1,
)
youtube_matcher = on_regex(
    r"(youtube\.com|youtu\.be)",
    rule=resolver_group_rule,
    priority=1,
)
netease_matcher = on_regex(
    r"(music\.163\.com|163cn\.tv)",
    rule=resolver_group_rule,
)
weibo_matcher = on_regex(
    r"(weibo\.com|m\.weibo\.cn)",
    rule=resolver_group_rule,
)
kugou_matcher = on_regex(r"(kugou\.com)", rule=resolver_group_rule)
