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
    """帮助文本生成方法。"""
    prefix = next(iter(sorted(get_driver().config.command_start)), "")
    commands = (
        "设置 立绘 <立绘ID>",
        "设置 签到模板 <sign01 / sign02 / sign03>",
        "设置 改名 <名字>（最多 10 字，消耗 10 积分）",
        "查询 立绘/签到模板/资料",
        "查询 积分（查询自己的积分与总排名）",
        "积分 查询（查询自己的积分与总排名）",
        "积分 转账 <@用户|QQ号> <积分数量>（也可使用 point）",
        "积分 排名/List（本群与全部用户积分前 20 名）",
        "商店 列表/立绘/签到模板",
        "商店 购买 <skin01 / sign02>",
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
    """帮助命令处理方法。"""
    await matcher.finish(build_help_text())
