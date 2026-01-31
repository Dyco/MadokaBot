import random
from datetime import datetime, timedelta
from typing import Tuple
from zoneinfo import ZoneInfo

from ...db.services import UserService



def calculate_reward(continuous_days: int) -> Tuple[int, int, int]:
    """
    计算奖励逻辑
    :param continuous_days: 当前的连续签到天数
    :return: (总积分, 连签奖励分, 提升好感度)
    """
    bonus = min(max(continuous_days - 1, 0), 10)
    base_points = random.randint(3, 6)
    reward_points = base_points + bonus
    reward_favor = random.randint(0, 1)
    
    return reward_points, bonus, reward_favor

#检查是否已签到
async def get_sign_status(uid: str, session):
    """仅仅检查日期，不做任何更新"""
    user, sign = await UserService.get_user_data(session, uid)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    is_new = (sign.last_sign_date.date() != now.date()) if sign.last_sign_date else True
    return user, sign, is_new


#计算奖励内容
async def execute_sign_update(user, sign, session):
    """计算奖励并更新数据库"""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date()
    last_date = sign.last_sign_date.date() if sign.last_sign_date else None

    # 计算连签
    if last_date == today - timedelta(days=1):
        sign.continuous_days += 1
    else:
        sign.continuous_days = 1

    reward_points, bonus_point, reward_favor = calculate_reward(sign.continuous_days)
    
    # 更新对象
    user.points += reward_points
    user.favorability += reward_favor
    sign.total_count += 1
    sign.last_sign_date = now

    reward_info = {
        "reward_points": reward_points - bonus_point,
        "bonus_point": bonus_point,
        "reward_favor": reward_favor
    }

    await session.commit()
    return reward_info