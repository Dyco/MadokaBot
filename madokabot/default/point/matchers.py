"""积分命令与使用说明。"""

from nonebot_plugin_alconna import Alconna, Args, At, Subcommand, on_alconna

POINT_USAGE = (
    "积分 查询（查询自己的积分与总排名，也可使用“查询 积分”）\n"
    "积分 转账 <@用户|QQ号> <积分数量>\n"
    "积分 排名（本群与全部用户积分前20名）"
)

point_cmd_alc = Alconna(
    "point",
    Subcommand("help", alias=["帮助"]),
    Subcommand("query", alias=["查询"]),
    Subcommand("list", alias=["排名", "List","Rank","列表","rank"]),
    Subcommand(
        "transfer",
        Args["target?", At | str]["amount?", str],
        alias=["转账"],
    ),
)

point_cmd = on_alconna(
    point_cmd_alc,
    aliases={"积分"},
    use_cmd_start=True,
    priority=10,
    block=True,
)
