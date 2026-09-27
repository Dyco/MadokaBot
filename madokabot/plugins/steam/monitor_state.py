"""记录运行期间群与订阅的启用版本，供轮询建立基线。"""

_group_versions: dict[str, int] = {}
_subscription_versions: dict[tuple[str, str], int] = {}


def mark_group_changed(group_id: str) -> None:
    """群总开关变化后，让该群下一次状态查询重新建立基线。"""
    key = str(group_id)
    _group_versions[key] = _group_versions.get(key, 0) + 1


def mark_subscription_changed(group_id: str, user_id: str) -> None:
    """订阅启停后，让该用户在本群重新建立基线。"""
    key = (str(group_id), str(user_id))
    _subscription_versions[key] = _subscription_versions.get(key, 0) + 1


def get_monitor_version(group_id: str, user_id: str) -> tuple[int, int]:
    """读取群开关与个人订阅的运行时版本。"""
    group_id, user_id = str(group_id), str(user_id)
    return (
        _group_versions.get(group_id, 0),
        _subscription_versions.get((group_id, user_id), 0),
    )
