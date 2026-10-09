"""超级用户命令处理。"""

import re

from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_alconna import Arparma, At

from .matchers import MODIFY_USAGE, modify_cmd
from .service import modify_user_stat


@modify_cmd.handle()
async def handle_modify(result: Arparma) -> None:
    """用户数值修改命令处理方法。"""
    if not result.subcommands:
        await modify_cmd.finish(f"用法：{MODIFY_USAGE}")
    field, subcommand = next(iter(result.subcommands.items()))
    target = subcommand.args.get("target")
    value = subcommand.args.get("value")
    if target is None or value is None:
        await modify_cmd.finish(f"请补充目标用户和数值。用法：{MODIFY_USAGE}")

    if isinstance(target, At):
        if target.flag != "user":
            await modify_cmd.finish("请艾特一位用户或输入有效的QQ号")
        uid = str(target.target)
    else:
        uid = target.strip()
    if not uid.isascii() or not uid.isdecimal() or int(uid) <= 0:
        await modify_cmd.finish("请艾特一位用户或输入有效的QQ号")

    raw_value = value.strip()
    if re.fullmatch(r"[+-]?[0-9]+", raw_value) is None:
        await modify_cmd.finish("数值必须是整数，例如+20、20或-20")
    try:
        amount = int(raw_value)
    except ValueError:
        await modify_cmd.finish("数值过大，请输入较小的整数")
    ok, message = await modify_user_stat(str(int(uid)), field, amount)
    await modify_cmd.finish(
        MessageSegment.text(message if ok else f"修改失败：{message}")
    )
