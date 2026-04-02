import math
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ...config import assets
from ...constants import ResType, SubFolder


# --- 樋口円香 清冷色调 (Cool / Elegant Palette) ---
CARD_BG = "#e5e8ec"          # 外层背景：冷灰白
PANEL_BG = "#f2f4f7"         # 卡片背景：透亮的冷白色
PANEL_ALT_BG = "#ebedf2"     # 交替卡片背景：微暗的冷灰色
PANEL_BORDER = "#cdd3dc"     # 卡片边框：柔和的灰蓝色
TEXT_MAIN = "#2d3440"        # 主文本：深灰蓝/夜蓝色
TEXT_SUB = "#6c7686"         # 副文本：冷铅灰色
OWNED_COLOR = "#3c7a89"      # 已拥有：沉静的灰青色
UNOWNED_COLOR = "#8e5a65"    # 未拥有：冷调的暗蔷薇色

THUMB_HEIGHT = 300
THUMB_FRAME_HEIGHT = THUMB_HEIGHT + 20
GRID_COLUMNS = 4
GRID_ROWS = 3
PAGE_SIZE = GRID_COLUMNS * GRID_ROWS


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_name = "MiSans-Bold.ttf" if bold else "MiSans-Regular.ttf"
    font_path = assets.get_dir(ResType.FONT, SubFolder.STEAM) / font_name
    if font_path.exists():
        return ImageFont.truetype(str(font_path), size)
    return ImageFont.load_default()


def _clip_name(name: str, limit: int = 18) -> str:
    if len(name) <= limit:
        return name
    return name[: limit - 3] + "..."


def _load_skin_image(asset_name: str) -> Image.Image | None:
    image_path = assets.get_dir(ResType.IMAGE, SubFolder.CHAR) / asset_name
    if not image_path.exists():
        return None
    try:
        return Image.open(image_path).convert("RGBA")
    except Exception:
        return None


def _resize_preview(image: Image.Image, max_width: int) -> Image.Image:
    if image.height <= 0:
        return image

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
    hint_font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
) -> None:
    draw = ImageDraw.Draw(canvas)
    x1, y1, x2, y2 = panel_box
    
    # 预览图背景也改为匹配的清冷色
    draw.rounded_rectangle(panel_box, radius=18, fill="#e8ebf0", outline="#d5dbe4", width=2)

    preview = _load_skin_image(asset_name)
    if preview is None:
        draw.text(
            ((x1 + x2) // 2, (y1 + y2) // 2),
            "资源缺失",
            font=hint_font,
            fill=TEXT_SUB,
            anchor="mm",
        )
        return

    resized = _resize_preview(preview, max_width=(x2 - x1) - 24)
    paste_x = x1 + ((x2 - x1) - resized.width) // 2
    paste_y = y2 - resized.height
    canvas.alpha_composite(resized, (paste_x, paste_y))


def render_shop_list_card(
    items: list[dict],
    points: int,
    page: int = 1,
    page_size: int = PAGE_SIZE,
    total_pages: int | None = None,
) -> bytes:
    total_pages = total_pages or max(1, math.ceil(len(items) / page_size))
    page = max(1, min(page, total_pages))
    page_items = items[(page - 1) * page_size : page * page_size]

    title_font = _load_font(44, bold=True)      # 略微调小一点标题，显得更精致
    subtitle_font = _load_font(24, bold=True)
    body_font = _load_font(20)                  # 【缩小2点】配合扩大的宽度，彻底告别超框
    small_font = _load_font(18)
    tag_font = _load_font(18, bold=True)

    outer_padding = 34
    header_height = 142
    footer_height = 24
    cell_width = 400                            # 【扩大宽度】原320 -> 400
    cell_height = 420                           # 【适度扩大高度】原414 -> 420
    gap_x = 24                                  # 卡片间距也稍微拉开一点，呼吸感更强
    gap_y = 24

    width = outer_padding * 2 + GRID_COLUMNS * cell_width + (GRID_COLUMNS - 1) * gap_x
    height = (
        outer_padding * 2
        + header_height
        + footer_height
        + GRID_ROWS * cell_height
        + (GRID_ROWS - 1) * gap_y
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
        fill="#515d6e",  # 替换原本的暖棕色为冷蓝灰
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
            panel_fill = PANEL_BG if (index % 2 == 0) else PANEL_ALT_BG

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
            _draw_preview(image, preview_box, item["asset_name"], small_font)

            owned = item["owned"]
            status_text = "[已拥有]" if owned else "[未拥有]"
            status_color = OWNED_COLOR if owned else UNOWNED_COLOR
            name_text = _clip_name(Path(item["asset_name"]).stem, limit=20) # 宽度够了，可以允许更长的截断限制
            number_text = f"#{item['item_id']}"
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

            # 【修复间距问题】
            text_y = preview_box[3] + 14  # 拉近图片底框与价格文本的距离 (原先是 + 20)
            draw.text((card_x + 24, text_y), price_text, font=body_font, fill="#616f82") # 使用低饱和度蓝灰色
            draw.text((card_x + 24, text_y + 28), name_text, font=body_font, fill=TEXT_MAIN) # 行距缩小 (原先是 + 40)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()