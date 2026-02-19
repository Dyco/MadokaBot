from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata
from nonebot.params import CommandArg
from .utils import SET_COMMANDS

from nonebot_plugin_alconna import (
    Alconna, 
    Subcommand, 
    Args, 
    on_alconna, 
    Match, 
    UniMessage, 
    Image
)
from nonebot.adapters.onebot.v11 import MessageEvent, GroupMessageEvent
from typing import Union, Optional

__plugin_meta__ = PluginMetadata(
    name="通用插件",
    description="通用的插件内容，包含一些常用指令",
    usage="""
    查询类
    """,
    type="application",
)


# ================= Alconna 命令定义 =================

set_cmd_alc = Alconna(
    "set",["设置"],
    Subcommand("chara", Args["id?", str], alias=["立绘"]),
)

query_cmd_alc = Alconna(
    "query",["查询"],
    Subcommand("chara", alias=["立绘"]),
    Subcommand("data", alias=["资料"]),
)

set_cmd = on_alconna(set_cmd_alc, priority=10, block=True)
query_cmd = on_alconna(query_cmd_alc, priority=10, block=True)

# ================= 设置类处理器 =================

@set_cmd.handle()
async def handle_set_base(event: MessageEvent):
    """
    """
    pass

@set_cmd.assign("立绘")
async def _set_skin(event: MessageEvent, id: Match[str]):
    uid = event.get_user_id()
    if not id.available:
        await set_cmd.finish("用法：设置 立绘 <立绘ID>")
    
    skin_key = id.result
    from ...db.user_source import UserAccount
    ok = await UserAccount.set_skin(uid, skin_key)
    await set_cmd.finish("立绘切换成功" if ok else "你还没有这个立绘")


# ================= 查询类处理器 =================
@query_cmd.handle()
async def handle_query_base(event: MessageEvent):
    """
    """
    pass


@query_cmd.assign("立绘")
async def _query_skin_list():
    from ...registry import SKIN_MAP
    if not SKIN_MAP:
        await query_cmd.finish("当前没有可用的立绘")
    
    lines = [f"{key} : {path.name}" for key, path in SKIN_MAP.items()]
    await query_cmd.finish("可用立绘列表：\n" + "\n".join(lines))

@query_cmd.assign("资料")
async def _query_profile(event: MessageEvent):
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname or uid
    
    from ...db.services import UserService
    from ...render.utils import render_sign_card
    from nonebot_plugin_datastore import create_session

    try:
        async with create_session() as session:
            user, sign = await UserService.get_user_data(session, uid)
        
        # 调用渲染函数
        image_data = await render_sign_card(
            user_name=username,
            user=user,
            sign=sign,
            reward_data=None
        )
        
        # Alconna 使用 UniMessage 可以自动适配多种适配器
        await query_cmd.finish(UniMessage(Image(raw=image_data)))
    except Exception as e:
        await query_cmd.finish(f"资料查询失败：{str(e)}")

# ================= 兜底逻辑 (显示菜单) =================

@set_cmd.handle()
@query_cmd.handle()
async def _handle_menu(result):
    """
    当用户只输入 '设置' 或 '查询'，或者输入错误子命令时，
    result.subcommands 会为空，此时返回菜单。
    """
    if not result.subcommands:
        # 你可以根据命令名称动态返回原有的 usage 菜单
        pass