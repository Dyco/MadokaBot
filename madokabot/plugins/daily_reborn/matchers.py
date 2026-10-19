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

reborn_jp = on_alconna(
    Alconna("rebornJP", Subcommand("reroll", alias=["重开"], help_text="消耗5积分重新随机投胎")),
    aliases={"投胎日本"},
    use_cmd_start=True,
    priority=10,
    block=True,
)

reborn_us = on_alconna(
    Alconna("rebornUS", Subcommand("reroll", alias=["重开"], help_text="消耗5积分重新随机投胎")),
    aliases={"投胎美国"},
    use_cmd_start=True,
    priority=10,
    block=True,
)

reborn_isekai = on_alconna(
    Alconna("rebornIsekai", Subcommand("reroll", alias=["重开"], help_text="消耗5积分重新随机投胎")),
    aliases={"投胎异世界"},
    use_cmd_start=True,
    priority=10,
    block=True,
)

reborn_anime = on_alconna(
    Alconna("rebornAnime", Subcommand("reroll", alias=["重开"], help_text="消耗5积分重新随机二次元身份")),
    aliases={"投胎二次元"},
    use_cmd_start=True,
    priority=10,
    block=True,
)

reborn_games = on_alconna(
    Alconna("rebornGames", Subcommand("reroll", alias=["重开"], help_text="消耗5积分重新随机二游身份")),
    aliases={"投胎二游"},
    use_cmd_start=True,
    priority=10,
    block=True,
)

reborn_all = on_alconna(
    Alconna("rebornAll", Subcommand("reroll", alias=["重开"], help_text="每种模式消耗5积分重新随机全部投胎")),
    aliases={"一键投胎"},
    use_cmd_start=True,
    priority=10,
    block=True,
)
