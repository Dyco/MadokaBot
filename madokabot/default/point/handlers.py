"""积分命令的参数校验与回复。"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot_plugin_alconna import Arparma, At, Match

from .matchers import POINT_USAGE, point_cmd
from .service import get_points_ranking, transfer_points


@point_cmd.handle()
async def handle_point_root(result: Arparma) -> None:
    """未指定子命令时展示积分命令用法。"""
    if not result.subcommands:
        await point_cmd.finish(f"用法：{POINT_USAGE}")


@point_cmd.assign("help")
async def handle_point_help() -> None:
    """返回积分命令说明。"""
    await point_cmd.finish(f"用法：{POINT_USAGE}")


def format_points_ranking(title: str, ranking: list[tuple[str, str, int]]) -> str:
    """用固定两个星号隐藏 QQ 号中段，昵称与积分之间保留两个空格。"""
    lines = [title]
    for index, (uid, nickname, points) in enumerate(ranking[:20], start=1):
        masked_id = f"{uid[:2]}**{uid[-2:]}" if len(uid) > 4 else "**"
        name = " ".join(nickname.split()) or "未设置昵称"
        lines.append(f"{index}. {name}（{masked_id}）  {points} 积分")
    if not ranking:
        lines.append("暂无已注册用户")
    return "\n".join(lines)


@point_cmd.assign("list")
async def handle_points_ranking(bot: Bot, event: MessageEvent) -> None:
    """用三个合并转发节点展示提示、本群排名和全部用户排名。"""
    if isinstance(event, GroupMessageEvent):
        try:
            members = await bot.get_group_member_list(group_id=event.group_id)
        except Exception:
            logger.exception("积分排名获取本群成员失败")
            await point_cmd.finish("获取本群成员失败，请稍后重试")
        ranking = await get_points_ranking([str(member["user_id"]) for member in members])
        group_text = format_points_ranking("本群积分排名（前 20 名）", ranking)
    else:
        group_text = "本群积分排名\n请在群聊中查询本群排名"

    all_text = format_points_ranking(
        "全部用户积分排名（前 20 名）", await get_points_ranking()
    )
    nodes = [
        MessageSegment.node_custom(
            user_id=bot.self_id,
            nickname="积分排名",
            content=Message(MessageSegment.text(text)),
        )
        for text in ("积分排名查询结果如下。", group_text, all_text)
    ]
    try:
        if isinstance(event, GroupMessageEvent):
            await bot.send_group_forward_msg(group_id=event.group_id, messages=nodes)
        else:
            await bot.send_private_forward_msg(user_id=event.user_id, messages=nodes)
    except Exception:
        logger.exception("积分排名合并消息发送失败")
        await point_cmd.finish("合并消息发送失败，请稍后重试")
    await point_cmd.finish()


@point_cmd.assign("transfer")
async def handle_transfer(
    event: MessageEvent, target: Match[At | str], amount: Match[str]
) -> None:
    """从 QQ 号或艾特读取收款人，校验数量后执行转账。"""
    if not target.available or not amount.available:
        await point_cmd.finish(f"请补充收款人和积分数量。用法：{POINT_USAGE}")

    recipient = target.result
    if isinstance(recipient, At):
        if recipient.flag != "user":
            await point_cmd.finish("请艾特一位用户或输入有效的 QQ 号")
        recipient_id = str(recipient.target)
    else:
        recipient_id = recipient.strip()
    if (
        not recipient_id.isascii()
        or not recipient_id.isdecimal()
        or int(recipient_id) <= 0
    ):
        await point_cmd.finish("请艾特一位用户或输入有效的 QQ 号")

    raw_amount = amount.result.strip()
    if not raw_amount.isascii() or not raw_amount.isdecimal() or int(raw_amount) <= 0:
        await point_cmd.finish("转账积分数量必须是正整数")

    ok, message = await transfer_points(
        event.get_user_id(), str(int(recipient_id)), int(raw_amount)
    )
    await point_cmd.finish(message if ok else f"转账失败：{message}")
