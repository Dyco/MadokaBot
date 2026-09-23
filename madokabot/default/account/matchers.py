"""业务命令定义。"""

from nonebot import on_message
from nonebot.rule import fullmatch
from arclet.alconna import StrMulti
from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna

RENAME_USAGE = "设置 改名 <名字>（1～10 个字符或汉字，每次消耗 10 积分）"
SET_USAGE = "设置 立绘 <立绘编号>\n" + RENAME_USAGE

QUERY_USAGE = "查询 立绘/资料"

set_cmd_alc = Alconna(
    "set",
    Subcommand("chara", Args["skin_id?", str], alias=["立绘"]),
    Subcommand("rename", Args["name?", StrMulti], alias=["改名", "更名"]),
)

query_cmd_alc = Alconna(
    "query",
    Subcommand("chara", alias=["立绘"]),
    Subcommand("data", alias=["资料"]),
)

set_cmd = on_alconna(
    set_cmd_alc,
    use_cmd_start=True,
    aliases={"设置"},
    priority=10,
    block=True,
)

query_cmd = on_alconna(
    query_cmd_alc,
    use_cmd_start=True,
    aliases={"查询"},
    priority=10,
    block=True,
)

register_cmd = on_message(rule=fullmatch(["注册", "register"]))
