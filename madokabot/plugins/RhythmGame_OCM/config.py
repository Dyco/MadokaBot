"""音游查分与资源更新配置。"""

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, SecretStr


class RhythmGameConfig(BaseModel):
    """舞萌和中二共用的 LXNS 开发者密钥与资源下载参数。"""

    rhythmgame_lxns_token: SecretStr = SecretStr("")
    rhythmgame_request_timeout: float = Field(default=20, gt=0)
    rhythmgame_asset_interval: float = Field(default=1, ge=0.5)


config = get_plugin_config(RhythmGameConfig)
