"""玩家战绩接口地址、平台别名和卡片字段约定。"""

from __future__ import annotations

from datetime import timedelta, timezone

from .models import MatchViewFields

FIVE_E_SEARCH_URL = "https://arena.5eplay.com/api/search/player/1/16"


FIVE_E_ID_URL = "https://gate.5eplay.com/userinterface/http/v1/userinterface/idTransfer"


FIVE_E_MATCH_LIST_URL = "https://gate.5eplay.com/crane/http/api/data/match/list"


FIVE_E_PLAYER_HOME_URL = "https://gate.5eplay.com/crane/http/api/data/v3/player/home"


RECENT_MATCH_LIMIT = 10


FIVE_E_RETRY_ATTEMPTS = 2


FIVE_E_RETRY_DELAY = 0.5


CHINA_TIMEZONE = timezone(timedelta(hours=8))


# 完美平台旧版接口仍负责返回完整的个人统计，但必须使用当前客户端的
# 公开请求头，并将 mySteamId 设为 0；使用手机号登录得到的旧 token 已无法
# 稳定调用这两个接口。
PW_CURRENT_SEARCH_URL = "https://gwapi.pwesports.cn/acty/api/v1/search"


PW_STATS_URL = "https://api.wmpvp.com/api/csgo/home/pvp/detailStats"


PW_MATCHES_URL = "https://api.wmpvp.com/api/csgo/home/match/list"


PW_LOGIN_URL = "https://passport.pwesports.cn/account/login"


PW_PUBLIC_APPVERSION = "3.7.9.203"


PW_PUBLIC_DEVICE = "rGPSR1772436611LrL5aF8eKG3"


PW_PUBLIC_TOKEN = "8e1233748353756e1d84a321753a98d599a9de48"


PLATFORM_ALIASES = {
    "5e": "5e",
    "5eplay": "5e",
    "pw": "pw",
    "wm": "pw",
    "完美": "pw",
    "完美世界": "pw",
}


SUPPORTED_PLATFORM_TEXT = "5E、5e、5eplay、wm、pw 或 完美"


# 5E 当前优先排位分段：这里使用每个分段的最高分作为边界，
# 例如 2001-2150 分归入 A-，2401 分及以上进入 S 星级。
FIVE_E_RANK_TIERS = (
    (1200, "D", "Level_D.avif"),
    (1350, "C-", "Level_C1.avif"),
    (1500, "C", "Level_C2.avif"),
    (1600, "C+", "Level_C3.avif"),
    (1750, "B-", "Level_B1.avif"),
    (1900, "B", "Level_B2.avif"),
    (2000, "B+", "Level_B3.avif"),
    (2150, "A-", "Level_A1.avif"),
    (2300, "A", "Level_A2.avif"),
    (2400, "A+", "Level_A3.avif"),
)


# 完美世界当前天梯分段。带“金色”的档位与同名普通档位是不同段位，
# 不能只根据字母截断；2401 分以上由 stars 决定 S 段展示。
PW_RANK_LIMITS = (
    (1000, "D"),
    (1150, "C"),
    (1300, "C+"),
    (1450, "金色 C+"),
    (1600, "B"),
    (1750, "B+"),
    (1900, "金色 B+"),
    (2050, "A"),
    (2200, "A+"),
    (2400, "金色 A+"),
)


FIVE_E_TOP_STARS_MIN = 40


FIVE_E_TOP_RANK_MAX = 100


PW_TOP_STARS_MIN = 50


PW_TOP_RANK_MAX = 999


FIVE_E_MATCH_FIELDS = MatchViewFields(
    win="is_win",
    tie="is_tie",
    team=None,
    winner=None,
    direct_score="score",
    score1="group1_all_score",
    score2="group2_all_score",
    time="start_time",
    map_name="map",
    kills="kill",
    deaths="death",
    assists=None,
    rating="rating",
    secondary="adr",
    score_change="change_elo",
    combat_kind="kd",
    secondary_kind="adr",
)


PW_MATCH_FIELDS = MatchViewFields(
    win="isWin",
    tie=None,
    team="team",
    winner="winTeam",
    direct_score=None,
    score1="score1",
    score2="score2",
    time="matchTime",
    map_name="mapName",
    kills="kill",
    deaths="death",
    assists="assist",
    rating="pwRating",
    secondary="we",
    score_change="pvpScoreChange",
    combat_kind="kda",
    secondary_kind="we",
)
