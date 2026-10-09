import math
import time

from nonebot import get_driver

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import (
    Arparma,
    Image,
    Match,
    UniMessage,
)
from nonebot_plugin_waiter import waiter

from madokabot.core.user.accounts import UserAccount
from .service import SignTemplateService, SkinService
from .render import render_shop_list_card
from .config import config
from .matchers import SHOP_USAGE, shop_cmd
from madokabot.core.messaging.pagination import extract_message_id, parse_page_command


def _calc_total_pages(item_count: int) -> int:
    """按商店每页数量计算总页数。"""
    return max(1, math.ceil(item_count / config.shop_page_size))


async def _build_shop_page(
    uid: str, page: int, category: str = "skin",
) -> tuple[UniMessage, int, int]:
    """读取用户积分与商品信息并渲染指定页。"""
    points = await UserAccount.get_points(uid)
    items = (
        await SignTemplateService.get_shop_template_list(uid)
        if category == "sign" else await SkinService.get_shop_skin_list(uid)
    )
    total_pages = _calc_total_pages(len(items))
    current_page = max(1, min(page, total_pages))
    image_data = render_shop_list_card(
        items,
        points,
        page=current_page,
        page_size=config.shop_page_size,
        total_pages=total_pages,
        category=category,
    )
    return UniMessage(Image(raw=image_data)), current_page, total_pages


def _build_shop_page_text(current_page: int, total_pages: int) -> str:
    """生成商店分页操作提示。"""
    return f"当前页码：{current_page}/{total_pages}，回复上一页/下一页 或 数字 进行翻页"


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
async def _shop_chara(event: MessageEvent):
    """展示立绘商店。"""
    await _send_shop(event, "skin")


@shop_cmd.assign("sign")
async def _shop_sign(event: MessageEvent):
    """展示签到模板商品与预览图。"""
    await _send_shop(event, "sign")


@shop_cmd.assign("list")
async def _shop_list(event: MessageEvent):
    """展示商店商品列表。"""
    starts = get_driver().config.command_start
    prefix = "/" if "/" in starts else next(iter(sorted(starts)), "")
    await shop_cmd.finish(
        "当前事务所正在出售以下内容：\n角色立绘\n签到模板\n"
        f"使用{prefix}shop 内容，可获得详细列表\n例如{prefix}商店 立绘"
    )


async def _send_shop(event: MessageEvent, category: str):
    """商店分页会话方法。"""
    uid = event.get_user_id()
    if not await UserAccount.is_registered(uid):
        await shop_cmd.finish("请先发送“注册”完成用户注册")

    message, current_page, total_pages = await _build_shop_page(uid, 1, category)
    purchase_hint = (
        "购买方式：商店 购买 <模板ID，如 sign03>；切换方式：设置 签到模板 <模板ID>\n"
        if category == "sign" else "购买方式：商店 购买 skin01（使用图中的商品编号）\n"
    )
    send_result = await shop_cmd.send(
        message + purchase_hint + _build_shop_page_text(current_page, total_pages),
        reply_message=True,
    )
    reply_message_id = extract_message_id(send_result)
    if reply_message_id is None:
        return

    @waiter(waits=["message"], keep_session=True, block=True)
    async def wait_shop_page(reply_event: MessageEvent):
        """商店翻页回复检查方法。"""
        if not reply_event.reply:
            return None
        try:
            replied_message_id = int(reply_event.reply.message_id)
        except (TypeError, ValueError):
            return None
        if replied_message_id != reply_message_id:
            return None

        target_page, invalid_page = parse_page_command(
            reply_event.get_plaintext(),
            current_page,
            total_pages,
        )
        if target_page is None and not invalid_page:
            return None
        return reply_event, target_page, invalid_page

    deadline = time.monotonic() + config.shop_session_timeout
    while (remaining := deadline - time.monotonic()) > 0:
        result = await wait_shop_page.wait(timeout=remaining)
        if result is None:
            return

        reply_event, target_page, invalid_page = result
        if invalid_page:
            await UniMessage(f"页码无效，当前共 {total_pages} 页").send(
                target=reply_event, reply_to=True
            )
            continue

        if target_page is None:
            continue
        message, current_page, total_pages = await _build_shop_page(uid, target_page, category)
        send_result = await (
            message + "\n" + _build_shop_page_text(current_page, total_pages)
        ).send(
            target=reply_event,
            reply_to=True,
        )
        next_message_id = extract_message_id(send_result)
        if next_message_id is None:
            return
        reply_message_id = next_message_id


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
        await shop_cmd.finish("参数无效，请输入商品编号，例如 skin01 或 sign02")
    await shop_cmd.finish(message if ok else f"购买失败：{message}")
