import math

from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    OneBotV11AdapterException,
)
from nonebot_plugin_alconna import Arparma, Match

from madokabot.core.config import command_start
from madokabot.core.messaging.response import respond
from madokabot.core.user.accounts import UserAccount

from .config import config
from .matchers import SHOP_USAGE, shop_cmd
from .render import SIGN_PAGE_SIZE, render_shop_list_card
from .service import SignTemplateService, SkinService


async def _build_shop_messages(uid: str, points: int, category: str) -> list[Message]:
    """生成分类操作说明与全部商品页，供合并转发使用。"""
    items = (
        await SignTemplateService.get_shop_template_list(uid)
        if category == "sign" else await SkinService.get_shop_skin_list(uid)
    )
    page_size = SIGN_PAGE_SIZE if category == "sign" else config.shop_page_size
    total_pages = max(1, math.ceil(len(items) / page_size))
    title = "签到模板" if category == "sign" else "角色立绘"
    setting = "签到模板" if category == "sign" else "立绘"
    example = "sign02" if category == "sign" else "skin01"
    hint = (
        f"——{title}——\n"
        f"{command_start}商店 购买 <编号，如{example}>\n"
        f"{command_start}设置 {setting} <编号，如{example}>\n"
        f"{command_start}积分 赠礼 <@用户|QQ号> <编号>"
    )
    messages = [Message(MessageSegment.text(hint))]
    for page in range(1, total_pages + 1):
        image_data = render_shop_list_card(
            items,
            points,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            category=category,
        )
        messages.append(
            MessageSegment.text(f"第 {page} 页\n") + MessageSegment.image(image_data)
        )
    return messages


@shop_cmd.handle()
async def _handle_shop_root(result: Arparma):
    """处理未指定子命令的商店入口。"""
    if not result.subcommands:
        await shop_cmd.finish(SHOP_USAGE)


@shop_cmd.assign("help")
async def _shop_help():
    """返回商店命令说明。"""
    await shop_cmd.finish(SHOP_USAGE)


@shop_cmd.assign("chara")
async def _shop_chara(bot: Bot, event: MessageEvent):
    """展示立绘商店。"""
    await _send_shop(bot, event, ("skin",))


@shop_cmd.assign("sign")
async def _shop_sign(bot: Bot, event: MessageEvent):
    """展示签到模板商品与预览图。"""
    await _send_shop(bot, event, ("sign",))


@shop_cmd.assign("list")
async def _shop_list(bot: Bot, event: MessageEvent):
    """依次展示立绘与签到模板的全部商品页。"""
    await _send_shop(bot, event, ("skin", "sign"))


async def _send_shop(bot: Bot, event: MessageEvent, categories: tuple[str, ...]) -> None:
    """添加表情回应，将指定分类的说明和图片合并转发到当前会话。"""
    await respond(bot, event)
    uid = event.get_user_id()
    if not await UserAccount.is_registered(uid):
        await shop_cmd.finish("请先发送“注册”完成用户注册")

    try:
        points = await UserAccount.get_points(uid)
        messages = []
        for category in categories:
            messages.extend(await _build_shop_messages(uid, points, category))
    except (OSError, ValueError):
        logger.exception("商店图片生成失败")
        await shop_cmd.finish("商店图片生成失败，请稍后重试")

    nodes = [
        MessageSegment.node_custom(
            user_id=int(bot.self_id),
            nickname="MadokaBot商店",
            content=message,
        )
        for message in messages
    ]
    try:
        if isinstance(event, GroupMessageEvent):
            await bot.send_group_forward_msg(group_id=event.group_id, messages=nodes)
        else:
            await bot.send_private_forward_msg(user_id=event.user_id, messages=nodes)
    except OneBotV11AdapterException:
        logger.exception("商店合并转发发送失败")
        await shop_cmd.finish("商店消息发送失败，请稍后重试")
    await shop_cmd.finish()


@shop_cmd.assign("buy")
async def _shop_buy_item(event: MessageEvent, number: Match[str]):
    """仅按带类别前缀的商品编号购买。"""
    uid = event.get_user_id()
    if not await UserAccount.is_registered(uid):
        await shop_cmd.finish("请先发送“注册”完成用户注册")

    if not number.available or not number.result.strip():
        await shop_cmd.finish(f"用法：{SHOP_USAGE}")

    raw_number = number.result.strip().lower()
    if raw_number.startswith("sign"):
        ok, message = await SignTemplateService.buy_template(uid, raw_number)
    elif raw_number.startswith("skin"):
        ok, message = await SkinService.buy_shop_skin(uid, raw_number)
    else:
        await shop_cmd.finish(f"商品编号无效，请发送“{command_start}商店 立绘”或“{command_start}商店 签到模板”查看编号。购买示例：{command_start}商店 购买 skin01、{command_start}商店 购买 sign02")
    await shop_cmd.finish(message if ok else f"购买失败：{message}")
