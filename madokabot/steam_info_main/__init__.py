import time
import httpx
import nonebot
import re
from io import BytesIO
from pathlib import Path
from typing import Union, Optional, List, Dict
import asyncio

from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.adapters import Bot, Event, Message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, GROUP_ADMIN, GROUP_OWNER
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot.permission import SUPERUSER

from PIL import Image as PILImage

from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_alconna import (
    Alconna,
    Option,
    Args,
    CommandMeta,
    on_alconna,
    Text,
    Image,
    UniMessage,
    Target,
    At,
    MsgTarget,
    Match,
)

import nonebot_plugin_localstore as store

from .config import Config
from .models import ProcessedPlayer
from .data_source import BindData, SteamInfoData, ParentData, DisableParentData
from .steam import (
    get_steam_id,
    get_user_data,
    STEAM_ID_OFFSET,
    get_steam_users_info,
    get_steam_users_info_cached,
    STEAM_USER_CACHE_TTL
)
from .draw import (
    draw_start_gaming,
    draw_player_status,
    draw_friends_status,
    vertically_concatenate_images,
)
from .utils import (
    fetch_avatar,
    image_to_bytes,
    simplize_steam_player_data,
    convert_player_name_to_nickname,
)

# ================= 插件元信息 =================

__plugin_meta__ = PluginMetadata(
    name="Steam Info",
    description="播报绑定的 Steam 好友状态",
    usage="""
steam help
steam bind <SteamID|好友码>
steam unbind
steam add <@用户|QQ号> <SteamID|好友码>
steam remove <@用户|QQ号>
steam info [@某人|SteamID|好友码]
steam check
steam enable
steam disable
steam update
steam nickname <昵称>
""".strip(),
    type="application",
    homepage="https://github.com/zhaomaoniu/nonebot-plugin-steam-info",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
)

# ================= 配置 =================

config = nonebot.get_plugin_config(Config)
# 权限组合：管理员、群主或超级管理员
BIND_PERMISSION = GROUP_ADMIN | GROUP_OWNER | SUPERUSER

# ================= 数据 =================

bind_data = BindData(store.get_data_file("nonebot_plugin_steam_info", "bind_data.json"))
steam_info_data = SteamInfoData(
    store.get_data_file("nonebot_plugin_steam_info", "steam_info.json")
)
parent_data = ParentData(
    store.get_data_file("nonebot_plugin_steam_info", "parent_data.json")
)
disable_parent_data = DisableParentData(
    store.get_data_file("nonebot_plugin_steam_info", "disable_parent_data.json")
)

avatar_path = store.get_cache_dir("nonebot_plugin_steam_info")
#
# try:
#     check_font()
# except FileNotFoundError as e:
#     logger.error(f"{e}，字体未配置，插件不可用")

# ================= Alconna 命令定义 =================

steam_command = Alconna(
    "steam",
    Option("help", alias=["帮助"]),
    Option("bind", Args["id", str], alias=["绑定"]),
    Option("add", Args["target", Union[At, str]]["steam_id", str], alias=["添加"]),
    Option("unbind", alias=["解绑"]),
    Option("remove", Args["target", [At, str]], alias=["删除"]),
    Option("info", Args["target?", [At, str]], alias=["信息"]),
    Option("check", alias=["查看","列表"]),
    Option("enable", alias=["启用","开启"]),
    Option("disable", alias=["禁用"]),
    Option("update", alias=["更新群信息", "更新"]),
    Option("nickname", Args["name", str], alias=["昵称","备注"]),
    separators=" ",
    meta=CommandMeta(compact=True),
)

steam_cmd = on_alconna(steam_command, priority=config.steam_command_priority)

# ================= 工具函数 =================

#async def get_target(target: MsgTarget) -> Optional[Target]:
#    if target.private:
#        # 不支持私聊消息
#        return None
#   return target


async def to_image_data(image: Image) -> Union[BytesIO, bytes]:
    if image.raw:
        return image.raw
    if image.path:
        return Path(image.path).read_bytes()
    if image.url:
        async with httpx.AsyncClient() as client:
            resp = await client.get(image.url)
            resp.raise_for_status()
            return resp.content
    raise ValueError("无法获取图片")

# ================= 命令实现 =================

# 帮助菜单
@steam_cmd.assign("help")
async def _( ):
    await steam_cmd.finish(__plugin_meta__.usage)

# 绑定Steam
@steam_cmd.assign("bind")
async def handle_bind(
    bot: Bot,
    event: GroupMessageEvent,
    target: MsgTarget,
    id: Match[str],
):    
    await steam_cmd.send("收到指令，正在绑定…")   
    if not id.available or not id.result.isdigit():
        await steam_cmd.finish("请输入正确的 Steam ID 或好友码")
    steam_id = get_steam_id(id.result)
    parent_id = target.parent_id or target.id
    user_id = str(event.user_id)

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
        if config.steam_api_key:
            info = await get_steam_users_info([steam_id], config.steam_api_key, config.proxy)
            players = info.get("response", {}).get("players", [])
            if players:
                steam_name = players[0].get("personaname", steam_id)
        else:
            logger.error("未配置 Steam API Key，无法获取昵称")
    except Exception as e:
        logger.error(f"获取 Steam 昵称失败: {e}")

    existing_data = bind_data.get(parent_id, user_id)
    if existing_data:
        if isinstance(existing_data, dict):
            existing_data["steam_id"] = steam_id
        else:
            existing_data.steam_id = steam_id
    else:
        bind_data.add(
            parent_id,
            {"user_id": user_id, "steam_id": steam_id, "nickname": None},
        )

    bind_data.save()
    
    await steam_cmd.finish(f"✅{qq_name}已绑定steam【{steam_name}】\nSteam ID：{steam_id}")

# 解绑Steam
@steam_cmd.assign("unbind")
async def handle_unbind(
    bot: Bot,
    event: GroupMessageEvent,
):
    user_id = str(event.user_id)
    parent_id = str(event.group_id)
    if bind_data.get(parent_id, user_id):
        bind_data.remove(parent_id, user_id)
        bind_data.save()
        await steam_cmd.finish("解绑成功！")
    else:
        await steam_cmd.finish("你当前尚未绑定 Steam ID。")

# 添加数据（仅限管理员）
@steam_cmd.assign("add")
async def handle_add_other(
    bot: Bot,
    event: GroupMessageEvent,
    target: Match[At | str], 
    steam_id: Match[str]
):
    if not await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")

    if not target.available:
        await steam_cmd.finish("请指定目标用户（At 或 QQ号）。")
    
    res = target.result
    target_qq = res.target if isinstance(res, At) else "".join(re.findall(r"\d+", res))
    await steam_cmd.send("收到指令，正在尝试添加…")
    if not target_qq:
        await steam_cmd.finish("无法识别目标用户。")

    if not steam_id.available or not steam_id.result.strip():
        await steam_cmd.finish("请提供 Steam ID 或好友码。")
    

    raw_id = steam_id.result.strip()
    s_id = get_steam_id(raw_id) 

    if not s_id.isdigit():
        await steam_cmd.finish("Steam ID 格式错误。")

    parent_id = str(event.group_id)

    if existing_bind := bind_data.get_by_steam_id(parent_id, s_id):
        if str(existing_bind.get("user_id")) != target_qq:
            await steam_cmd.finish(
                f"绑定失败：该 Steam ID 已被群成员 {existing_bind['user_id']} 占用"
            )

    try:
        member_info = await bot.get_group_member_info(group_id=int(parent_id), user_id=int(target_qq))
        qq_name = member_info.get("card") or member_info.get("nickname") or target_qq
    except Exception:
        qq_name = target_qq

    steam_name = "未知玩家"
    try:
        if config.steam_api_key:

            info = await get_steam_users_info([s_id], config.steam_api_key, config.proxy)
            players = info.get("response", {}).get("players", [])
            if players:
                steam_name = players[0].get("personaname", s_id)
        else:
            logger.error("未配置 Steam API Key，无法获取昵称")
    except Exception as e:
        logger.error(f"获取 Steam 昵称失败: {e}")

    existing_data = bind_data.get(parent_id, target_qq)
    if existing_data:

        if isinstance(existing_data, dict):
            existing_data["steam_id"] = s_id
        else:
            existing_data.steam_id = s_id
    else:
        bind_data.add(parent_id, {"user_id": target_qq, "steam_id": s_id, "nickname": None})
    
    bind_data.save()
    await steam_cmd.finish(f"为用户：{qq_name} ({target_qq})绑定Steam：成功\n{steam_name} ({s_id})")

# 移除数据（仅限管理员）    
@steam_cmd.assign("remove")
async def handle_remove(
    bot: Bot,
    event: GroupMessageEvent,
    target: Match[At | str]
):
    parent_id = str(event.group_id)

    # --- 权限校验：必须是管理、群主或超管 ---
    if not await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event):
        await steam_cmd.finish("权限不足，只有管理员可以使用删除功能。")

    if not target.available:
        all_binds = bind_data.content.get(parent_id, [])
        if not all_binds:
            await steam_cmd.finish(" can't find any data：本群暂无任何绑定记录。")

        msg = "当前群内绑定列表：\n"
        for data in all_binds:
            u_id = data["user_id"]
            s_id = data["steam_id"]
            try:
                member_info = await bot.get_group_member_info(group_id=int(parent_id), user_id=int(u_id))
                name = member_info.get("card") or member_info.get("nickname") or u_id
            except:
                name = u_id
            
            msg += f"• {name} ({u_id}) -> {s_id}\n"
        
        await steam_cmd.finish(msg.strip())

    res = target.result
    target_qq = res.target if isinstance(res, At) else "".join(re.findall(r"\d+", res))

    if not target_qq:
        await steam_cmd.finish("无法识别该用户。")

    if bind_data.get(parent_id, target_qq):
        bind_data.remove(parent_id, target_qq)
        bind_data.save()
        await steam_cmd.finish(f"已成功移除用户{target_qq}的绑定数据。")
    else:
        await steam_cmd.finish(f"用户{target_qq}在本群没有绑定数据。")

# 添加备注
@steam_cmd.assign("nickname")
async def _(target : MsgTarget, event: Event, name: Match[str]):
    if not name.available:
        await steam_cmd.finish("请输入昵称")

    parent_id = target.parent_id or target.id
    data = bind_data.get(parent_id, event.get_user_id())
    if not data:
        await steam_cmd.finish("未绑定 Steam ID")
        
    if name.result == "删除":
        data["nickname"] = None 
        data.pop("nickname", None)
        
        bind_data.save()
        await steam_cmd.finish("昵称备注已成功移除")

    data["nickname"] = name.result
    bind_data.save()
    await steam_cmd.finish(f"昵称已设置为：{name.result}")

# 启用播报
@steam_cmd.assign("enable")
async def _(bot: Bot,event: GroupMessageEvent, target : MsgTarget):
    if not await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")
    disable_parent_data.remove(target.parent_id or target.id)
    disable_parent_data.save()
    await steam_cmd.finish("已启用 Steam 播报")

# 禁用播报
@steam_cmd.assign("disable")
async def _(bot: Bot,event: GroupMessageEvent, target : MsgTarget):
    if not await (GROUP_ADMIN | GROUP_OWNER | SUPERUSER)(bot, event):
        await steam_cmd.finish("只有群管理员可以使用此功能。")
    disable_parent_data.add(target.parent_id or target.id)
    disable_parent_data.save()
    await steam_cmd.finish("已禁用 Steam 播报")
    
# 更新主用户为群昵称与群头像    
@steam_cmd.assign("update")
async def update_parent_info_handle(
    bot: Bot,
    target : MsgTarget,
):
    parent_id = target.parent_id or target.id

    try:
        group_id = int(parent_id)
        group_info = await bot.get_group_info(group_id=group_id)

        # 群头像
        avatar_url = f"https://p.qlogo.cn/gh/{group_id}/{group_id}/640"
        async with httpx.AsyncClient() as client:
            resp = await client.get(avatar_url)
            resp.raise_for_status()
            avatar = PILImage.open(BytesIO(resp.content))

        # 群名称
        name = group_info.get("group_name")

    except Exception as e:
        logger.error(f"读取群信息失败: {e}")
        await steam_cmd.finish("无法获取群头像或群名称")

    parent_data.update(parent_id, avatar, name)
    await steam_cmd.finish(f"更新成功，新名称为 {name}")

# 查看Steam列表
@steam_cmd.assign("check")
async def _(target : MsgTarget):
    parent_id = target.parent_id or target.id
    steam_ids = bind_data.get_all(parent_id)
    
    if not steam_ids:
        await steam_cmd.finish("当前群聊未绑定任何 Steam 账号")
        
    await steam_cmd.send("收到指令，正在尝试读取…")
    try:
        info = await get_steam_users_info(
            steam_ids, config.steam_api_key, config.proxy
        )
    except Exception as e:
        logger.error(f"Steam API 调用失败: {e}")
        await steam_cmd.finish("无法连接到 Steam API，请检查网络或 API Key")

    if not info.get("response", {}).get("players"):
        await steam_cmd.finish("未查找到玩家信息")

    tasks = [
        simplize_steam_player_data(p, config.proxy, avatar_path) 
        for p in info["response"]["players"]
    ]
    
    try:
        player_results = await asyncio.gather(*tasks)
    except Exception as e:
        logger.error(f"处理玩家数据时崩溃: {e}")
        await steam_cmd.finish("处理头像数据时出错")

    parent_avatar, parent_name = parent_data.get(parent_id)
    
    data = [
        convert_player_name_to_nickname(res, parent_id, bind_data)
        for res in player_results
    ]

    image = draw_friends_status(parent_avatar, parent_name, data)
    await target.send(UniMessage(Image(raw=image_to_bytes(image))))

# 查看info
@steam_cmd.assign("info")
async def handle_info(
    bot: Bot,
    event: GroupMessageEvent,
    target: Match[At | str],
):
    parent_id = str(event.group_id)
    sender_id = str(event.user_id)
    
    steam_id = None

    if target.available:
        res = target.result
        if isinstance(res, At):
            target_qq = res.target
        else:
            target_qq = "".join(re.findall(r"\d+", res.strip()))
        
        if not target_qq:
            await steam_cmd.finish("❌ 无法识别的参数，请输入 QQ 号或 At 某人")

        user_data = bind_data.get(parent_id, target_qq)
        if not user_data:
            await steam_cmd.finish(f"❌ 该用户 ({target_qq}) 尚未在群内绑定 Steam")
        
        steam_id = user_data["steam_id"]
    else:
        user_data = bind_data.get(parent_id, sender_id)
        if not user_data:
            await steam_cmd.finish("❌ 你尚未绑定 Steam，请使用 `steam bind ID` 绑定")
        
        steam_id = user_data["steam_id"]
    await steam_cmd.send("收到指令，正在尝试读取…")
        
    try:
        player_data = await get_user_data(steam_id, avatar_path, config.proxy)
    except Exception as e:
        logger.error(f"获取玩家详情失败: {e}")
        await steam_cmd.finish("❌ 获取 Steam 数据失败，可能 API 超时或 ID 无效")
    steam_friend_code = str(int(steam_id) - STEAM_ID_OFFSET)
    draw_data = [
        {
            "game_header": game.get("game_image"),
            "game_name": game.get("game_name", "未知游戏"),
            "game_time": f"{game.get('play_time', 0)} 小时",
            "last_play_time": game.get("last_played", "未知"),
            "achievements": game.get("achievements", []),
            "completed_achievement_number": game.get("completed_achievement_number", 0),
            "total_achievement_number": game.get("total_achievement_number", 0),
        }
        for game in player_data.get("game_data", [])
    ]
    try:
        image = draw_player_status(
            player_data["background"],
            player_data["avatar"],
            player_data["player_name"],
            steam_friend_code,
            player_data.get("description", ""),
            player_data.get("recent_2_week_play_time", "0"),
            draw_data,
        )   
    except Exception as e:
        logger.error(f"存在错误：{e}")
        await steam_cmd.finish("❌ 绘图失败，部分数据可能存在异常")
        
    await steam_cmd.finish(UniMessage(Image(raw=image_to_bytes(image))))

# ================= 定时任务 =================

async def update_steam_info():
    bind_map = {
        pid: bind_data.get_all(pid)
        for pid in bind_data.content.keys()
    }

    steam_ids = {
        steam_id
        for ids in bind_map.values()
        for steam_id in ids
    }

    steam_info = await get_steam_users_info_cached(
        list(steam_ids),
        config.steam_api_key,
        config.proxy,
        STEAM_USER_CACHE_TTL
    )

    old = {
        pid: steam_info_data.get_players(ids)
        for pid, ids in bind_map.items()
    }

    if steam_info["response"]["players"]:
        steam_info_data.update_by_players(
            steam_info["response"]["players"]
        )
        steam_info_data.save()

    return old


@scheduler.scheduled_job(
    "interval", minutes=config.steam_request_interval / 60
)
async def _():
    old = await update_steam_info()
    for pid, old_players in old.items():
        new_players = steam_info_data.get_players(bind_data.get_all(pid))
        await broadcast_steam_info(pid, old_players, new_players)

async def broadcast_steam_info(
    parent_id: str,
    old_players: List[ProcessedPlayer],
    new_players: List[ProcessedPlayer],
):
    if disable_parent_data.is_disabled(parent_id):
        return None

    bot = nonebot.get_bot()
    play_data = steam_info_data.compare(old_players, new_players)

    msg = []

    for entry in play_data:
        player = entry["player"]
        old_player = entry.get("old_player")

        if entry["type"] == "start":
            msg.append(
                f"{player['personaname']} 开始玩 {player['gameextrainfo']} 了"
            )

        elif entry["type"] in ("stop", "change"):
            time_start = old_player["game_start_time"]
            time_stop = time.time()
            hours = int((time_stop - time_start) / 3600)
            minutes = int((time_stop - time_start) % 3600 / 60)

            time_str = (
                f"{hours} 小时 {minutes} 分钟"
                if hours > 0
                else f"{minutes} 分钟"
            )

            if entry["type"] == "change":
                msg.append(
                    f"{player['personaname']} 玩了 {time_str} "
                    f"{old_player['gameextrainfo']} 后，开始玩 "
                    f"{player['gameextrainfo']} 了"
                )
            else:
                msg.append(
                    f"{player['personaname']} 玩了 {time_str} "
                    f"{old_player['gameextrainfo']} 后不玩了"
                )

    if not msg:
        return None

    # ===== part 模式 =====
    if config.steam_broadcast_type == "part":
        avatar_cache: Dict[str, bytes] = {}
        images = []

        for entry in play_data:
            if entry["type"] not in ("start", "change"):
                continue

            steamid = entry["player"]["steamid"]

            if steamid in avatar_cache:
                avatar = avatar_cache[steamid]
            else:
                avatar = await fetch_avatar(
                    entry["player"], avatar_path, config.proxy
                )
                avatar_cache[steamid] = avatar

            img = draw_start_gaming(
                avatar,
                entry["player"]["personaname"],
                entry["player"]["gameextrainfo"],
                bind_data.get_by_steam_id(
                    parent_id, steamid
                )["nickname"],
            )
            images.append(img)

        if images:
            image = (
                vertically_concatenate_images(images)
                if len(images) > 1
                else images[0]
            )
            uni_msg = UniMessage(
                [Text("\n".join(msg)), Image(raw=image_to_bytes(image))]
            )
        else:
            uni_msg = UniMessage([Text("\n".join(msg))])

    elif config.steam_broadcast_type == "none":
        uni_msg = UniMessage([Text("\n".join(msg))])

    else:
        logger.error(
            f"未知的播报类型: {config.steam_broadcast_type}"
        )
        return None

    await uni_msg.send(
        Target(parent_id, parent_id, True, False, "", bot.adapter.get_name()),
        bot,
    )