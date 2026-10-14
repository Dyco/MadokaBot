"""LXNS 玩家与成绩数据结构。"""

from typing import Literal

from pydantic import BaseModel, Field

DIFFICULTIES = ("BASIC", "ADVANCED", "EXPERT", "MASTER", "Re:MASTER")
DIFFICULTY_KEYS = ("basic", "advanced", "expert", "master", "remaster")


class Collection(BaseModel):
    """玩家头像、姓名框或称号。"""

    id: int
    name: str = ""


class Player(BaseModel):
    """舞萌玩家公开资料。"""

    name: str
    rating: int
    friend_code: int
    course_rank: int = 0
    class_rank: int = 0
    star: int = 0
    trophy: Collection | None = None
    icon: Collection | None = None
    name_plate: Collection | None = None
    upload_time: str = ""


class Score(BaseModel):
    """单张谱面的最佳成绩，保留标准与 DX 类型区别。"""

    id: int
    song_name: str
    level: str
    level_index: int = Field(ge=0, le=4)
    achievements: float
    dx_score: int
    dx_rating: float
    dx_star: int = 0
    rate: str
    type: Literal["standard", "dx", "utage"]
    fc: str | None = None
    fs: str | None = None


class Best50(BaseModel):
    """旧谱 B35 与现版本 B15，分组以 LXNS 返回为准。"""

    standard_total: int
    dx_total: int
    standard: list[Score]
    dx: list[Score]
