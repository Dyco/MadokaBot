from nonebot.plugin import PluginMetadata
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="Madoka自定义CS赛事订阅",
    description="Madoka自定义CS赛事订阅插件。",
    usage= (
    "使用CS作为起始指令进行查询\n"
    "cs sub|订阅 / result|赛果  <赛事ID>"
),
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=Config,
)

