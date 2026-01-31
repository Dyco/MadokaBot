from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment # 导入 MessageSegment
from nonebot.plugin import PluginMetadata
from nonebot.params import CommandArg
from .utils import SET_COMMANDS

__plugin_meta__ = PluginMetadata(
    name="通用插件",
    description="通用的插件内容，包含一些常用指令",
    usage="使用设置命令，调整皮肤/立绘/背景等等",
    type="application",
)

# 设置相关
user_set = on_command("设置", block=True, priority=10)

@user_set.handle()
async def _(event: MessageEvent, arg=CommandArg()):
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname
    
    text = arg.extract_plain_text().strip()
    parts = text.split()

    if not parts:
        menu = ["设置菜单："]
        for cmd in SET_COMMANDS.values():
            if "设置" in cmd.usage: # 过滤只显示设置类
                menu.append(cmd.usage)
        await user_set.finish("\n".join(menu))

    key = parts[0]
    args = parts[1:]

    cmd = SET_COMMANDS.get(key)
    if not cmd:
        await user_set.finish("未知设置项，使用 /设置 查看可用命令")
        
    msg = await cmd.handler(uid, username, args)
    await user_set.finish(msg)

# 查询相关
user_query = on_command("查询", block=True, priority=10)

@user_query.handle()
async def _(event: MessageEvent, arg=CommandArg()):
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname
    
    text = arg.extract_plain_text().strip()
    parts = text.split()
    
    if not parts:
        menu = ["查询菜单："]
        for cmd in SET_COMMANDS.values():
            if "查询" in cmd.usage: 
                menu.append(cmd.usage)
        await user_query.finish("\n".join(menu))

    key = parts[0]
    args = parts[1:]

    cmd = SET_COMMANDS.get(key)
    if not cmd:
        await user_query.finish("未知查询，使用 /查询 查看可用命令")

    msg = await cmd.handler(uid, username, args)
    
    if isinstance(msg, MessageSegment):
        await user_query.finish(msg)
    else:
        await user_query.finish(str(msg))