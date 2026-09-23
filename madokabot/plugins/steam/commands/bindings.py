"""Steam 账号绑定、解绑与绑定列表。"""

import re

from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger
from nonebot_plugin_alconna import At, Match, MsgTarget

from ..client import get_steam_id, get_steam_users_info
from ..config import get_query_proxy, get_steam_api_key
from ..matchers import BIND_PERMISSION, steam_cmd
from ..state import steam_groups


async def get_bind_list_message(bot: Bot, parent_id: str) -> str:
    """读取群成员称呼并生成当前群绑定列表。"""
    all_binds = steam_groups.list_bindings(parent_id)
    if not all_binds:
        return "本群暂无任何绑定记录。"

    msg = "当前群内绑定列表：\n"
    for data in all_binds:
        u_id = data["user_id"]
        s_id = data["steam_id"]
        try:
            member_info = await bot.get_group_member_info(
                group_id=int(parent_id), user_id=int(u_id)
            )
            name = member_info.get("card") or member_info.get("nickname") or u_id
        except Exception:
            name = u_id
        msg += f"- {name} ({u_id}) -> {s_id}\n"
    return msg.strip()


@steam_cmd.assign("bind")
async def handle_bind(
    bot: Bot,
    event: GroupMessageEvent,
    target: MsgTarget,
    id: Match[str],
):
    """为发送者绑定 Steam 账号并检查群内重复绑定。"""
    await steam_cmd.send("收到指令，正在绑定…")

    if not id.available or not id.result.isdigit():
        await steam_cmd.finish("参数无效，请检查 Steam64 ID 或好友码是否正确")

    steam_id = get_steam_id(id.result)
    if steam_id is None:
        await steam_cmd.finish("Steam ID 格式错误。")

    parent_id = target.parent_id or target.id
    user_id = str(event.user_id)

    if existing_bind := steam_groups.get_binding_by_steam_id(parent_id, steam_id):
        if str(existing_bind.get("user_id")) != user_id:
            await steam_cmd.finish(
                f"绑定失败：该 Steam ID 已被群成员 {existing_bind['user_id']} 占用"
            )

    try:
        member_info = await bot.get_group_member_info(
            group_id=int(parent_id), user_id=int(user_id)
        )
        qq_name = member_info.get("card") or member_info.get("nickname") or user_id
    except Exception as e:
        logger.warning(f"无法获取群成员信息: {e}")
        qq_name = user_id

    steam_name = "未知玩家"
    try:
        api_key = get_steam_api_key()
        if api_key:
            info = await get_steam_users_info([steam_id], api_key, get_query_proxy())
            players = info.get("response", {}).get("players", [])
            if players:
                steam_name = players[0].get("personaname", steam_id)
        else:
            logger.error("未配置 Steam API Key，无法获取昵称")
    except Exception as e:
        logger.error(f"获取 Steam 昵称失败: {e}")

    try:
        steam_groups.bind(parent_id, user_id, steam_id)
    except ValueError as exc:
        await steam_cmd.finish(f"绑定失败：{exc}")
    await steam_cmd.finish(
        f"已为 {qq_name} 绑定 Steam：{steam_name}\nSteam ID：{steam_id}"
    )


@steam_cmd.assign("unbind")
async def handle_unbind(bot: Bot, event: GroupMessageEvent):
    """解除发送者在当前群的 Steam 绑定。"""
    user_id = str(event.user_id)
    parent_id = str(event.group_id)
    if steam_groups.unbind(parent_id, user_id):
        await steam_cmd.finish("解绑成功")
    await steam_cmd.finish("你当前尚未绑定 Steam ID。")


@steam_cmd.assign("add")
async def handle_add_other(
    bot: Bot,
    event: GroupMessageEvent,
    target: Match[At | str],
    steam_id: Match[str],
):
    """由管理员为指定群成员绑定 Steam 账号。"""
    if not await BIND_PERMISSION(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")

    if not target.available:
        await steam_cmd.finish("请指定目标用户（At 或 QQ 号）。")

    res = target.result
    target_qq = res.target if isinstance(res, At) else "".join(re.findall(r"\d+", res))
    await steam_cmd.send("收到指令，正在尝试添加…")

    if not target_qq:
        await steam_cmd.finish("参数无效，请检查 QQ 号是否正确。")

    if not steam_id.available or not steam_id.result.strip():
        await steam_cmd.finish("参数无效，请检查 Steam64 ID 或好友码是否正确")

    s_id = get_steam_id(steam_id.result.strip())
    if s_id is None or not s_id.isdigit():
        await steam_cmd.finish("Steam ID 格式错误。")

    parent_id = str(event.group_id)
    if existing_bind := steam_groups.get_binding_by_steam_id(parent_id, s_id):
        if str(existing_bind.get("user_id")) != target_qq:
            await steam_cmd.finish(
                f"绑定失败：该 Steam ID 已被群成员 {existing_bind['user_id']} 占用"
            )

    try:
        member_info = await bot.get_group_member_info(
            group_id=int(parent_id), user_id=int(target_qq)
        )
        qq_name = member_info.get("card") or member_info.get("nickname") or target_qq
    except Exception:
        qq_name = target_qq

    steam_name = "未知玩家"
    try:
        api_key = get_steam_api_key()
        if api_key:
            info = await get_steam_users_info([s_id], api_key, get_query_proxy())
            players = info.get("response", {}).get("players", [])
            if players:
                steam_name = players[0].get("personaname", s_id)
        else:
            logger.error("未配置 Steam API Key，无法获取昵称")
    except Exception as e:
        logger.error(f"获取 Steam 昵称失败: {e}")

    try:
        steam_groups.bind(parent_id, target_qq, s_id)
    except ValueError as exc:
        await steam_cmd.finish(f"绑定失败：{exc}")
    await steam_cmd.finish(
        f"为用户 {qq_name} ({target_qq}) 绑定 Steam 成功\n{steam_name} ({s_id})"
    )


@steam_cmd.assign("list")
async def handle_list(bot: Bot, event: GroupMessageEvent):
    """发送当前群的 Steam 绑定列表。"""
    parent_id = str(event.group_id)
    msg = await get_bind_list_message(bot, parent_id)
    await steam_cmd.finish(msg)


@steam_cmd.assign("remove")
async def handle_remove(
    bot: Bot,
    event: GroupMessageEvent,
    target: Match[At | str],
):
    """由管理员移除指定群成员的 Steam 绑定。"""
    parent_id = str(event.group_id)

    if not await BIND_PERMISSION(bot, event):
        await steam_cmd.finish("权限不足，只有管理员可以使用删除功能。")

    if not target.available:
        msg = await get_bind_list_message(bot, parent_id)
        await steam_cmd.finish(f"请指定要删除的用户。\n{msg}")

    res = target.result
    target_qq = res.target if isinstance(res, At) else "".join(re.findall(r"\d+", res))
    if not target_qq:
        await steam_cmd.finish("无法识别该用户。")

    if steam_groups.unbind(parent_id, target_qq):
        await steam_cmd.finish(f"已成功移除用户 {target_qq} 的绑定数据。")
    await steam_cmd.finish(f"用户 {target_qq} 在本群没有绑定数据。")
