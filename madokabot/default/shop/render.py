import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from madokabot.core.resources import ResourceFolder, ResourceType, assets
from madokabot.core.storage.image_cache import ImageCache, build_image_signature

CARD_BG = "#e5e8ec"
PANEL_BG = "#f2f4f7"
PANEL_ALT_BG = "#ebedf2"
PANEL_BORDER = "#cdd3dc"
TEXT_MAIN = "#2d3440"
TEXT_SUB = "#6c7686"
OWNED_COLOR = "#3c7a89"
UNOWNED_COLOR = "#8e5a65"
CURRENT_COLOR = "#426b9b"

THUMB_HEIGHT = 300
THUMB_FRAME_HEIGHT = THUMB_HEIGHT + 20
GRID_COLUMNS = 4
PAGE_SIZE = 12
SIGN_GRID_COLUMNS = 3
SIGN_PAGE_SIZE = 9
OUTER_PADDING = 34
HEADER_HEIGHT = 142
FOOTER_HEIGHT = 24
GRID_GAP = 24

_BACKGROUND_CACHE = ImageCache("shop")


@dataclass(frozen=True)
class _ShopLayout:
    """公共底图与用户状态叠加共用的商店页面布局。"""

    columns: int
    rows: int
    cell_width: int
    cell_height: int
    frame_height: int

    @property
    def width(self) -> int:
        """根据列数计算页面宽度。"""
        return OUTER_PADDING * 2 + self.columns * self.cell_width + (self.columns - 1) * GRID_GAP

    @property
    def height(self) -> int:
        """根据实际行数计算页面高度。"""
        return (
            OUTER_PADDING * 2 + HEADER_HEIGHT + FOOTER_HEIGHT
            + self.rows * self.cell_height + (self.rows - 1) * GRID_GAP
        )

    def card_box(self, index: int) -> tuple[int, int, int, int]:
        """返回指定商品的卡片区域。"""
        x = OUTER_PADDING + index % self.columns * (self.cell_width + GRID_GAP)
        y = OUTER_PADDING + HEADER_HEIGHT + index // self.columns * (self.cell_height + GRID_GAP)
        return x, y, x + self.cell_width, y + self.cell_height

    def preview_box(self, index: int) -> tuple[int, int, int, int]:
        """返回指定商品的预览区域，统一编号与持有状态的位置。"""
        x1, y1, x2, _ = self.card_box(index)
        return x1 + 20, y1 + 18, x2 - 20, y1 + 18 + self.frame_height


def _font_path(bold: bool = False) -> Path:
    """返回商店字体路径，供字体加载与缓存指纹共用。"""
    font_name = "MiSans-Bold.ttf" if bold else "MiSans-Regular.ttf"
    return assets.get_dir(ResourceType.FONT, ResourceFolder.STEAM) / font_name


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """按字号和字重加载商店字体。"""
    font_path = _font_path(bold)
    if not font_path.is_file():
        raise FileNotFoundError(f"商店字体资源不存在：{font_path}")
    return ImageFont.truetype(str(font_path), size)


def _clip_name(name: str, limit: int = 18) -> str:
    """截短过长的商品名称。"""
    if len(name) <= limit:
        return name
    return name[: limit - 3] + "..."


def _load_shop_image(asset_name: str, content: ResourceFolder) -> Image.Image:
    """按商品分类加载立绘或模板预览。"""
    image_path = assets.get_dir(ResourceType.IMAGE, content) / asset_name
    with Image.open(image_path) as image:
        return image.convert("RGBA")


def _resize_preview(image: Image.Image, max_width: int) -> Image.Image:
    """按预览区域等比缩放商品图片。"""
    target_width = max(1, int(image.width * (THUMB_HEIGHT / image.height)))
    resized = image.resize((target_width, THUMB_HEIGHT), Image.LANCZOS)
    if resized.width <= max_width:
        return resized

    target_height = max(1, int(resized.height * (max_width / resized.width)))
    return resized.resize((max_width, target_height), Image.LANCZOS)


def _draw_preview(
    canvas: Image.Image,
    panel_box: tuple[int, int, int, int],
    asset_name: str,
    content: ResourceFolder,
) -> None:
    """在商品面板内缩放并绘制对应分类的图片。"""
    draw = ImageDraw.Draw(canvas)
    x1, _, x2, y2 = panel_box

    draw.rounded_rectangle(
        panel_box,
        radius=18,
        fill="#e8ebf0",
        outline="#d5dbe4",
        width=2,
    )

    preview = _load_shop_image(asset_name, content)
    resized = _resize_preview(preview, max_width=(x2 - x1) - 24)
    paste_x = x1 + ((x2 - x1) - resized.width) // 2
    paste_y = y2 - resized.height
    canvas.alpha_composite(resized, (paste_x, paste_y))


def _render_shop_background(
    page_items: list[dict[str, Any]],
    page: int,
    total_pages: int,
    category: str,
    layout: _ShopLayout,
) -> Image.Image:
    """绘制所有用户共用的商品底图，不包含积分或个人持有状态。"""
    content = ResourceFolder.SIGN if category == "sign" else ResourceFolder.CHAR

    title_font = _load_font(44, bold=True)
    subtitle_font = _load_font(24, bold=True)
    body_font = _load_font(20)
    tag_font = _load_font(18, bold=True)

    width, height = layout.width, layout.height
    image = Image.new("RGBA", (width, height), CARD_BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (18, 18, width - 18, height - 18),
        radius=30,
        fill=PANEL_BG,
        outline=PANEL_BORDER,
        width=2,
    )
    draw.text(
        (width // 2, 62), "签到模板商店" if category == "sign" else "积分商店",
        font=title_font, fill=TEXT_MAIN, anchor="mm"
    )
    draw.text(
        (width - 58, 94),
        f"第 {page} / {total_pages} 页",
        font=body_font,
        fill=TEXT_SUB,
        anchor="ra",
    )

    if not page_items:
        draw.text(
            (width // 2, OUTER_PADDING + HEADER_HEIGHT + 120),
            "当前没有可用商品",
            font=subtitle_font,
            fill=TEXT_SUB,
            anchor="mm",
        )
    else:
        for index, item in enumerate(page_items):
            card_box = layout.card_box(index)
            card_x = card_box[0]
            panel_fill = PANEL_BG if index % 2 == 0 else PANEL_ALT_BG

            draw.rounded_rectangle(
                card_box,
                radius=26,
                fill=panel_fill,
                outline=PANEL_BORDER,
                width=2,
            )

            preview_box = layout.preview_box(index)
            _draw_preview(image, preview_box, item["asset_name"], content)

            name_text = _clip_name(item.get("name", Path(item["asset_name"]).stem), limit=20)
            number_text = item["item_key"]
            price_text = f"价格：{item['price']}积分"

            draw.text(
                (preview_box[0] + 14, preview_box[1] + 12),
                number_text,
                font=tag_font,
                fill=TEXT_MAIN,
            )
            text_y = preview_box[3] + 14
            draw.text(
                (card_x + 24, text_y),
                price_text,
                font=body_font,
                fill="#616f82",
            )
            draw.text(
                (card_x + 24, text_y + 28),
                name_text,
                font=body_font,
                fill=TEXT_MAIN,
            )

    return image


def render_shop_list_card(
    items: list[dict[str, Any]],
    points: int,
    page: int = 1,
    page_size: int | None = None,
    total_pages: int | None = None,
    category: str = "skin",
) -> bytes:
    """复用持久化商品底图，实时叠加积分和当前用户的持有状态。"""
    if page_size is None:
        page_size = SIGN_PAGE_SIZE if category == "sign" else PAGE_SIZE
    if page_size <= 0:
        raise ValueError("page_size 必须大于 0")
    if total_pages is None:
        total_pages = max(1, math.ceil(len(items) / page_size))
    if total_pages <= 0:
        raise ValueError("total_pages 必须大于 0")

    page = max(1, min(page, total_pages))
    page_items = items[(page - 1) * page_size : page * page_size]
    columns = SIGN_GRID_COLUMNS if category == "sign" else GRID_COLUMNS
    layout = _ShopLayout(
        columns=columns,
        rows=max(1, math.ceil((len(page_items) if category == "sign" else page_size) / columns)),
        cell_width=520 if category == "sign" else 400,
        cell_height=450 if category == "sign" else 420,
        frame_height=350 if category == "sign" else THUMB_FRAME_HEIGHT,
    )
    content = ResourceFolder.SIGN if category == "sign" else ResourceFolder.CHAR
    image_dir = assets.get_dir(ResourceType.IMAGE, content)
    signature = build_image_signature(
        {
            "category": category, "page": page, "page_size": page_size, "total_pages": total_pages,
            "items": [
                {
                    "item_key": item["item_key"], "asset_name": item["asset_name"],
                    "name": item.get("name", Path(item["asset_name"]).stem), "price": item["price"],
                }
                for item in page_items
            ],
        },
        files=[
            Path(__file__), _font_path(), _font_path(bold=True),
            *(image_dir / item["asset_name"] for item in page_items),
        ],
    )
    cache_key = f"{category}-{page}"
    image = _BACKGROUND_CACHE.load(cache_key, signature)
    if image is None:
        image = _render_shop_background(page_items, page, total_pages, category, layout)
        _BACKGROUND_CACHE.save(cache_key, signature, image)

    draw = ImageDraw.Draw(image)
    draw.text(
        (layout.width - 58, 56), f"当前积分：{points}",
        font=_load_font(24, bold=True), fill="#515d6e", anchor="ra",
    )
    tag_font = _load_font(18, bold=True)
    for index, item in enumerate(page_items):
        if item["current"]:
            status_text, status_color = "[使用中]", CURRENT_COLOR
        elif item["owned"]:
            status_text, status_color = "[已拥有]", OWNED_COLOR
        else:
            status_text, status_color = "[未拥有]", UNOWNED_COLOR
        preview_box = layout.preview_box(index)
        draw.text(
            (preview_box[2] - 14, preview_box[1] + 12), status_text,
            font=tag_font, fill=status_color, anchor="ra",
        )

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
