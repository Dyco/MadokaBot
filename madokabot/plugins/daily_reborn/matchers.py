"""每日投胎命令定义。"""

from nonebot_plugin_alconna import Alconna, on_alconna

reborn = on_alconna(
    Alconna("reborn"),
    aliases={"每日投胎", "投胎", "daily_reborn"},
    use_cmd_start=True,
    priority=10,
    block=True,
)
