from dataclasses import dataclass
from typing import Callable, Awaitable, Union, Any
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot_plugin_datastore import create_session
from ...db.user_source import UserAccount
from ...registry import SKIN_MAP
from ...render.utils import render_sign_card
from ...db.models import UserStats, SignRecord 
from ...db.services import UserService

@dataclass
class SetCommand:
    name: str
    usage: str
    handler: Callable[[str, str, list[str]], Awaitable[Union[str, MessageSegment]]]

SET_COMMANDS: dict[str, SetCommand] = {}

def register_set_command(name: str, usage: str):
    def decorator(func):
        SET_COMMANDS[name] = SetCommand(
            name=name,
            usage=usage,
            handler=func
        )
        return func
    return decorator

@register_set_command(name="皮肤", usage="设置 皮肤 <皮肤ID>")
async def handle_set_skin(uid: str, username: str, args: list[str]) -> str:
    if not args:
        return "用法：设置 皮肤 <皮肤ID>"
    skin_key = args[0]
    ok = await UserAccount.set_skin(uid, skin_key)
    return "皮肤切换成功" if ok else "你还没有这个皮肤"

@register_set_command(name="头像", usage="设置 头像 <头像ID>")
async def handle_set_avatar(uid: str, username: str, args: list[str]) -> str:
    if not args:
        return "用法：设置 头像 <头像ID>"
    return f"头像已切换为 {args[0]}"

@register_set_command(name="立绘", usage="查询 立绘")
async def handle_query_skin(uid: str, username: str, args: list[str]) -> str:
    if not SKIN_MAP:
        return "当前没有可用的立绘"
    lines = [f"{key} : {path.name}" for key, path in SKIN_MAP.items()]
    return "可用立绘列表：\n" + "\n".join(lines)

@register_set_command(name="资料", usage="查询 资料")
async def handle_query_profile(uid: str, username: str, args: list[str]) -> Union[str, MessageSegment]:
    
    async with create_session() as session:
        user, sign = await UserService.get_user_data(session, uid)

    user.nickname = username 
    
    try:
        msg = await render_sign_card(
            user_name=username,  
            user=user,          
            sign=sign,           
            reward_data=None     
        )
        return msg
    except Exception as e:
        return f"渲染失败：{str(e)}"