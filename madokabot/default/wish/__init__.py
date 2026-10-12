"""许愿插件元数据与处理器入口。"""

from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="许愿",
    description="花费1积分许愿，极低概率获得许愿池的全部积分",
    usage="发送“许愿”即可参与，每天仅限一次。",
    type="application",
    extra={"help_category": "基础功能", "help_order": 11},
)

from . import handlers as handlers  # noqa: E402,F401
