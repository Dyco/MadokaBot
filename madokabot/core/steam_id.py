"""Steam 账号 ID 的公共格式转换。"""

STEAM_ID_OFFSET = 76561197960265728
_MAX_ACCOUNT_ID = 0xFFFFFFFF


def normalize_steam_id(value: str) -> str:
    """SteamID规范化方法。"""
    raw = value.strip()
    if not raw.isascii() or not raw.isdigit():
        raise ValueError("Steam ID 必须是纯数字。")
    if 1 <= len(raw) <= 10:
        account_id = int(raw)
        if not 0 < account_id <= _MAX_ACCOUNT_ID:
            raise ValueError("32 位 Steam ID 超出有效范围。")
        return str(STEAM_ID_OFFSET + account_id)
    if len(raw) == 17:
        steam_id = int(raw)
        if not STEAM_ID_OFFSET < steam_id <= STEAM_ID_OFFSET + _MAX_ACCOUNT_ID:
            raise ValueError("64 位 Steam ID 超出有效范围。")
        return str(steam_id)
    raise ValueError("Steam ID 必须是 1 至 10 位或 17 位数字。")
