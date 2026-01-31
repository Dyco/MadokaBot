import time
import pytz
import httpx
import datetime
import calendar
from PIL import Image
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional
from nonebot import logger


from .models import Player
from .constants import *
from .data_source import BindData
from .steam import get_http_client

import time



async def fetch_avatar(
    player: Player, avatar_dir: Optional[Path], proxy: str = None
) -> Image.Image:
    # 使用 .get() 并在缺失时尝试 fallback 到 "avatar" 字段
    url = player.get("avatarfull") or player.get("avatar")
    
    if not url:
        logger.warning(f"玩家 {player.get('steamid')} 缺少头像 URL")
        return Image.open(unknown_avatar_path)

    if avatar_dir is None:
        return await _fetch_avatar(url, proxy)

    avatar_dir.mkdir(parents=True, exist_ok=True)
    avatar_path = avatar_dir / f"avatar_{player['steamid']}.png"

    if avatar_path.exists():
        mtime = avatar_path.stat().st_mtime
        if (time.time() - mtime) < 86400:
            try:
                return Image.open(avatar_path)
            except Exception:
                avatar_path.unlink(missing_ok=True)

    avatar = await _fetch_avatar(url, proxy)
    try:
        avatar.save(avatar_path)
    except Exception as e:
        logger.error(f"保存头像失败: {e}")
            
    return avatar

async def _fetch_avatar(avatar_url: str, proxy: str = None) -> Image.Image:
    client = await get_http_client(proxy) 
    try:
        response = await client.get(avatar_url)
        if response.status_code == 200:
            return Image.open(BytesIO(response.content))
        else:
            logger.warning(f"下载头像失败，状态码: {response.status_code}")
    except Exception as e:
        logger.warning(f"下载头像异常: {avatar_url}, 错误: {e}")
            
    return Image.open(unknown_avatar_path)


def convert_player_name_to_nickname(
    data: Dict[str, str], parent_id: str, bind_data: BindData
) -> Dict[str, str]:
    data["nickname"] = bind_data.get_by_steam_id(parent_id, data["steamid"])["nickname"]
    return data


async def simplize_steam_player_data(
    player: Player, proxy: str = None, avatar_dir: Path = None
) -> Dict[str, str]:
    avatar = await fetch_avatar(player, avatar_dir, proxy)

    if player["personastate"] == 0:
        if not player.get("lastlogoff"):
            status = "离线"
        else:
            time_logged_off = player["lastlogoff"]  # Unix timestamp
            time_to_now = calendar.timegm(time.gmtime()) - time_logged_off

            # 将时间转换为自然语言
            if time_to_now < 60:
                status = "上次在线 刚刚"
            elif time_to_now < 3600:
                status = f"上次在线 {time_to_now // 60} 分钟前"
            elif time_to_now < 86400:
                status = f"上次在线 {time_to_now // 3600} 小时前"
            elif time_to_now < 2592000:
                status = f"上次在线 {time_to_now // 86400} 天前"
            elif time_to_now < 31536000:
                status = f"上次在线 {time_to_now // 2592000} 个月前"
            else:
                status = f"上次在线 {time_to_now // 31536000} 年前"
    elif player["personastate"] in [1, 2, 4]:
        status = (
            "在线" if player.get("gameextrainfo") is None else player["gameextrainfo"]
        )
    elif player["personastate"] == 3:
        status = (
            "离开" if player.get("gameextrainfo") is None else player["gameextrainfo"]
        )
    elif player["personastate"] in [5, 6]:
        status = "在线"
    else:
        status = "未知"

    return {
        "steamid": player["steamid"],
        "avatar": avatar,
        "name": player["personaname"],
        "status": status,
        "personastate": player["personastate"],
    }


def image_to_bytes(image: Image.Image) -> bytes:
    with BytesIO() as bio:
        image.save(bio, format="PNG")
        return bio.getvalue()


def hex_to_rgb(hex_color: str):
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def convert_timestamp_to_beijing_time(timestamp: int) -> str:
    beijing_timezone = pytz.timezone("Asia/Shanghai")
    date_utc = datetime.datetime.fromtimestamp(timestamp, pytz.utc)
    date_beijing = date_utc.astimezone(beijing_timezone)
    return date_beijing.strftime("%Y-%m-%d %H:%M:%S")
    # example: 2021-09-06 21:00:00
