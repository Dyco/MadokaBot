"""每日投胎命令定义。"""

from nonebot_plugin_alconna import Alconna, Subcommand, on_alconna

reborn = on_alconna(
    Alconna("reborn", Subcommand("reroll", alias=["重开"], help_text="消耗5积分重新随机投胎")),
    aliases={"投胎"},
    use_cmd_start=True,
    priority=10,
    block=True,
)

reborn_cn = on_alconna(
    Alconna("rebornCN", Subcommand("reroll", alias=["重开"], help_text="消耗5积分重新随机投胎")),
    aliases={"投胎中国"},
    use_cmd_start=True,
    priority=10,
    block=True,
)
