"""积分命令的参数校验与回复。"""

from nonebot import logger
from nonebot.matcher import Matcher
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot_plugin_alconna import Arparma, At, Check, Match, assign

from madokabot.core.user.accounts import UserAccount
from madokabot.default.account.matchers import query_cmd

from .matchers import POINT_USAGE, point_cmd
from .service import get_points_ranking, transfer_points


@point_cmd.handle()
async def handle_point_root(result: Arparma) -> None:
    """积分命令入口。"""
    if not result.subcommands:
        await point_cmd.finish(f"用法：{POINT_USAGE}")


@point_cmd.assign("help")
async def handle_point_help() -> None:
    """积分帮助方法。"""
    await point_cmd.finish(f"用法：{POINT_USAGE}")


# assign复用函数的注册索引，跨命令共享方法需用handle分别注册。
@query_cmd.handle(parameterless=[Check(assign("point"))])
@point_cmd.handle(parameterless=[Check(assign("query"))])
async def handle_point_query(event: MessageEvent, matcher: Matcher) -> None:
    """个人积分查询方法。"""
    try:
        points, rank = await UserAccount.get_points_and_rank(event.get_user_id())
    except LookupError:
        await matcher.finish("请先发送“注册”完成用户注册")
    rank_text = f"排名第{rank}名" if rank is not None else "未参与排名"
    await matcher.finish(f"查询结果：制作人当前持有{points}积分，{rank_text}。")


def format_points_ranking(title: str, ranking: list[tuple[str, str, int]]) -> str:
    """积分排名格式化方法。"""
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
    """积分排名发送方法。"""
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
    bot: Bot, event: MessageEvent, target: Match[At | str], amount: Match[str]
) -> None:
    """转账命令处理方法。"""
    if not target.available or not amount.available:
        await point_cmd.finish(f"请补充收款人和积分数量，使用空格分隔。用法：\n{POINT_USAGE}\n示例：积分 转账 @用户 100")

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

    recipient_id = str(int(recipient_id))
    recipient_name = await get_recipient_name(bot, event, recipient_id)
    ok, message = await transfer_points(
        event.get_user_id(), recipient_id, int(raw_amount), recipient_name
    )
    await point_cmd.finish(MessageSegment.text(message if ok else f"转账失败：{message}"))


async def get_recipient_name(bot: Bot, event: MessageEvent, recipient_id: str) -> str:
    """收款人昵称查询方法。"""
    if isinstance(event, GroupMessageEvent):
        try:
            member = await bot.get_group_member_info(
                group_id=event.group_id, user_id=int(recipient_id)
            )
            name = (member.get("card") or "").strip() or (member.get("nickname") or "").strip()
            if name:
                return name
        except Exception as exc:
            logger.debug(f"获取转账收款人群昵称失败：{exc}")

    try:
        user = await bot.get_stranger_info(user_id=int(recipient_id))
        return (user.get("nickname") or "").strip()
    except Exception as exc:
        logger.debug(f"获取转账收款人 QQ 昵称失败：{exc}")
        return ""
