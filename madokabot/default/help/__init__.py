"""机器人基础功能与扩展插件的帮助入口。"""

from nonebot import get_driver, get_loaded_plugins, logger, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    OneBotV11AdapterException,
)
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import fullmatch
from nonebot_plugin_alconna import on_alconna

from madokabot.core.version import get_bot_version

__plugin_meta__ = PluginMetadata(
    name="帮助",
    description="通过合并转发展示插件分类、功能说明和使用方法",
    usage="帮助/help",
    type="application",
    supported_adapters={"~onebot.v11"},
)

HELP_CATEGORIES = ("响应内容", "基础功能", "拓展功能")

help_message = on_message(rule=fullmatch(["帮助", "help"]))
help_command = on_alconna(
    "help",
    aliases={"帮助"},
    use_cmd_start=True,
    priority=10,
    block=True,
)


def build_help_messages() -> list[str]:
    """按元数据中的帮助分类和顺序生成总览及插件详情。"""
    groups: dict[str, list[PluginMetadata]] = {
        category: [] for category in HELP_CATEGORIES
    }
    for plugin in get_loaded_plugins():
        metadata = plugin.metadata
        if metadata is None:
            continue
        category = metadata.extra.get("help_category")
        if category in groups:
            groups[category].append(metadata)

    overview = [f"以下是MadokaBot Ver{get_bot_version()}的全部插件内容"]
    details = []
    for category, plugins in groups.items():
        if not plugins:
            continue
        plugins.sort(key=lambda meta: (meta.extra.get("help_order", 100), meta.name))
        overview.append(f"——{category}——")
        overview.extend(meta.name for meta in plugins)
        details.extend(
            "\n".join(
                text
                for text in (
                    f"【{category}】",
                    f"·{meta.name}",
                    meta.description,
                    meta.usage,
                )
                if text
            )
            for meta in plugins
        )

    prefixes = "、".join(
        repr(prefix) for prefix in sorted(get_driver().config.command_start)
    )
    overview.append(f"\n指令起始符：{prefixes}（完整匹配关键词除外）")
    return ["\n".join(overview), *details]


@help_message.handle()
@help_command.handle()
async def handle_help(bot: Bot, event: MessageEvent, matcher: Matcher) -> None:
    """将帮助总览和插件详情以合并转发发送至当前群聊或私聊。"""
    nodes = [
        MessageSegment.node_custom(
            user_id=int(bot.self_id),
            nickname="MadokaBot帮助",
            content=Message(MessageSegment.text(text)),
        )
        for text in build_help_messages()
    ]
    try:
        if isinstance(event, GroupMessageEvent):
            await bot.send_group_forward_msg(group_id=event.group_id, messages=nodes)
        else:
            await bot.send_private_forward_msg(user_id=event.user_id, messages=nodes)
    except OneBotV11AdapterException:
        logger.exception("帮助合并转发发送失败")
        await matcher.finish("帮助消息发送失败，请稍后重试")
    await matcher.finish()
