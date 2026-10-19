"""从百科作品资料抽取二次元身份。"""

from .identity import load_identity_data, simulate_identity


def load_anime_data() -> dict:
    """读取二次元作品资料，使用共用的条件池校验和缓存。"""
    return load_identity_data("anime")


def simulate_anime() -> dict:
    """生成二次元身份与来源快照，保持原有模式及数据格式。"""
    return simulate_identity(load_anime_data(), mode="anime")
