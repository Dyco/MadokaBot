"""积分排名的超级用户配置。"""

from nonebot import get_driver


def get_ranking_superusers() -> set[str]:
    """排名排除账号读取方法。"""
    return {
        uid.removeprefix("onebot:")
        for uid in get_driver().config.superusers
        if ":" not in uid or uid.startswith("onebot:")
    }
