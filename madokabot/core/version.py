from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def get_bot_version() -> str:
    """读取包版本；源码运行时读取项目声明的版本。"""
    try:
        return version("madokabot")
    except PackageNotFoundError:
        project_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
        project = project_file.read_text(encoding="utf-8").split("[project]", 1)[1]
        project = project.split("\n[", 1)[0]
        return next(
            line.split('"', 2)[1]
            for line in project.splitlines()
            if line.startswith("version = ")
        )
