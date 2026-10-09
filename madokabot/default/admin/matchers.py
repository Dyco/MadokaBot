"""超级用户命令定义。"""

from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Alconna, Args, At, Subcommand, on_alconna

MODIFY_USAGE = "修改 <好感|积分> <@用户|QQ号> <数值>"

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
