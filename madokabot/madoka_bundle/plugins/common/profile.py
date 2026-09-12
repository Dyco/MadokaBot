from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import Arparma, Match
from nonebot_plugin_datastore import create_session

from ...db.services import UserService
from ...db.user_source import UserAccount
from ...render.utils import render_sign_card
from .matchers import QUERY_USAGE, SET_USAGE, query_cmd, set_cmd


@set_cmd.handle()
async def handle_set_base(result: Arparma):
    if not result.subcommands:
        await set_cmd.finish(f"用法：{SET_USAGE}")


@set_cmd.assign("chara")
async def _set_skin(event: MessageEvent, skin_id: Match[str]):
    uid = event.get_user_id()
    if not await UserAccount.is_registered(uid):
        await set_cmd.finish("请先发送“注册”完成用户注册")

    if not skin_id.available or not skin_id.result.strip():
        await set_cmd.finish(f"用法：{SET_USAGE}")

    _, message = await UserAccount.switch_skin(uid, skin_id.result)
    await set_cmd.finish(message)


@query_cmd.handle()
async def handle_query_base(result: Arparma):
    if not result.subcommands:
        await query_cmd.finish(f"用法：{QUERY_USAGE}")


@query_cmd.assign("chara")
async def _query_skin_list(event: MessageEvent):
    uid = event.get_user_id()
    if not await UserAccount.is_registered(uid):
        await query_cmd.finish("请先发送“注册”完成用户注册")

    owned_skins = await UserAccount.get_owned_skin_list(uid)
    if not owned_skins:
        await query_cmd.finish("你还没有可用立绘，请前往商店购买")

    lines = [
        f"{'[使用中] ' if skin['current'] else ''}{skin['item_key']}："
        f"{skin['asset_name']}"
        for skin in owned_skins
    ]
    await query_cmd.finish(
        "已拥有立绘：\n"
        + "\n".join(lines)
        + "\n\n切换方式：设置 立绘 <立绘ID>"
    )


@query_cmd.assign("data")
async def _query_profile(event: MessageEvent):
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname or uid

    try:
        async with create_session() as session:
            user, sign = await UserService.get_user_data(session, uid)

        image_data = await render_sign_card(
            user_name=username,
            user=user,
            sign=sign,
            reward_data=None,
        )
    except LookupError:
        await query_cmd.finish("请先发送“注册”完成用户注册")
    except Exception:
        logger.exception("生成用户资料失败")
        await query_cmd.finish("资料查询失败，请稍后重试")

    await query_cmd.finish(image_data)
