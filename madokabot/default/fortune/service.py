"""每日运势、农历日期与首次祈福积分奖励。"""

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from random import Random

from nonebot_plugin_datastore import create_session
from sqlalchemy import update

from madokabot.core.db.base import shanghai_now
from madokabot.core.user.models import UserStats
from .almanac import get_almanac
from .models import FortuneRecord

FORTUNE_LEVELS = (
    (90, "大吉", "今天的风正合适，试着向前迈一步吧。"),
    (70, "中吉", "把想做的事提上日程，也许会遇到小惊喜。"),
    (50, "小吉", "顺着自己的节奏来，普通的一天也能过得不错。"),
    (30, "末吉", "先完成一件小事，慢慢找回状态。"),
    (11, "小凶", "今天放慢一点也没关系，给自己留些余地。"),
    (0, "大凶", "不顺心时就歇一歇，今天对自己好一点。"),
)
FORTUNE_REWARDS = {"大吉": 20, "中吉": 18, "小吉": 15, "末吉": 12, "小凶": 10, "大凶": 10}
FORTUNE_LINES = {
    "大吉": "制作人，今天运气不错。……恭喜。别得意过头了。",
    "中吉": "还算顺利。制作人，照常做好该做的事就行。",
    "小吉": "有一点好运。……也值得高兴吧。",
    "末吉": "一点小运气而已。慢慢来吧，制作人。",
    "小凶": "签上这么写，也不代表什么。……别太在意。",
    "大凶": "别盯着那两个字看了。……今天对自己好一点吧。",
}
LUCKY_COLORS = ("天蓝", "樱粉", "草绿", "暖黄", "浅紫", "米白", "橙色", "银灰")


@dataclass(frozen=True)
class FortuneResult:
    """图片与文字共用的每日运势，不包含数值评分。"""

    date: str
    lunar_date: str
    level: str
    suitable: str
    unsuitable: str
    color: str
    number: int
    message: str

    def as_text(self) -> str:
        """图片不可用时返回同一份运势的文字结果。"""
        return (
            f"今日运势（{self.date}）\n"
            f"农历：{self.lunar_date}\n"
            f"综合运势：{self.level}\n"
            f"宜：{self.suitable}\n"
            f"忌：{self.unsuitable}\n"
            f"幸运色：{self.color}\n"
            f"幸运数字：{self.number}\n"
            f"寄语：{self.message}"
        )


def generate_fortune(uid: str, today_date: date) -> FortuneResult:
    """使用上海日期读取农历宜忌，按账号生成个人运势，不夹带积分信息。"""
    today = today_date.isoformat()
    seed = sha256(f"fortune:{today}:{uid}".encode("utf-8")).digest()
    rng = Random(seed)
    roll = rng.randint(1, 100)
    _, level, message = next(item for item in FORTUNE_LEVELS if roll >= item[0])
    lunar_date, suitable, unsuitable = get_almanac(today_date)
    color = rng.choice(LUCKY_COLORS)
    number = rng.randint(0, 9)
    return FortuneResult(
        date=today,
        lunar_date=lunar_date,
        level=level,
        suitable=suitable,
        unsuitable=unsuitable,
        color=color,
        number=number,
        message=message,
    )


async def get_today_fortune(uid: str) -> tuple[FortuneResult, int]:
    """返回已注册用户的当日运势，仅首次在同一事务内保存结果并赠送积分。"""
    today = shanghai_now().date()
    async with create_session() as session:
        # 先取得账号写锁，串行处理同一用户的首次奖励，避免并发重复发放。
        locked = await session.execute(
            update(UserStats).where(UserStats.user_id == uid)
            .values(points=UserStats.points)
        )
        if locked.rowcount != 1:
            raise LookupError("用户未注册")
        record = await session.get(FortuneRecord, (uid, today))
        if record is not None:
            return FortuneResult(**record.result), 0

        result = generate_fortune(uid, today)
        points = FORTUNE_REWARDS[result.level]
        session.add(FortuneRecord(
            user_id=uid, fortune_date=today, result=asdict(result), reward_points=points,
        ))
        await session.execute(
            update(UserStats).where(UserStats.user_id == uid)
            .values(points=UserStats.points + points)
        )
        await session.commit()
    return result, points


def format_reward_message(level: str, points: int) -> str:
    """生成首次祈福的图片外台词，凶签统一使用安慰奖文案。"""
    label = "安慰奖" if level in ("小凶", "大凶") else level
    return f"{FORTUNE_LINES[level]}（{label}+{points}积分）"
