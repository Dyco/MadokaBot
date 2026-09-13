"""Resolver 主命令、访问控制与开关状态。"""

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
    Message,
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
from .config import Config
from .state import (
    load_comment_shutdown_list,
    load_comment_mode_map,
    load_resolver_shutdown_list,
    save_comment_shutdown_list,
    save_comment_mode_map,
    save_resolver_shutdown_list,
    split_config_list,
)
from .messages import get_target_id

RESOLVER_USAGE = (
    "用法：\n"
    "解析 <B站/抖音/TikTok/ACFun/X/小红书/YouTube/网易云/酷狗/微博链接>\n"
    "resolver <链接>\n"
    "解析 开启解析 | 解析 关闭解析 | 解析 查看关闭解析\n"
    "解析 开启评论 | 解析 关闭评论 | 解析 切换评论模式 | 解析 重载评论模板\n"
    "解析 帮助"
)
config = get_plugin_config(Config)
disabled_resolvers = split_config_list(config.global_resolve_controller, ",")
resolve_shutdown_list: list = load_resolver_shutdown_list()
comment_shutdown_list: list = load_comment_shutdown_list()
comment_mode_map: dict = load_comment_mode_map()


async def resolver_access_rule(bot: Bot, event: Event) -> bool:
    """白名单群可用；私聊只允许超级用户。"""
    if isinstance(event, GroupMessageEvent):
        return is_group_whitelisted(event.group_id)
    return await SUPERUSER(bot, event)


async def resolver_group_rule(bot: Bot, event: Event) -> bool:
    """平台解析器接受白名单群消息及超级用户私聊。"""
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
    aliases={"resolver", "/解析", "/resolver"},
    rule=resolver_access_rule,
    use_cmd_start=False,
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
        if event is None or bot is None:
            return None
        if isinstance(event, GroupMessageEvent):
            if not is_group_whitelisted(event.group_id):
                return None
            if event.group_id in resolve_shutdown_list:
                logger.info(f"群 {event.group_id} 已关闭解析，不再执行")
                return None
        elif not await SUPERUSER(bot, event):
            return None
        return await func(*args, **kwargs)

    return wrapper


def resolve_controller(func):
    """根据配置禁用指定平台解析器。"""
    status = "禁止" if func.__name__ in disabled_resolvers else "允许"
    logger.debug(f"[link_resolver] 加载 {func.__name__}: {status}")

    @wraps(func)
    async def wrapper(*args, **kwargs):
        if func.__name__ in disabled_resolvers:
            logger.warning(f"[link_resolver] {func.__name__} 被禁止执行")
            return None
        return await func(*args, **kwargs)

    return wrapper


async def enable(_: Bot, event: Event) -> None:
    target_id = get_target_id(event)
    if target_id in resolve_shutdown_list:
        resolve_shutdown_list.remove(target_id)
        save_resolver_shutdown_list(resolve_shutdown_list)
        await resolver.finish("解析已开启")
    await resolver.finish("解析已开启，无需重复开启")


async def disable(_: Bot, event: Event) -> None:
    target_id = get_target_id(event)
    if target_id not in resolve_shutdown_list:
        resolve_shutdown_list.append(target_id)
        save_resolver_shutdown_list(resolve_shutdown_list)
        await resolver.finish("解析已关闭")
    await resolver.finish("解析已关闭，无需重复关闭")


async def check_disable(bot: Bot, event: Event) -> None:
    async def describe(items: list) -> str:
        result = []
        for item in items:
            try:
                group = await bot.get_group_info(group_id=int(item))
                name = group.get("group_name", "未知群组")
            except Exception:
                name = "无法获取群名"
            result.append(f"{item}--{name}")
        return "\n".join(result) or "（空）"

    memory = await describe(resolve_shutdown_list)
    persistent = await describe(load_resolver_shutdown_list())
    message = (
        "[Madoka 链接解析器关闭名单如下：]\n\n"
        f"1. 在【内存】中的名单有：\n{memory}\n\n"
        f"2. 在【持久层】中的名单有：\n{persistent}\n\n"
        "🌟 温馨提示：使用“解析 关闭解析”可关闭本群解析"
    )
    await bot.send(event, message=Message("已经发送到私信了~"))
    await bot.send_private_msg(user_id=event.user_id, message=Message(message))


async def enable_comments(_: Bot, event: Event) -> None:
    target_id = get_target_id(event)
    if target_id in comment_shutdown_list:
        comment_shutdown_list.remove(target_id)
        save_comment_shutdown_list(comment_shutdown_list)
        await resolver.finish("评论已开启")
    await resolver.finish("评论已开启，无需重复开启")


async def disable_comments(_: Bot, event: Event) -> None:
    target_id = get_target_id(event)
    if target_id not in comment_shutdown_list:
        comment_shutdown_list.append(target_id)
        save_comment_shutdown_list(comment_shutdown_list)
        await resolver.finish("评论已关闭")
    await resolver.finish("评论已关闭，无需重复关闭")


async def switch_comment_mode(_: Bot, event: Event) -> None:
    target_id = str(get_target_id(event))
    current_mode = comment_mode_map.get(target_id, "image")
    new_mode = "text" if current_mode == "image" else "image"
    comment_mode_map[target_id] = new_mode
    save_comment_mode_map(comment_mode_map)
    mode_name = "【文字合并转发】" if new_mode == "text" else "【HTML图片渲染】"
    await resolver.finish(f"已切换至 {mode_name} 评论模式")


async def reload_comment_templates(_: Bot, __: Event) -> None:
    try:
        from .core.comment import load_bili_template, load_template

        load_template(force_reload=True)
        load_bili_template(force_reload=True)
    except Exception as exc:
        await resolver.finish(f"模板重载失败: {exc}")
    await resolver.finish("评论 HTML 模板重载成功！")


@resolver.handle()
async def handle_resolver_command(
    bot: Bot,
    event: Event,
    content: Match[str],
    result: Arparma,
) -> None:
    """处理主命令；链接由对应的平台 matcher 继续处理。"""
    if result.subcommands:
        return
    if not content.available or not content.result.strip():
        await resolver.finish(RESOLVER_USAGE)

    command = " ".join(content.result.strip().split())
    manage_permission = GROUP_ADMIN | GROUP_OWNER | SUPERUSER
    command_handlers = {
        "开启解析": (enable, manage_permission),
        "开启": (enable, manage_permission),
        "关闭解析": (disable, manage_permission),
        "关闭": (disable, manage_permission),
        "查看关闭解析": (check_disable, SUPERUSER),
        "查看": (check_disable, SUPERUSER),
        "开启评论": (enable_comments, manage_permission),
        "关闭评论": (disable_comments, manage_permission),
        "切换评论模式": (switch_comment_mode, manage_permission),
        "重载评论模板": (reload_comment_templates, SUPERUSER),
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
    await resolver.finish(RESOLVER_USAGE)
