"""通过公共资源目录与 JSON 存储读取投胎资料。"""

from madokabot.core.resources import ResourceFolder, ResourceType, assets
from madokabot.core.storage.json_store import JsonDataStore

DATA_DIR = assets.get_dir(ResourceType.JSON, ResourceFolder.DAILY_REBORN)


def load_json_resource(filename: str) -> dict:
    """使用核心 JSON 工具读取资料，缺失或无效时停止本次生成。"""
    dataset = JsonDataStore(DATA_DIR / filename).content
    if not isinstance(dataset, dict) or not dataset:
        raise ValueError(f"投胎资料缺失或无效：{filename}")
    return dataset
