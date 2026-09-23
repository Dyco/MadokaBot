"""CS 命令定义、别名与用法文本。"""

from __future__ import annotations

from arclet.alconna import StrMulti
from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna

from .players.constants import SUPPORTED_PLATFORM_TEXT

BOT_NAME = "圆香"


UNSUPPORTED_LINK_MESSAGE = f"{BOT_NAME}暂不支持此链接"


CS_BIND_USAGE = f"用法：CS bind <{SUPPORTED_PLATFORM_TEXT}> <用户昵称>"


CS_UNBIND_USAGE = f"用法：CS unbind <{SUPPORTED_PLATFORM_TEXT}>"


CS_LOGIN_USAGE = "用法：CS login <手机号> <验证码>"


CS_STATS_USAGE = (
    "【查询指令】\n"
    "CS 战绩 <5E | 5e | 5eplay> [玩家昵称]\n"
    "CS 战绩 <wm | pw | 完美> [Steam ID]"
)


CS_UNSUB_USAGE = "用法：CS unsub <赛事ID>"


CS_REMOVESUB_USAGE = "用法：CS removesub <赛事ID>"


CS_EVENT_USAGE = "用法：CS event <all|single|notif|predict>"


CS_PREDICTION_USAGE = (
    "用法：\nCS prediction <队伍名|A/B> <积分>\nCS prediction rank <本群|全部>"
)


CS_USAGE = """用法：
CS help
CS list event  列出当前及未来三个月的高奖金国际 LAN 和 Major 赛事
CS list <比赛ID> 查看竞猜情况
CS sub <赛事ID>  订阅赛事并推送其中的比赛结果
CS event <all|single|notif|predict> 设置本群推送方式、开赛提醒和竞猜
CS unsub <赛事ID>  本群退订指定赛事推送
CS nosub  本群退订全部赛事推送
CS removesub <赛事ID>  超级用户全局移除赛事订阅
CS check <比赛链接>  查询一场比赛的 Rating
CS prediction <队伍名|A/B> <积分> 参与当前比赛竞猜
CS prediction rank <本群|全部> 查看竞猜排行榜
CS login <手机号> <验证码>  登录完美平台并保存 Session（验证码请自行获取）
CS bind <5E|5e|5eplay|wm|pw|完美> <用户昵称>  绑定平台战绩查询对象
CS unbind <5E|5e|5eplay|wm|pw|完美>  解除指定平台绑定
CS result <5E|5e|5eplay> [玩家昵称]  查询 5E 绑定账号或指定玩家的战绩
CS result <wm|pw|完美> [Steam ID]  查询完美平台绑定账号或指定 Steam ID 的战绩


订阅后的推送方式和赛事开始通知，按本群的CS event设置生效。"""


cs_command = Alconna(
    "cs",
    Subcommand(
        "help",
        alias=["帮助"],
        help_text="查看 CS 赛事指令帮助",
    ),
    Subcommand(
        "list",
        Args["params?", StrMulti],
        alias=["列表"],
        help_text="列出 CS 赛事信息或查看竞猜情况",
    ),
    Subcommand(
        "event",
        Args["params?", StrMulti],
        alias=["赛事", "比赛"],
        help_text="设置本群赛事推送方式",
    ),
    Subcommand(
        "prediction",
        Args["params?", StrMulti],
        alias=["竞猜", "预测"],
        help_text="参与赛事预测",
    ),
    Subcommand(
        "sub",
        Args["event_id?", StrMulti],
        alias=["订阅"],
        help_text="订阅 HLTV 赛事并推送其中的比赛结果",
    ),
    Subcommand(
        "unsub",
        Args["event_id?", str],
        alias=["退订"],
        help_text="让当前群退订指定赛事推送",
    ),
    Subcommand(
        "nosub",
        alias=["退订全部", "退订所有"],
        help_text="让当前群退订全部赛事推送",
    ),
    Subcommand(
        "removesub",
        Args["event_id?", str],
        alias=["移除订阅", "删除订阅"],
        help_text="超级用户全局移除指定赛事订阅",
    ),
    Subcommand(
        "login",
        Args["mobile?", str],
        Args["code?", str],
        alias=["登录"],
        help_text="使用手机号和验证码登录完美平台并保存 Session",
    ),
    Subcommand(
        "bind",
        Args["params?", StrMulti],
        alias=["绑定"],
        help_text="绑定 5E 或完美平台玩家昵称",
    ),
    Subcommand(
        "unbind",
        Args["params?", StrMulti],
        alias=["解绑"],
        help_text="解除指定平台绑定",
    ),
    Subcommand(
        "result",
        Args["platform", str],
        Args["nickname?", StrMulti],
        alias=["战绩"],
        help_text="查询 5E 昵称或完美平台 Steam ID 的玩家战绩",
    ),
    Subcommand(
        "check",
        Args["match_url?", StrMulti],
        alias=["查看"],
        help_text="查询 HLTV 比赛 Rating",
    ),
)


cs_cmd = on_alconna(
    cs_command,
    use_cmd_start=True,
    aliases={"CS"},
    priority=10,
    block=True,
)
