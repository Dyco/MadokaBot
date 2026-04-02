import math
import re
import time
from dataclasses import dataclass
from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import (
    Alconna,
    Arparma,
    Args,
    Image,
    Match,
    Subcommand,
    UniMessage,
    on_alconna,
)

from ...db.user_source import UserAccount
from ..pillow import render_shop_list_card

__plugin_meta__ = PluginMetadata(
    name="通用插件",
    description="通用指令集合，包含设置、查询和商店功能",
    usage=(
        "请使用以下指令：\n"
        "set chara <立绘ID>\n"
        "query chara\n"
        "query data\n"
        "shop help\n"
        "shop list\n"
        "shop buy <编号>"
    ),
    type="application",
)


SET_USAGE = "set chara <立绘ID>"
QUERY_USAGE = "query chara\nquery data"
SHOP_USAGE = "shop help\nshop list\nshop buy <编号>"
SHOP_PAGE_SIZE = 12
SHOP_PAGE_TTL = 600


@dataclass
class ShopPageSession:
    user_id: str
    current_page: int
    total_pages: int
    expires_at: float


shop_page_sessions: dict[int, ShopPageSession] = {}


set_cmd_alc = Alconna(
    "set",
    ["设置"],
    Subcommand("chara", Args["id?", str], alias=["立绘"]),
)

query_cmd_alc = Alconna(
    "query",
    ["查询"],
    Subcommand("chara", alias=["立绘"]),
    Subcommand("data", alias=["资料"]),
)

shop_cmd_alc = Alconna(
    "shop",
    Subcommand("help", alias=["帮助"]),
    Subcommand("list", alias=["列表"]),
    Subcommand("buy", Args["item_id?", str], alias=["购买"]),
)

set_cmd = on_alconna(set_cmd_alc, priority=10, block=True)
query_cmd = on_alconna(query_cmd_alc, priority=10, block=True)
shop_cmd = on_alconna(shop_cmd_alc, priority=10, block=True)
shop_page_reply = on_message(priority=11, block=False)


def _prune_shop_page_sessions() -> None:
    now = time.time()
    expired = [
        message_id
        for message_id, session in shop_page_sessions.items()
        if session.expires_at <= now
    ]
    for message_id in expired:
        shop_page_sessions.pop(message_id, None)


def _extract_message_id(send_result: Any) -> int | None:
    if hasattr(send_result, "msg_ids"):
        msg_ids = getattr(send_result, "msg_ids", None) or []
        if msg_ids:
            first_id = msg_ids[0]
            if isinstance(first_id, dict):
                first_id = first_id.get("message_id")
            try:
                return int(first_id) if first_id is not None else None
            except (TypeError, ValueError):
                return None

    if isinstance(send_result, dict):
        message_id = send_result.get("message_id")
    else:
        message_id = getattr(send_result, "message_id", None)
    try:
        return int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return None


def _calc_total_pages(item_count: int) -> int:
    return max(1, math.ceil(item_count / SHOP_PAGE_SIZE))


def _parse_page_command(text: str, current_page: int, total_pages: int) -> tuple[int | None, bool]:
    normalized = text.strip().lower()
    if not normalized:
        return None, False

    if normalized in {"下一页", "下页", "next", "n"}:
        return min(total_pages, current_page + 1), False
    if normalized in {"上一页", "上页", "prev", "previous", "p"}:
        return max(1, current_page - 1), False

    page_match = re.fullmatch(r"第?\s*(\d+)\s*页?", normalized)
    if page_match:
        page = int(page_match.group(1))
        if 1 <= page <= total_pages:
            return page, False
        return None, True
    return None, False


async def _build_shop_page(uid: str, page: int) -> tuple[UniMessage, int, int]:
    points = await UserAccount.get_points(uid)
    items = await UserAccount.get_shop_skin_list(uid)
    total_pages = _calc_total_pages(len(items))
    current_page = max(1, min(page, total_pages))
    image_data = render_shop_list_card(
        items,
        points,
        page=current_page,
        page_size=SHOP_PAGE_SIZE,
        total_pages=total_pages,
    )
    return UniMessage(Image(raw=image_data)), current_page, total_pages


def _build_shop_page_text(current_page: int, total_pages: int) -> str:
    return (
        f"当前页码：{current_page}/{total_pages}，"
        "回复上一页/下一页 或 数字 进行翻页"
    )


def _store_shop_page_session(
    message_id: int | None,
    uid: str,
    current_page: int,
    total_pages: int,
) -> None:
    if message_id is None:
        return
    _prune_shop_page_sessions()
    shop_page_sessions[message_id] = ShopPageSession(
        user_id=uid,
        current_page=current_page,
        total_pages=total_pages,
        expires_at=time.time() + SHOP_PAGE_TTL,
    )


@set_cmd.handle()
async def handle_set_base(result: Arparma):
    if not result.subcommands:
        await set_cmd.finish(f"用法：{SET_USAGE}")


@set_cmd.assign("chara")
async def _set_skin(event: MessageEvent, id: Match[str]):
    uid = event.get_user_id()
    if not id.available or not id.result.strip():
        await set_cmd.finish(f"用法：{SET_USAGE}")

    ok = await UserAccount.set_skin(uid, id.result.strip())
    await set_cmd.finish(
        "立绘切换成功"
        if ok
        else "你还没有这个立绘"
    )


@query_cmd.handle()
async def handle_query_base(result: Arparma):
    if not result.subcommands:
        await query_cmd.finish(f"用法：{QUERY_USAGE}")


@query_cmd.assign("chara")
async def _query_skin_list():
    from ...registry import SKIN_MAP, SKIN_PRICE_MAP

    if not SKIN_MAP:
        await query_cmd.finish("当前没有可用的立绘")

    lines = [
        f"{key} : {path.name}（价格 {SKIN_PRICE_MAP.get(key, 0)}）"
        for key, path in SKIN_MAP.items()
    ]
    await query_cmd.finish("可用立绘列表：\n" + "\n".join(lines))


@query_cmd.assign("data")
async def _query_profile(event: MessageEvent):
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname or uid

    from nonebot_plugin_datastore import create_session

    from ...db.services import UserService
    from ...render.utils import render_sign_card

    try:
        async with create_session() as session:
            user, sign = await UserService.get_user_data(session, uid)

        image_data = await render_sign_card(
            user_name=username,
            user=user,
            sign=sign,
            reward_data=None,
        )
        await query_cmd.finish(UniMessage(Image(raw=image_data)))
    except Exception as e:
        await query_cmd.finish(f"资料查询失败：{str(e)}")


@shop_cmd.handle()
async def _handle_shop_root(result: Arparma):
    if not result.subcommands:
        await shop_cmd.finish(SHOP_USAGE)


@shop_cmd.assign("help")
async def _shop_help():
    await shop_cmd.finish(SHOP_USAGE)


@shop_cmd.assign("list")
async def _shop_list(event: MessageEvent):
    uid = event.get_user_id()
    message, current_page, total_pages = await _build_shop_page(uid, 1)
    send_result = await shop_cmd.send(
        message + _build_shop_page_text(current_page, total_pages),
        reply_message=True,
    )
    _store_shop_page_session(
        _extract_message_id(send_result),
        uid,
        current_page,
        total_pages,
    )


@shop_cmd.assign("buy")
async def _shop_buy_skin(event: MessageEvent, item_id: Match[str]):
    uid = event.get_user_id()
    if not item_id.available or not item_id.result.strip():
        await shop_cmd.finish(f"用法：{SHOP_USAGE}")
    if not item_id.result.strip().isdigit():
        await shop_cmd.finish("参数无效，请输入商品编号")

    ok, message = await UserAccount.buy_shop_item(uid, int(item_id.result.strip()))
    await shop_cmd.finish(message if ok else f"购买失败：{message}")


@shop_page_reply.handle()
async def _handle_shop_page_reply(event: MessageEvent):
    if not event.reply:
        return

    _prune_shop_page_sessions()
    session = shop_page_sessions.get(event.reply.message_id)
    if session is None:
        return
    if event.get_user_id() != session.user_id:
        return

    text = event.get_plaintext().strip()
    target_page, invalid_page = _parse_page_command(text, session.current_page, session.total_pages)
    if target_page is None:
        if invalid_page:
            await shop_page_reply.send(
                f"页码无效，当前共 {session.total_pages} 页",
                reply_message=True,
            )
        return

    message, current_page, total_pages = await _build_shop_page(session.user_id, target_page)
    send_result = await (
        message + "\n" + _build_shop_page_text(current_page, total_pages)
    ).send(
        target=event,
        reply_to=True,
    )
    _store_shop_page_session(
        _extract_message_id(send_result),
        session.user_id,
        current_page,
        total_pages,
    )
