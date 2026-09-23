from importlib.metadata import version


def get_bot_version() -> str:
    """读取已安装的 MadokaBot 包版本。"""
    return version("madokabot")
