from dataclasses import dataclass
from pathlib import Path

from madokabot.core.resources import ResourceType, ResourceFolder, assets, get_indexed_files


@dataclass(frozen=True)
class ShopDefinition:
    """资源商店分类。"""

    type: ResourceType
    content: ResourceFolder
    price: int
    prefix: str


SKIN_SHOP = ShopDefinition(
    type=ResourceType.IMAGE,
    content=ResourceFolder.CHAR,
    price=50,
    prefix="skin",
)

SIGN_SHOP = ShopDefinition(ResourceType.IMAGE, ResourceFolder.SIGN, 500, "sign")
DEFAULT_SIGN_ASSET = "daily_sign_01.png"
SIGN_TEMPLATES = {
    "sign01": ("daily_sign_01.html", "默认模板", 0),
    "sign02": ("daily_sign_02.html", "P3 水色模板", SIGN_SHOP.price),
    "sign03": ("daily_sign_03.html", "尼尔档案模板", SIGN_SHOP.price),
}
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "account" / "templates"


def get_sign_map() -> dict[str, Path]:
    """仅展示同时具有正式模板与预览图片的签到商品，编号保持固定。"""
    image_dir = assets.get_dir(SIGN_SHOP.type, SIGN_SHOP.content)
    return {
        key: image_dir / Path(filename).with_suffix(".png")
        for key, (filename, _, _) in SIGN_TEMPLATES.items()
        if (TEMPLATE_DIR / filename).is_file()
        and (image_dir / Path(filename).with_suffix(".png")).is_file()
    }


def get_sign_template_path(filename: str) -> Path | None:
    """按已登记名称获取正式模板，避免读取任意路径或试验模板。"""
    if filename not in {item[0] for item in SIGN_TEMPLATES.values()}:
        return None
    path = TEMPLATE_DIR / filename
    return path if path.is_file() else None


def get_skin_map() -> dict[str, Path]:
    """立绘目录索引方法。"""
    return get_indexed_files(
        SKIN_SHOP.type,
        SKIN_SHOP.content,
        prefix=SKIN_SHOP.prefix,
    )


def get_skin_path(asset_name: str) -> Path | None:
    """立绘文件查询方法。"""
    path = next(
        (path for path in get_skin_map().values() if path.name == asset_name),
        None,
    )
    return path if path is not None and path.is_file() else None
