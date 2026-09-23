from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_alconna import Arparma, Match
from nonebot_plugin_datastore import create_session

from madokabot.core.user.queries import UserQueries
from madokabot.core.user.accounts import UserAccount
from madokabot.default.shop.service import SkinService
from .render import render_sign_card
from .matchers import QUERY_USAGE, RENAME_USAGE, SET_USAGE, query_cmd, set_cmd
from .service import rename_user


@set_cmd.handle()
async def handle_set_base(result: Arparma):
    """返回账号设置命令的使用说明。"""
    if not result.subcommands:
        await set_cmd.finish(f"用法：{SET_USAGE}")


@set_cmd.assign("chara")
async def _set_skin(event: MessageEvent, skin_id: Match[str]):
    """切换当前账号已拥有的立绘。"""
    uid = event.get_user_id()
    if not await UserAccount.is_registered(uid):
        await set_cmd.finish("请先发送“注册”完成用户注册")

    if not skin_id.available or not skin_id.result.strip():
        await set_cmd.finish(f"用法：{SET_USAGE}")

    _, message = await SkinService.switch_skin(uid, skin_id.result)
    await set_cmd.finish(message)


@set_cmd.assign("rename")
async def _rename(event: MessageEvent, name: Match[str]):
    """处理账号改名，缺少参数时提示名字限制及积分费用。"""
    if not name.available:
        await set_cmd.finish(f"用法：{RENAME_USAGE}")

    _, message = await rename_user(event.get_user_id(), name.result)
    await set_cmd.finish(message)


@query_cmd.handle()
async def handle_query_base(result: Arparma):
    """返回账号查询命令的使用说明。"""
    if not result.subcommands:
        await query_cmd.finish(f"用法：{QUERY_USAGE}")


@query_cmd.assign("chara")
async def _query_skin_list(event: MessageEvent):
    """列出账号持有的立绘。"""
    uid = event.get_user_id()
    if not await UserAccount.is_registered(uid):
        await query_cmd.finish("请先发送“注册”完成用户注册")

    owned_skins = await SkinService.get_owned_skin_list(uid)
    if not owned_skins:
        await query_cmd.finish("你还没有可用立绘，请前往商店购买")

    lines = [
        f"{'[使用中] ' if skin['current'] else ''}{skin['item_key']}："
        f"{skin['asset_name']}"
        for skin in owned_skins
    ]
    await query_cmd.finish(
        "已拥有立绘：\n" + "\n".join(lines) + "\n\n切换方式：设置 立绘 <立绘ID>"
    )


@query_cmd.assign("data")
async def _query_profile(event: MessageEvent):
    """渲染并发送当前账号的资料卡片。"""
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname or uid

    try:
        async with create_session() as session:
            user, sign = await UserQueries.get_user_data(session, uid)

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
