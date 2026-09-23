"""Steam 昵称、群资料与播报开关。"""

from io import BytesIO

import httpx
from PIL import Image as PILImage
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.log import logger
from nonebot_plugin_alconna import Match, MsgTarget

from ..config import get_query_proxy
from ..matchers import BIND_PERMISSION, steam_cmd
from ..state import steam_groups


@steam_cmd.assign("nickname")
async def handle_nickname(target: MsgTarget, event: Event, name: Match[str]):
    """设置或删除当前用户的 Steam 昵称备注。"""
    if not name.available:
        await steam_cmd.finish("请输入昵称")

    parent_id = target.parent_id or target.id
    nickname = None if name.result == "删除" else name.result
    if not steam_groups.set_nickname(parent_id, event.get_user_id(), nickname):
        await steam_cmd.finish("未绑定 Steam ID")

    if nickname is None:
        await steam_cmd.finish("昵称备注已成功移除")

    await steam_cmd.finish(f"昵称已设置为：{name.result}")


@steam_cmd.assign("enable")
async def handle_enable(bot: Bot, event: GroupMessageEvent, target: MsgTarget):
    """由管理员启用当前群的 Steam 播报。"""
    if not await BIND_PERMISSION(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")
    steam_groups.set_broadcast_enabled(target.parent_id or target.id, True)
    await steam_cmd.finish("已启用 Steam 播报")


@steam_cmd.assign("disable")
async def handle_disable(bot: Bot, event: GroupMessageEvent, target: MsgTarget):
    """由管理员禁用当前群的 Steam 播报。"""
    if not await BIND_PERMISSION(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")
    steam_groups.set_broadcast_enabled(target.parent_id or target.id, False)
    await steam_cmd.finish("已禁用 Steam 播报")


@steam_cmd.assign("update")
async def handle_update_group(bot: Bot, target: MsgTarget):
    """读取并保存当前群的群名和头像。"""
    parent_id = target.parent_id or target.id

    try:
        group_id = int(parent_id)
        group_info = await bot.get_group_info(group_id=group_id)
        avatar_url = f"https://p.qlogo.cn/gh/{group_id}/{group_id}/640"
        async with httpx.AsyncClient(
            proxy=get_query_proxy(), trust_env=False
        ) as client:
            resp = await client.get(avatar_url)
            resp.raise_for_status()
            avatar = PILImage.open(BytesIO(resp.content))
        name = group_info.get("group_name")
    except Exception as e:
        logger.error(f"读取群信息失败: {e}")
        await steam_cmd.finish("无法获取群头像或群名称")

    steam_groups.update_group_profile(parent_id, avatar, name)
    await steam_cmd.finish(f"更新成功，新名称为：{name}")
