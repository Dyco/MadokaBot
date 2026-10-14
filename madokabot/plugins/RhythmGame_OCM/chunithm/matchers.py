"""中二节奏命令注册，遵循全局命令起始符。"""

from nonebot_plugin_alconna import Alconna, Args, At, Subcommand, on_alconna

from madokabot.core.config import command_start

CHUNITHM_USAGE = (
    f"{command_start}cb50 [好友码|QQ号|@用户] 生成中二 B50\n"
    f"{command_start}chu b50 [好友码|QQ号|@用户] 同上，包含 B30、新曲 B20 与独立 S10\n"
    f"{command_start}chu info [好友码|QQ号|@用户] 查询中二资料\n"
    f"{command_start}chu score <曲目ID> <绿|黄|红|紫|黑|WE> [好友码|QQ号|@用户] 查询最佳成绩\n"
    f"{command_start}chu bind <15位好友码> 绑定中二账号\n"
    f"{command_start}chu unbind 解除机器人内的中二绑定\n"
    f"{command_start}chu update [超级用户] 更新中二曲目定数与曲绘\n"
    "chu 别名：chuni、chunithm、中二、中二节奏。中二绑定与舞萌独立。\n"
    "不填目标时先读机器人绑定，再按当前 QQ 查询 LXNS；成绩需先同步并开放第三方查询。"
)

chunithm = on_alconna(
    Alconna(
        "chu",
        Subcommand("help", alias=["帮助"]),
        Subcommand("b50", Args["target?", [At, str]]),
        Subcommand("info", Args["target?", [At, str]], alias=["资料", "查分"]),
        Subcommand(
            "score", Args["song_id?", int]["difficulty?", str]["target?", [At, str]],
            alias=["成绩"],
        ),
        Subcommand("bind", Args["friend_code?", str], alias=["绑定"]),
        Subcommand("unbind", alias=["解绑"]),
        Subcommand("update", alias=["更新资源"]),
    ),
    aliases={"chuni", "chunithm", "中二", "中二节奏"},
    use_cmd_start=True,
    priority=10,
    block=True,
)

cb50 = on_alconna(
    Alconna("cb50", Args["target?", [At, str]]),
    aliases={"CB50"},
    use_cmd_start=True,
    priority=10,
    block=True,
)
