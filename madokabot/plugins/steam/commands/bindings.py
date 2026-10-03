"""Steam 全局绑定和按群订阅指令。"""

from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import At, Match

from ..bindings import (
    bind_user,
    hide_user,
    list_group_bindings,
    online_user,
    unbind_user,
)
from ..client import get_steam_id, get_steam_users_info
from ..config import get_query_proxy, get_steam_api_key
from ..matchers import BIND_PERMISSION, steam_cmd


def _target_qq(value: At | str) -> str:
    """从 At 或纯数字参数取得 QQ 号。"""
    if isinstance(value, At):
        return str(value.target)
    return value.strip() if value.strip().isdigit() else ""


def _steam_id(value: str) -> str | None:
    """把 Steam64 ID 或好友码转换为统一的 Steam ID。"""
    return get_steam_id(value.strip()) if value.strip().isdigit() else None


async def _steam_name(steam_id: str) -> str:
    """仅在新增全局绑定时尝试查询玩家昵称。"""
    api_key = get_steam_api_key()
    if not api_key:
        return steam_id
    try:
        info = await get_steam_users_info([steam_id], api_key, get_query_proxy())
        players = info.get("response", {}).get("players", [])
        return (players[0].get("personaname") or steam_id) if players else steam_id
    except Exception:
        return steam_id


async def get_bind_list_message(bot: Bot, group_id: str) -> str:
    """列出当前群订阅，包含已隐藏用户。"""
    bindings = await list_group_bindings(group_id)
    if not bindings:
        return "本群暂无任何绑定记录。"

    lines = ["当前群内绑定列表："]
    for binding in bindings:
        user_id = binding["user_id"]
        try:
            member = await bot.get_group_member_info(
                group_id=int(group_id), user_id=int(user_id)
            )
            name = member.get("card") or member.get("nickname") or user_id
        except Exception:
            name = user_id
        suffix = "（本群已隐藏）" if not binding["enabled"] else ""
        lines.append(f"- {name} ({user_id}) -> {binding['steam_id']}{suffix}")
    return "\n".join(lines)


@steam_cmd.assign("bind")
async def handle_bind(event: GroupMessageEvent, id: Match[str]):
    """首次绑定全局账号，并加入或恢复当前群订阅。"""
    requested = _steam_id(id.result) if id.available else None
    if id.available and requested is None:
        await steam_cmd.finish("Steam ID 格式错误。")

    group_id = str(event.group_id)
    user_id = str(event.user_id)
    qq_name = event.sender.nickname or user_id
    try:
        steam_id, created = await bind_user(group_id, user_id, requested, qq_name)
    except ValueError as exc:
        await steam_cmd.finish(f"绑定失败：{exc}")

    if created:
        name = await _steam_name(steam_id)
        await steam_cmd.finish(
            f"已绑定 Steam：{name}\nSteam ID：{steam_id}；本群推送已开启，"
            "使用 steam hide 可关闭本群推送。"
        )
    await steam_cmd.finish(
        f"已使用全局绑定 {steam_id}，本群推送已开启，"
        "使用 steam hide 可关闭本群推送。"
    )


@steam_cmd.assign("unbind")
async def handle_unbind(event: GroupMessageEvent):
    """全局解绑，并删除所有群的 Steam 订阅。"""
    if await unbind_user(str(event.user_id)):
        await steam_cmd.finish(
            "已解绑 Steam/CS 共用账号，所有群订阅均已删除，"
            "使用 steam bind <SteamID|好友码> 可重新绑定。"
        )
    await steam_cmd.finish("你尚未绑定 Steam ID。")


@steam_cmd.assign("hide")
async def handle_hide(event: GroupMessageEvent):
    """只隐藏发送者在当前群的自动播报。"""
    if await hide_user(str(event.group_id), str(event.user_id)):
        await steam_cmd.finish(
            "已关闭本群推送，使用 steam online 可开启本群推送。"
        )
    await steam_cmd.finish("你尚未订阅本群 Steam 播报。")


@steam_cmd.assign("online")
async def handle_online(event: GroupMessageEvent):
    """只开启发送者在当前群的自动播报。"""
    if await online_user(str(event.group_id), str(event.user_id)):
        await steam_cmd.finish(
            "已开启本群推送，使用 steam hide 可关闭本群推送。"
        )
    await steam_cmd.finish("你尚未订阅本群 Steam 播报，请先使用 steam bind 绑定。")


@steam_cmd.assign("add")
async def handle_add_other(
    bot: Bot,
    event: GroupMessageEvent,
    target: Match[At | str],
    steam_id: Match[str],
):
    """管理员为用户首次绑定，或把相同的全局绑定加入本群。"""
    if not await BIND_PERMISSION(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")
    if not target.available or not steam_id.available:
        await steam_cmd.finish("请指定目标用户和 Steam ID。")
    user_id = _target_qq(target.result)
    requested = _steam_id(steam_id.result)
    if not user_id or requested is None:
        await steam_cmd.finish("QQ 号或 Steam ID 格式错误。")

    group_id = str(event.group_id)
    try:
        member = await bot.get_group_member_info(
            group_id=event.group_id, user_id=int(user_id)
        )
        qq_name = member.get("nickname") or user_id
    except Exception:
        qq_name = user_id

    try:
        resolved, created = await bind_user(group_id, user_id, requested, qq_name)
    except ValueError as exc:
        await steam_cmd.finish(f"添加失败：{exc}")
    action = "创建了全局绑定并加入" if created else "加入或恢复"
    await steam_cmd.finish(
        f"已为 {qq_name} ({user_id}) {action}本群 Steam 推送：{resolved}。"
        "该用户可使用 steam hide 关闭本群推送。"
    )


@steam_cmd.assign("list")
async def handle_list(bot: Bot, event: GroupMessageEvent):
    """发送当前群的 Steam 订阅列表。"""
    await steam_cmd.finish(await get_bind_list_message(bot, str(event.group_id)))


@steam_cmd.assign("remove")
async def handle_remove(
    bot: Bot,
    event: GroupMessageEvent,
    target: Match[At | str],
):
    """群管理员隐藏本群订阅，超级用户全局解绑。"""
    if not await BIND_PERMISSION(bot, event):
        await steam_cmd.finish("权限不足，只有管理员可以使用删除功能。")
    group_id = str(event.group_id)
    if not target.available:
        await steam_cmd.finish(
            "请指定要删除的用户。\n" + await get_bind_list_message(bot, group_id)
        )
    user_id = _target_qq(target.result)
    if not user_id:
        await steam_cmd.finish("无法识别该用户。")

    if await SUPERUSER(bot, event):
        if await unbind_user(user_id):
            await steam_cmd.finish(
                f"已全局解绑用户 {user_id} 的 Steam/CS 共用账号，并删除所有群订阅。"
                "该用户可使用 steam bind <SteamID|好友码> 重新绑定。"
            )
        await steam_cmd.finish(f"用户 {user_id} 没有全局 Steam 绑定。")

    if await hide_user(group_id, user_id):
        await steam_cmd.finish(
            f"已关闭用户 {user_id} 在本群的 Steam 推送。"
            "该用户可使用 steam online 重新开启本群推送。"
        )
    await steam_cmd.finish(f"用户 {user_id} 在本群没有 Steam 订阅。")
