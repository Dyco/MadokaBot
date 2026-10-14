"""舞萌命令注册，统一遵循全局命令起始符。"""

from nonebot_plugin_alconna import Alconna, Args, At, Subcommand, on_alconna

from madokabot.core.config import command_start

MAIMAI_USAGE = (
    f"{command_start}b50 [好友码|QQ号|@用户] 生成舞萌 B50\n"
    f"{command_start}mai b50 [好友码|QQ号|@用户] 同上\n"
    f"{command_start}mai info [好友码|QQ号|@用户] 查询玩家资料\n"
    f"{command_start}mai score <曲目ID> <绿|黄|红|紫|白> <SD|DX> [好友码|QQ号|@用户] 查询最佳成绩\n"
    f"{command_start}mai bind <15位好友码> 绑定自己的舞萌账号\n"
    f"{command_start}mai unbind 解除机器人内的绑定\n"
    f"{command_start}mai update [超级用户] 增量补齐曲绘并更新定数\n"
    "mai 也可写作 maimai 或 舞萌；不填目标时先读机器人绑定，再按当前 QQ 查询 LXNS。\n"
    "查询其他人的好友码不会更改自己的绑定。成绩需先在 LXNS 同步并开放第三方查询权限。"
)

maimai = on_alconna(
    Alconna(
        "mai",
        Subcommand("help", alias=["帮助"]),
        Subcommand("b50", Args["target?", [At, str]]),
        Subcommand("info", Args["target?", [At, str]], alias=["资料", "查分"]),
        Subcommand(
            "score",
            Args["song_id?", int]["difficulty?", str]["chart_type?", str]["target?", [At, str]],
            alias=["成绩"],
        ),
        Subcommand("bind", Args["friend_code?", str], alias=["绑定"]),
        Subcommand("unbind", alias=["解绑"]),
        Subcommand("update", alias=["更新资源"]),
    ),
    aliases={"maimai", "舞萌"},
    use_cmd_start=True,
    priority=10,
    block=True,
)

b50 = on_alconna(
    Alconna("b50", Args["target?", [At, str]]),
    aliases={"B50"},
    use_cmd_start=True,
    priority=10,
    block=True,
)
