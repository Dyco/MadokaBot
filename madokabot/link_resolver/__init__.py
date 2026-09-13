from nonebot.plugin import PluginMetadata

from .commands import RESOLVER_USAGE
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="Madoka 链接分享解析器",
    description="MadokaBot 内置的链接分享解析器，支持视频、图片和音乐链接。",
    usage=RESOLVER_USAGE,
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=Config,
    supported_adapters={"~onebot.v11"},
    extra={
        "source": "https://github.com/zhiyu1998/nonebot-plugin-resolver",
        "source_version": "1.2.32",
    },
)

from . import handlers as handlers  # noqa: E402,F401
