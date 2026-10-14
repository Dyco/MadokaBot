from nonebot.plugin import PluginMetadata
from madokabot.core.config import command_start

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="解析插件",
    description="自动解析群聊分享的视频、图片和音乐链接，使用解析指令管理开关与评论。",
    usage=(
        "用法：\n"
        "直接在群聊发送分享链接即可自动解析。\n"
        f"{command_start}解析 打开/关闭 <全部/平台/图片/视频/评论> [多个参数]\n"
        f"示例：{command_start}解析 关闭 抖音 B站 图片；{command_start}解析 关闭 图片 评论\n"
        f"{command_start}解析 关闭 全部，然后{command_start}解析 打开 B站，可仅保留 B站解析\n"
        f"{command_start}解析 查看\n"
        f"{command_start}解析 切换评论 | {command_start}解析 重载评论\n"
        f"{command_start}解析 帮助"
    ),
    type="application",
    homepage="https://github.com/Dyco/MadokaBot",
    config=Config,
    supported_adapters={"~onebot.v11"},
    extra={
        "help_category": "拓展功能",
        "help_order": 30,
        "source": "https://github.com/zhiyu1998/nonebot-plugin-resolver",
        "source_version": "1.2.32",
    },
)

from . import handlers as handlers  # noqa: E402,F401
