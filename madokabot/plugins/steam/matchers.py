"""Steam 命令定义与管理权限。"""

from typing import Union

from nonebot.adapters.onebot.v11 import GROUP_ADMIN, GROUP_OWNER
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Alconna, Args, At, CommandMeta, Option, on_alconna

from .config import config

BIND_PERMISSION = GROUP_ADMIN | GROUP_OWNER | SUPERUSER
STEAM_USAGE = (
    "steam help\n"
    "steam bind <SteamID|好友码>\n"
    "steam unbind\n"
    "steam add <@用户|QQ号> <SteamID|好友码>\n"
    "steam remove <@用户|QQ号>\n"
    "steam info <@用户|QQ号>\n"
    "steam check\n"
    "steam list\n"
    "steam enable\n"
    "steam disable\n"
    "steam update\n"
    "steam nickname <昵称|删除>"
)

steam_command = Alconna(
    "steam",
    Option("help", alias=["帮助"]),
    Option("bind", Args["id?", str], alias=["绑定"]),
    Option("add", Args["target?", Union[At, str]]["steam_id?", str], alias=["添加"]),
    Option("unbind", alias=["解绑"]),
    Option("remove", Args["target?", [At, str]], alias=["删除"]),
    Option("info", Args["target?", [At, str]], alias=["信息"]),
    Option("check", alias=["查看"]),
    Option("list", alias=["列表"]),
    Option("enable", alias=["启用", "开启"]),
    Option("disable", alias=["禁用"]),
    Option("update", alias=["更新群信息", "更新"]),
    Option("nickname", Args["name?", str], alias=["昵称", "备注"]),
    separators=" ",
    meta=CommandMeta(compact=True),
)

steam_cmd = on_alconna(
    steam_command,
    use_cmd_start=True,
    priority=config.steam_command_priority,
)
