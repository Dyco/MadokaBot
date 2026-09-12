import math
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ...config import assets
from ...constants import ResType, SubFolder

# 樋口円香清冷色调
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


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    font_name = "MiSans-Bold.ttf" if bold else "MiSans-Regular.ttf"
    font_path = assets.get_dir(ResType.FONT, SubFolder.STEAM) / font_name
    if not font_path.is_file():
        raise FileNotFoundError(f"商店字体资源不存在：{font_path}")
    return ImageFont.truetype(str(font_path), size)


def _clip_name(name: str, limit: int = 18) -> str:
    if len(name) <= limit:
        return name
    return name[: limit - 3] + "..."


def _load_skin_image(asset_name: str) -> Image.Image:
    image_path = assets.get_dir(ResType.IMAGE, SubFolder.CHAR) / asset_name
    with Image.open(image_path) as image:
        return image.convert("RGBA")


def _resize_preview(image: Image.Image, max_width: int) -> Image.Image:
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
) -> None:
    draw = ImageDraw.Draw(canvas)
    x1, _, x2, y2 = panel_box

    draw.rounded_rectangle(
        panel_box,
        radius=18,
        fill="#e8ebf0",
        outline="#d5dbe4",
        width=2,
    )

    preview = _load_skin_image(asset_name)
    resized = _resize_preview(preview, max_width=(x2 - x1) - 24)
    paste_x = x1 + ((x2 - x1) - resized.width) // 2
    paste_y = y2 - resized.height
    canvas.alpha_composite(resized, (paste_x, paste_y))


def render_shop_list_card(
    items: list[dict[str, Any]],
    points: int,
    page: int = 1,
    page_size: int = PAGE_SIZE,
    total_pages: int | None = None,
) -> bytes:
    if page_size <= 0:
        raise ValueError("page_size 必须大于 0")
    if total_pages is None:
        total_pages = max(1, math.ceil(len(items) / page_size))
    if total_pages <= 0:
        raise ValueError("total_pages 必须大于 0")

    page = max(1, min(page, total_pages))
    page_items = items[(page - 1) * page_size : page * page_size]
    grid_rows = max(1, math.ceil(page_size / GRID_COLUMNS))

    title_font = _load_font(44, bold=True)
    subtitle_font = _load_font(24, bold=True)
    body_font = _load_font(20)
    tag_font = _load_font(18, bold=True)

    outer_padding = 34
    header_height = 142
    footer_height = 24
    cell_width = 400
    cell_height = 420
    gap_x = 24
    gap_y = 24

    width = outer_padding * 2 + GRID_COLUMNS * cell_width + (GRID_COLUMNS - 1) * gap_x
    height = (
        outer_padding * 2
        + header_height
        + footer_height
        + grid_rows * cell_height
        + (grid_rows - 1) * gap_y
    )

    image = Image.new("RGBA", (width, height), CARD_BG)
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(
        (18, 18, width - 18, height - 18),
        radius=30,
        fill=PANEL_BG,
        outline=PANEL_BORDER,
        width=2,
    )
    draw.text((width // 2, 62), "积分商店", font=title_font, fill=TEXT_MAIN, anchor="mm")
    draw.text(
        (width - 58, 56),
        f"当前积分：{points}",
        font=subtitle_font,
        fill="#515d6e",
        anchor="ra",
    )
    draw.text(
        (width - 58, 94),
        f"第 {page} / {total_pages} 页",
        font=body_font,
        fill=TEXT_SUB,
        anchor="ra",
    )

    grid_origin_x = outer_padding
    grid_origin_y = outer_padding + header_height

    if not page_items:
        draw.text(
            (width // 2, grid_origin_y + 120),
            "当前没有可用商品",
            font=subtitle_font,
            fill=TEXT_SUB,
            anchor="mm",
        )
    else:
        for index, item in enumerate(page_items):
            col = index % GRID_COLUMNS
            row = index // GRID_COLUMNS
            card_x = grid_origin_x + col * (cell_width + gap_x)
            card_y = grid_origin_y + row * (cell_height + gap_y)
            card_box = (card_x, card_y, card_x + cell_width, card_y + cell_height)
            panel_fill = PANEL_BG if index % 2 == 0 else PANEL_ALT_BG

            draw.rounded_rectangle(
                card_box,
                radius=26,
                fill=panel_fill,
                outline=PANEL_BORDER,
                width=2,
            )

            preview_box = (
                card_x + 20,
                card_y + 18,
                card_x + cell_width - 20,
                card_y + 18 + THUMB_FRAME_HEIGHT,
            )
            _draw_preview(image, preview_box, item["asset_name"])

            owned = item["owned"]
            current = item["current"]
            if current:
                status_text = "[使用中]"
                status_color = CURRENT_COLOR
            elif owned:
                status_text = "[已拥有]"
                status_color = OWNED_COLOR
            else:
                status_text = "[未拥有]"
                status_color = UNOWNED_COLOR

            name_text = _clip_name(Path(item["asset_name"]).stem, limit=20)
            number_text = f"#{item['display_id']}"
            price_text = f"价格：{item['price']}积分"

            draw.text(
                (preview_box[0] + 14, preview_box[1] + 12),
                number_text,
                font=tag_font,
                fill=TEXT_MAIN,
            )
            draw.text(
                (preview_box[2] - 14, preview_box[1] + 12),
                status_text,
                font=tag_font,
                fill=status_color,
                anchor="ra",
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

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
