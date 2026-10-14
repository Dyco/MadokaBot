"""音游查分插件入口。"""

from nonebot.plugin import PluginMetadata

from .chunithm.matchers import CHUNITHM_USAGE
from .config import RhythmGameConfig
from .matchers import MAIMAI_USAGE

__plugin_meta__ = PluginMetadata(
    name="RhythmGame_OCM",
    description="使用 LXNS 查询舞萌与中二节奏的资料、单曲成绩并生成 B50 图片",
    usage=MAIMAI_USAGE + "\n\n" + CHUNITHM_USAGE,
    type="application",
    config=RhythmGameConfig,
    supported_adapters={"~onebot.v11"},
    extra={"help_category": "拓展功能", "help_order": 65},
)

from . import commands as commands
from .chunithm import commands as chunithm_commands  # noqa: F401
