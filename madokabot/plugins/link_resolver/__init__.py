from nonebot.plugin import PluginMetadata
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="Madoka 链接分享解析器",
    description="MadokaBot 内置的链接分享解析器，支持视频、图片和音乐链接，主指令为解析。",
    usage= (
    "用法：\n"
    "解析 <B站/抖音/TikTok/ACFun/X/小红书/YouTube/网易云/酷狗/微博链接>\n"
    "解析 打开/关闭 <全部/平台/图片/视频/评论> [多个参数]\n"
    "示例：解析 关闭 抖音 B站 图片；解析 关闭 图片 评论\n"
    "解析 关闭 全部，然后解析 打开 B站，可仅保留 B站解析\n"
    "解析 查看\n"
    "解析 切换评论 | 解析 重载评论\n"
    "解析 帮助"
),
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
