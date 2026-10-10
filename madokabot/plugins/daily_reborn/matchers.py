"""每日投胎命令定义。"""

from nonebot_plugin_alconna import Alconna, Subcommand, on_alconna

reborn = on_alconna(
    Alconna("reborn", Subcommand("reroll", alias=["重开"], help_text="消耗 5 积分重新随机投胎")),
    aliases={"每日投胎", "投胎", "daily_reborn"},
    use_cmd_start=True,
    priority=10,
    block=True,
)
