"""LXNS 中二节奏的只读查分请求。"""

from ..client import request_api
from .models import Best50, Player, Score


async def get_player(identifier: str, *, qq: bool = False) -> Player:
    """通过中二好友码或 LXNS 绑定的 QQ 获取资料。"""
    path = f"player/qq/{identifier}" if qq else f"player/{identifier}"
    return Player.model_validate(await request_api("chunithm", path))


async def get_b50(friend_code: int) -> Best50:
    """读取 LXNS 返回的 B30、B20 和 Selection 10。"""
    return Best50.model_validate(await request_api("chunithm", f"player/{friend_code}/bests"))


async def get_score(friend_code: int, song_id: int, level_index: int) -> Score:
    """读取指定曲目与难度的最佳成绩，中二不区分 SD／DX。"""
    return Score.model_validate(await request_api(
        "chunithm", f"player/{friend_code}/best",
        {"song_id": song_id, "level_index": level_index},
    ))
