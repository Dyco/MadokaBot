"""Steam 群备注与群总播报开关。"""

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot_plugin_alconna import Match, MsgTarget

from ..bindings import set_group_nickname
from ..matchers import BIND_PERMISSION, steam_cmd
from ..state import steam_groups


@steam_cmd.assign("nickname")
async def handle_nickname(target: MsgTarget, event: Event, name: Match[str]):
    """设置或删除当前用户的 Steam 昵称备注。"""
    if not name.available:
        await steam_cmd.finish("请输入昵称")

    parent_id = target.parent_id or target.id
    nickname = None if name.result == "删除" else name.result
    if not await set_group_nickname(parent_id, event.get_user_id(), nickname):
        await steam_cmd.finish("未绑定 Steam ID")

    if nickname is None:
        await steam_cmd.finish(
            "昵称备注已移除，使用 steam nickname <昵称> 可重新设置。"
        )

    await steam_cmd.finish(
        f"昵称已设置为：{name.result}，使用 steam nickname 删除 可移除备注。"
    )


@steam_cmd.assign("enable")
async def handle_enable(bot: Bot, event: GroupMessageEvent, target: MsgTarget):
    """由管理员启用当前群的 Steam 播报。"""
    if not await BIND_PERMISSION(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")
    steam_groups.set_broadcast_enabled(target.parent_id or target.id, True)
    await steam_cmd.finish(
        "已启用本群 Steam 播报，使用 steam disable 可关闭本群播报。"
    )


@steam_cmd.assign("disable")
async def handle_disable(bot: Bot, event: GroupMessageEvent, target: MsgTarget):
    """由管理员禁用当前群的 Steam 播报。"""
    if not await BIND_PERMISSION(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")
    steam_groups.set_broadcast_enabled(target.parent_id or target.id, False)
    await steam_cmd.finish(
        "已关闭本群 Steam 播报，使用 steam enable 可启用本群播报。"
    )
