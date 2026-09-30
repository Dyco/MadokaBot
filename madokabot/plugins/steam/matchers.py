"""Steam 命令定义与管理权限。"""

from typing import Union

from nonebot.adapters.onebot.v11 import GROUP_ADMIN, GROUP_OWNER
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Alconna, Args, At, CommandMeta, Option, on_alconna

from .config import config

BIND_PERMISSION = GROUP_ADMIN | GROUP_OWNER | SUPERUSER
STEAM_USAGE = (
    "steam help 获取帮助菜单\n"
    "steam bind [SteamID|好友码] 绑定个人steam\n"
    "steam unbind 解绑个人steam\n"
    "steam hide 在本群隐藏推送\n"
    "steam online 在本群开启推送\n"
    "steam add <@用户|QQ号> <SteamID|好友码> 添加用户\n"
    "steam remove <@用户|QQ号> 删除用户\n"
    "steam info <@用户|QQ号> 查看用户信息\n"
    "steam check 查看本群玩家在线状态\n"
    "steam list 查看本群玩家绑定情况\n"
    "steam enable [管理员] 启用Steam播报\n"
    "steam disable [管理员] 禁用Steam播报\n"
    "steam nickname <昵称|删除> 设置昵称备注"
)

steam_command = Alconna(
    "steam",
    Option("help", alias=["帮助"]),
    Option("bind", Args["id?", str], alias=["绑定"]),
    Option("add", Args["target?", Union[At, str]]["steam_id?", str], alias=["添加"]),
    Option("unbind", alias=["解绑"]),
    Option("hide", alias=["隐藏","隐身"]),
    Option("online", alias=["上线"]),
    Option("remove", Args["target?", [At, str]], alias=["删除"]),
    Option("info", Args["target?", [At, str]], alias=["信息"]),
    Option("check", alias=["查看"]),
    Option("list", alias=["列表"]),
    Option("enable", alias=["启用", "开启"]),
    Option("disable", alias=["禁用"]),
    Option("nickname", Args["name?", str], alias=["昵称", "备注"]),
    separators=" ",
    meta=CommandMeta(compact=True),
)

steam_cmd = on_alconna(
    steam_command,
    use_cmd_start=True,
    priority=config.steam_command_priority,
)
