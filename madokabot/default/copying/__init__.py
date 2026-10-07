from nonebot.plugin import PluginMetadata

from .config import CopyingConfig, config

__plugin_meta__ = PluginMetadata(
    name="复读机功能",
    description="检测到群内连续重复的文字或图片消息时，自动复读一次",
    usage=(
        f"默认连续 {config.copying_number} 条相同消息时触发。\n"
        "复读 开/关\n"
        "复读 设置 <数量>"
    ),
    type="application",
    config=CopyingConfig,
)

from . import handlers as handlers  # noqa: E402,F401
