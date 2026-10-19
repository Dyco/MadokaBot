"""超级用户命令定义。"""

from nonebot import on_message
from nonebot.permission import SUPERUSER
from nonebot.rule import fullmatch
from nonebot_plugin_alconna import Alconna, Args, At, Subcommand, on_alconna

from madokabot.core.config import command_start

MODIFY_USAGE = f"{command_start}修改 <好感|积分> <@用户|QQ号> <数值>"

modify_cmd_alc = Alconna(
    "修改",
    Subcommand("好感", Args["target?", At | str]["value?", str]),
    Subcommand("积分", Args["target?", At | str]["value?", str]),
)

modify_cmd = on_alconna(
    modify_cmd_alc,
    permission=SUPERUSER,
    use_cmd_start=True,
    priority=10,
    block=True,
)

broadcast_cmd = on_message(
    rule=fullmatch(["/全群通告", "全群通告"]),
    permission=SUPERUSER,
    priority=10,
    block=True,
)
