from nonebot.plugin import PluginMetadata

from .config import CopyingConfig, config

__plugin_meta__ = PluginMetadata(
    name="复读机",
    description="群内出现连续的重复消息时，自动复读+1",
    usage=(
        f"使用/copying set <数字>即可设置触发阈值，最低值{config.copying_number}\n"
        "使用/copying on|off控制复读开关\n"
        "*仅限管理员使用"
    ),
    type="application",
    config=CopyingConfig,
    extra={"help_category": "响应内容", "help_order": 20},
)

from . import handlers as handlers  # noqa: E402,F401
