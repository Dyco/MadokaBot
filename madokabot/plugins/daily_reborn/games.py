"""从已核实的二游设定与养成规则抽取游戏身份。"""

from .identity import load_identity_data, simulate_identity


def simulate_games() -> dict:
    """所有游戏共用二游模式的每日机会，字段与规则全部来自 JSON。"""
    return simulate_identity(load_identity_data("games"), mode="games")
