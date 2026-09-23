"""机器人基础功能与扩展插件的帮助入口。"""

from nonebot import get_driver, on_message
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import fullmatch
from nonebot_plugin_alconna import on_alconna

__plugin_meta__ = PluginMetadata(
    name="帮助",
    description="列出机器人提供的主要功能和指令",
    usage="帮助 / help",
    type="application",
)

help_message = on_message(rule=fullmatch(["帮助", "help"]))
help_command = on_alconna(
    "help",
    aliases={"帮助"},
    use_cmd_start=True,
    priority=10,
    block=True,
)


def build_help_text() -> str:
    """按当前配置的起始符展示基础功能和扩展插件指令。"""
    prefix = next(iter(sorted(get_driver().config.command_start)), "")
    commands = (
        "设置 立绘 <立绘ID>",
        "设置 改名 <名字>（最多 10 字，消耗 10 积分）",
        "查询 立绘/资料",
        "商店 立绘/列表/购买 <编号>",
        "群白名单 添加/删除/列表 [群号]",
        "群黑名单 添加/删除/列表 [群号]",
        "copying on/off/set <数量>",
    )
    return (
        "基础功能：注册、签到、Ping、戳一戳\n"
        + "\n".join(prefix + command for command in commands)
        + "\n扩展插件：RSS、解析、CS、Steam、制图（命令使用相同起始符）"
    )


@help_message.handle()
@help_command.handle()
async def handle_help(matcher: Matcher) -> None:
    """为完整匹配消息和带起始符的帮助命令返回统一说明。"""
    await matcher.finish(build_help_text())
