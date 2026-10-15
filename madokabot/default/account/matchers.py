"""业务命令定义。"""

from nonebot import on_message
from nonebot.rule import fullmatch
from arclet.alconna import StrMulti
from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna

from madokabot.core.config import command_start

RENAME_USAGE = f"{command_start}设置 改名 <名字>（1～10 个字符或汉字，每次消耗 10 积分）"
SET_USAGE = (
    f"{command_start}设置 立绘 <立绘编号>\n"
    f"{command_start}设置 签到模板 <模板编号，如sign02>\n"
    f"{command_start}设置 随机立绘（开/关；英文：{command_start}set random_skin）\n"
    f"{command_start}设置 随机模板（开/关；英文：{command_start}set random_template）\n"
    + RENAME_USAGE
)

QUERY_USAGE = f"{command_start}查询 立绘/签到模板/资料/积分"

set_cmd_alc = Alconna(
    "set",
    Subcommand("chara", Args["skin_id?", str], alias=["立绘"]),
    Subcommand("sign", Args["template_id?", str], alias=["签到", "签到模板"]),
    Subcommand("random_skin", alias=["随机立绘", "random_chara"]),
    Subcommand("random_template", alias=["随机模板", "随机签到模板", "random_sign"]),
    Subcommand("rename", Args["name?", StrMulti], alias=["改名", "更名"]),
)

query_cmd_alc = Alconna(
    "query",
    Subcommand("chara", alias=["立绘"]),
    Subcommand("sign", alias=["签到", "签到模板"]),
    Subcommand("data", alias=["资料"]),
    Subcommand("point", alias=["积分"]),
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

register_cmd = on_message(rule=fullmatch(["注册", "register", "/注册", "/register"]))
