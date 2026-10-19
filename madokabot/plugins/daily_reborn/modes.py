"""投胎模式及展示名称。"""

from typing import Literal

# 各模式分别保存每日结果与累计记录。
RebornMode = Literal["world", "china", "japan", "usa", "isekai", "anime", "games"]
MODE_NAMES = {"world": "世界", "china": "中国", "japan": "日本", "usa": "美国", "isekai": "异世界", "anime": "二次元", "games": "二游"}
MODE_COMMANDS = {
    "world": "投胎", "china": "投胎中国", "japan": "投胎日本", "usa": "投胎美国", "isekai": "投胎异世界",
    "anime": "投胎二次元", "games": "投胎二游",
}
