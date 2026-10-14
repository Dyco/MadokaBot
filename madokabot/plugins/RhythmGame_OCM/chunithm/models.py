"""LXNS 中二玩家、谱面成绩与 Rating 构成。"""

from pydantic import BaseModel, Field

from ..models import Collection

DIFFICULTIES = ("BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA", "WORLD'S END")
DIFFICULTY_KEYS = ("basic", "advanced", "expert", "master", "ultima", "worldsend")


class ChunithmCollection(Collection):
    """中二角色、称号、名牌版或地图头像。"""

    color: str | None = None
    level: int | None = None


class Player(BaseModel):
    """中二节奏玩家公开资料。"""

    name: str
    friend_code: int
    rating: float
    level: int = 0
    reborn_count: int = 0
    over_power: float = 0
    over_power_progress: float = 0
    total_play_count: int = 0
    trophy: ChunithmCollection | None = None
    character: ChunithmCollection | None = None
    name_plate: ChunithmCollection | None = None
    map_icon: ChunithmCollection | None = None
    upload_time: str = ""


class Score(BaseModel):
    """中二谱面最佳成绩，保留通关、连击和链条状态。"""

    id: int
    song_name: str
    level: str
    level_index: int = Field(ge=0, le=5)
    score: int
    rating: float
    over_power: float = 0
    clear: str
    rank: str
    full_combo: str | None = None
    full_chain: str | None = None


class Best50(BaseModel):
    """旧曲 B30、新曲 B20 以及不参与 B50 合计的候选 S10。"""

    bests: list[Score]
    new_bests: list[Score]
    selections: list[Score] = Field(default_factory=list)
