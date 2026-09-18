"""Resolver 主命令、访问控制与开关状态。"""

from __future__ import annotations

import re
from functools import wraps

from arclet.alconna import StrMulti
from nonebot import get_plugin_config, logger
from nonebot.adapters.onebot.v11 import (
    GROUP_ADMIN,
    GROUP_OWNER,
    Bot,
    Event,
    GroupMessageEvent,
)
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import (
    Alconna,
    Args,
    Arparma,
    CommandMeta,
    Match,
    Subcommand,
    on_alconna,
)

from ..madoka_bundle.plugins.common import is_group_whitelisted
from . import __plugin_meta__
from .config import Config
from .messages import get_target_id
from .state import (
    CONTENT_KEYS,
    RESOLVER_KEYS,
    current_resolver_key,
    current_resolver_target,
    is_resolver_enabled,
    load_comment_mode_map,
    save_comment_mode_map,
    save_resolver_control_map,
    set_all_content_enabled,
    set_all_resolvers_enabled,
    set_resolver_content_enabled,
    set_resolver_enabled,
    split_config_list,
)
from .status import render_resolver_status_card


config = get_plugin_config(Config)
disabled_resolvers = {
    item.casefold()
    for item in split_config_list(config.global_resolve_controller, ",")
}
comment_mode_map: dict = load_comment_mode_map()

HANDLER_RESOLVER_KEYS = {
    "bilibili": "bilibili",
    "dy": "douyin",
    "tiktok": "tiktok",
    "ac": "acfun",
    "twitter": "twitter",
    "xiaohongshu": "xiaohongshu",
    "youtube": "youtube",
    "netease": "netease",
    "kugou": "kugou",
    "wb": "weibo",
}
RESOLVER_ALIASES = {
    "b站": "bilibili",
    "bilibili": "bilibili",
    "bili": "bilibili",
    "哔哩哔哩": "bilibili",
    "dy": "douyin",
    "douyin": "douyin",
    "抖音": "douyin",
    "tiktok": "tiktok",
    "tk": "tiktok",
    "抖音国际版": "tiktok",
    "acfun": "acfun",
    "ac": "acfun",
    "a站": "acfun",
    "twitter": "twitter",
    "x": "twitter",
    "推特": "twitter",
    "小蓝鸟": "twitter",
    "xhs": "xiaohongshu",
    "xiaohongshu": "xiaohongshu",
    "小红书": "xiaohongshu",
    "youtube": "youtube",
    "ytb": "youtube",
    "yt": "youtube",
    "油管": "youtube",
    "网易云": "netease",
    "网易云音乐": "netease",
    "netease": "netease",
    "ncm": "netease",
    "酷狗": "kugou",
    "酷狗音乐": "kugou",
    "kugou": "kugou",
    "kg": "kugou",
    "微博": "weibo",
    "weibo": "weibo",
    "wb": "weibo",
}
CONTENT_ALIASES = {
    "图片": "image",
    "image": "image",
    "img": "image",
    "视频": "video",
    "video": "video",
    "评论": "comment",
    "comment": "comment",
    "comments": "comment",
}
CONTENT_LABELS = {
    "image": "图片",
    "video": "视频",
    "comment": "评论",
}
RESOLVER_LABELS = {
    "bilibili": "B站",
    "douyin": "抖音",
    "tiktok": "TikTok",
    "acfun": "ACFun",
    "twitter": "X",
    "xiaohongshu": "小红书",
    "youtube": "YouTube",
    "netease": "网易云",
    "kugou": "酷狗",
    "weibo": "微博",
}
OPEN_ACTIONS = {"打开"}
CLOSE_ACTIONS = {"关闭"}


def _resolver_key_for_handler(handler_name: str) -> str:
    """将处理器函数名转换为统一的平台标识。"""
    return HANDLER_RESOLVER_KEYS.get(handler_name, handler_name)


def _event_target_id(event: GroupMessageEvent) -> int:
    """获取当前群组的控制目标编号。"""
    return event.group_id


def _split_control_tokens(content: Match[str]) -> list[str]:
    """将主命令参数拆分为支持空格和逗号的控制项。"""
    value = content.result
    if isinstance(value, str):
        raw_value = value
    elif value is None:
        return []
    else:
        raw_value = " ".join(str(item) for item in value)
    return [
        item
        for item in re.split(r"[\s,，、]+", raw_value.strip())
        if item
    ]


def _is_control_command(tokens: list[str]) -> bool:
    """判断参数是否属于 Resolver 开关控制命令。"""
    if not tokens:
        return False
    first = tokens[0].casefold()
    return first in OPEN_ACTIONS or first in CLOSE_ACTIONS


def _control_scope_text(
    all_selected: bool,
    resolver_keys: set[str],
    content_keys: set[str],
) -> str:
    """生成开关操作的目标范围说明。"""
    if content_keys:
        target = (
            "全部平台"
            if all_selected or not resolver_keys
            else "、".join(
                RESOLVER_LABELS[key]
                for key in RESOLVER_KEYS
                if key in resolver_keys
            )
        )
        contents = "、".join(
            CONTENT_LABELS[key] for key in CONTENT_KEYS if key in content_keys
        )
        return f"{target}的{contents}内容"
    if all_selected:
        return "全部平台解析"
    return (
        "、".join(
            RESOLVER_LABELS[key]
            for key in RESOLVER_KEYS
            if key in resolver_keys
        )
        + "解析"
    )


async def _apply_control_command(
    event: GroupMessageEvent,
    tokens: list[str],
) -> None:
    """应用 Resolver 的全局、平台和内容类型开关。"""
    target_id = _event_target_id(event)

    enabled = tokens[0].casefold() in OPEN_ACTIONS
    parameters = tokens[1:]
    if not parameters:
        await resolver.finish("请指定要打开或关闭的平台、内容类型或“全部”。")

    resolver_keys: set[str] = set()
    content_keys: set[str] = set()
    all_selected = False
    unknown: list[str] = []
    for parameter in parameters:
        normalized = parameter.casefold()
        if normalized in {"all", "全部", "所有"}:
            all_selected = True
        elif normalized in RESOLVER_ALIASES:
            resolver_keys.add(RESOLVER_ALIASES[normalized])
        elif normalized in CONTENT_ALIASES:
            content_keys.add(CONTENT_ALIASES[normalized])
        else:
            unknown.append(parameter)

    if unknown:
        await resolver.finish(
            "无法识别控制参数："
            + "、".join(unknown)
            + "。可使用平台名称或“全部/图片/视频/评论”。"
        )

    if all_selected:
        resolver_keys.clear()
    if not all_selected and not resolver_keys and not content_keys:
        await resolver.finish("没有找到有效的解析控制参数。")

    if content_keys:
        for content_key in content_keys:
            if all_selected or not resolver_keys:
                set_all_content_enabled(target_id, content_key, enabled)
            else:
                for resolver_key in resolver_keys:
                    set_resolver_content_enabled(
                        target_id,
                        resolver_key,
                        content_key,
                        enabled,
                    )
    elif all_selected:
        set_all_resolvers_enabled(target_id, enabled)
    else:
        for resolver_key in resolver_keys:
            set_resolver_enabled(target_id, resolver_key, enabled)

    save_resolver_control_map()

    action_name = "打开" if enabled else "关闭"
    await resolver.finish(
        f"已{action_name}"
        f"{_control_scope_text(all_selected, resolver_keys, content_keys)}"
    )


async def resolver_access_rule(_: Bot, event: Event) -> bool:
    """仅允许白名单群使用 Resolver，私聊消息直接忽略。"""
    return isinstance(event, GroupMessageEvent) and is_group_whitelisted(
        event.group_id
    )


async def resolver_group_rule(bot: Bot, event: Event) -> bool:
    """平台解析器仅接受白名单群消息。"""
    return await resolver_access_rule(bot, event)


resolver_command = Alconna(
    "解析",
    Subcommand("help", alias=["帮助"]),
    Args["content?", StrMulti],
    separators=" ",
    meta=CommandMeta(compact=True),
)
resolver = on_alconna(
    resolver_command,
    aliases={"resolver", "解析",},
    rule=resolver_access_rule,
    use_cmd_sep=False,
    priority=1,
    block=False,
)


def resolve_handler(func):
    """在平台解析器执行前检查群白名单和群内关闭状态。"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        bot = kwargs.get("bot") or next(
            (value for value in args if isinstance(value, Bot)),
            None,
        )
        event = kwargs.get("event") or next(
            (value for value in args if isinstance(value, Event)),
            None,
        )
        if (
            event is None
            or bot is None
            or not isinstance(event, GroupMessageEvent)
        ):
            return None
        resolver_key = _resolver_key_for_handler(func.__name__)
        if not is_group_whitelisted(event.group_id):
            return None

        target_id = _event_target_id(event)
        if not is_resolver_enabled(target_id, resolver_key):
            logger.info(
                f"目标 {target_id} 已关闭 {resolver_key} 解析，不再执行"
            )
            return None

        resolver_token = current_resolver_key.set(resolver_key)
        target_token = current_resolver_target.set(
            str(target_id) if target_id is not None else None
        )
        try:
            return await func(*args, **kwargs)
        finally:
            current_resolver_key.reset(resolver_token)
            current_resolver_target.reset(target_token)

    return wrapper


def resolve_controller(func):
    """根据配置禁用指定平台解析器。"""
    resolver_key = _resolver_key_for_handler(func.__name__)
    status = (
        "禁止"
        if func.__name__.casefold() in disabled_resolvers
        or resolver_key.casefold() in disabled_resolvers
        else "允许"
    )
    logger.debug(f"[link_resolver] 加载 {func.__name__}: {status}")

    @wraps(func)
    async def wrapper(*args, **kwargs):
        if (
            func.__name__.casefold() in disabled_resolvers
            or resolver_key.casefold() in disabled_resolvers
        ):
            logger.warning(f"[link_resolver] {func.__name__} 被禁止执行")
            return None
        return await func(*args, **kwargs)

    return wrapper


async def switch_comment_mode(_: Bot, event: GroupMessageEvent) -> None:
    target_id = str(get_target_id(event))
    current_mode = comment_mode_map.get(target_id, "image")
    new_mode = "text" if current_mode == "image" else "image"
    comment_mode_map[target_id] = new_mode
    save_comment_mode_map(comment_mode_map)
    mode_name = "【文字合并转发】" if new_mode == "text" else "【HTML图片渲染】"
    await resolver.finish(f"已切换至 {mode_name} 评论模式")


async def reload_comment_templates(
    _: Bot,
    __: GroupMessageEvent,
) -> None:
    try:
        from .core.comment import load_bili_template, load_template

        load_template(force_reload=True)
        load_bili_template(force_reload=True)
    except Exception as exc:
        await resolver.finish(f"模板重载失败: {exc}")
    await resolver.finish("评论 HTML 模板重载成功！")


async def view_resolver_status(
    _: Bot,
    event: GroupMessageEvent,
) -> None:
    """渲染并发送当前目标的 Resolver 内容状态表。"""
    target_id = _event_target_id(event)
    scope_name = f"当前群组 {event.group_id}"

    try:
        status_card = await render_resolver_status_card(
            target_id,
            scope_name,
            disabled_resolvers,
        )
    except Exception as exc:
        logger.exception(f"Resolver 状态表渲染失败：{exc}")
        await resolver.finish("解析状态渲染失败，请检查 htmlrender 配置。")
    await resolver.finish(status_card)


@resolver.handle()
async def handle_resolver_command(
    bot: Bot,
    event: GroupMessageEvent,
    content: Match[str],
    result: Arparma,
) -> None:
    """处理主命令；链接由对应的平台 matcher 继续处理。"""
    if result.subcommands:
        return
    tokens = _split_control_tokens(content) if content.available else []
    if not tokens:
        await resolver.finish(__plugin_meta__.usage)

    command = " ".join(tokens)
    manage_permission = GROUP_ADMIN | GROUP_OWNER | SUPERUSER
    if _is_control_command(tokens):
        if not await manage_permission(bot, event):
            await resolver.finish("你没有权限执行这个解析器管理命令。")
        await _apply_control_command(event, tokens)
        return

    command_handlers = {
        "查看": (view_resolver_status, manage_permission),
        "切换评论": (switch_comment_mode, manage_permission),
        "重载评论": (reload_comment_templates, SUPERUSER),
    }
    if command_handler := command_handlers.get(command):
        handler, permission = command_handler
        if not await permission(bot, event):
            await resolver.finish("你没有权限执行这个解析器管理命令。")
        await handler(bot, event)
        return
    if re.search(
        r"https?://|(?:^|\s)BV[0-9a-zA-Z]{10}(?:\s|$)",
        command,
        re.IGNORECASE,
    ):
        return
    await resolver.finish("无法识别该解析指令，请使用“解析 帮助”查看用法。")


@resolver.assign("help")
async def handle_resolver_help() -> None:
    await resolver.finish(__plugin_meta__.usage)
