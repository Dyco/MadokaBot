"""CS 命令定义、别名与用法文本。"""

from __future__ import annotations

from arclet.alconna import StrMulti
from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna

from .players.constants import SUPPORTED_PLATFORM_TEXT

BOT_NAME = "圆香"


UNSUPPORTED_LINK_MESSAGE = f"{BOT_NAME}暂不支持此链接"


CS_BIND_USAGE = (
    "用法：\n"
    "CS bind <5E|5e|5eplay> <玩家昵称>\n"
    "CS bind <wm|pw|完美> [Steam 32 位或 64 位 ID]"
)


CS_UNBIND_USAGE = f"用法：CS unbind <{SUPPORTED_PLATFORM_TEXT}>"


CS_LOGIN_USAGE = "用法：CS login <手机号> <验证码>"


CS_STATS_USAGE = (
    "【查询指令】\n"
    "CS 战绩 <5E | 5e | 5eplay> [玩家昵称]\n"
    "CS 战绩 <wm | pw | 完美> [Steam 32 位或 64 位 ID]"
)


CS_UNSUB_USAGE = "用法：CS unsub <赛事ID>"


CS_REMOVESUB_USAGE = "用法：CS removesub <赛事ID>"


CS_EVENT_USAGE = "用法：CS event [all|single|notif|predict]（不带参数时查看赛事列表）"


CS_PREDICTION_USAGE = (
    "用法：\nCS prediction <队伍名|竞猜编号> <积分>\n"
    "例如：CS prediction teamA 100（以当前通知编号为准）\n"
    "CS prediction rank <本群|全部|个人|本人>"
)


CS_USAGE = """用法：
/cs help
/cs event  列出当前及未来三个月的高奖金国际 LAN 和 Major 赛事
/cs list <比赛ID> 查看竞猜情况
/cs sub <赛事ID>  订阅赛事并推送其中的比赛结果
/cs check <比赛链接>  查询一场比赛的 Rating
/cs prediction <队伍名|竞猜编号> <积分> 参与当前比赛竞猜（如 teamA、team1）
/cs prediction rank <本群|全部|个人|本人> 查看竞猜排行榜或个人记录
/cs login <手机号> <验证码>  登录完美平台并保存 Session（验证码请自行获取）
/cs bind <5E|5e|5eplay> <玩家昵称>  绑定 5E 玩家
/cs bind <wm|pw|完美> [Steam 32 位或 64 位 ID]  使用 Steam/CS 共用绑定
/cs unbind <5E|5e|5eplay|wm|pw|完美>  解绑 5E 或 Steam/CS 共用账号
/cs result <5E|5e|5eplay> [玩家昵称]  查询 5E 绑定账号或指定玩家的战绩
/cs result <wm|pw|完美> [Steam 32 位或 64 位 ID]  查询完美平台绑定账号或指定 Steam ID 的战绩

*以下指令仅限管理员使用（群主、群管理员、超级用户），仅支持群聊
/cs event <all|single|notif|predict> 设置本群推送方式、开赛提醒和竞猜
/cs unsub <赛事ID>  本群退订指定赛事推送
/cs nosub  本群退订全部赛事推送

*以下指令仅限超级用户使用
/cs removesub <赛事ID>  全局移除赛事订阅

订阅后的推送方式和赛事开始通知，按本群的 /cs event 设置生效。
本群竞猜默认开启，可使用 /cs event predict 切换；竞猜通知通过合并转发推送。"""


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
        help_text="查看指定比赛的竞猜情况",
    ),
    Subcommand(
        "event",
        Args["params?", StrMulti],
        alias=["赛事", "比赛"],
        help_text="查看赛事列表或设置本群赛事推送方式",
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
        help_text="绑定 5E 玩家，或使用 Steam/CS 共用账号查询完美平台",
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
        help_text="查询 5E 昵称或完美平台 Steam 32 位、64 位 ID 的玩家战绩",
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
