from ..madoka_bundle.utils import get_file
from ..madoka_bundle.constants import ResType, SubFolder

unknown_avatar_path = get_file(ResType.IMAGE, SubFolder.STEAM, "unknown_avatar.jpg")
parent_status_path = get_file(ResType.IMAGE, SubFolder.STEAM, "parent_status.png")
friends_search_path = get_file(ResType.IMAGE, SubFolder.STEAM, "friends_search.png")
busy_path = get_file(ResType.IMAGE, SubFolder.STEAM, "busy.png")
zzz_online_path = get_file(ResType.IMAGE, SubFolder.STEAM, "zzz_online.png")
zzz_gaming_path = get_file(ResType.IMAGE, SubFolder.STEAM, "zzz_gaming.png")
gaming_path = get_file(ResType.IMAGE, SubFolder.STEAM, "gaming.png")
default_background_path = get_file(ResType.IMAGE, SubFolder.STEAM, "bg_dots.png")
default_avatar_path = get_file(ResType.IMAGE, SubFolder.STEAM, "unknown_avatar.jpg")
default_achievement_image_path = get_file(ResType.IMAGE, SubFolder.STEAM, "default_achievement_image.png")
default_header_image_path = get_file(ResType.IMAGE, SubFolder.STEAM, "default_header_image.jpg")

font_regular_path = get_file(ResType.FONT, SubFolder.STEAM, "MiSans-Regular.ttf")
font_light_path   = get_file(ResType.FONT, SubFolder.STEAM, "MiSans-Light.ttf")
font_bold_path    = get_file(ResType.FONT, SubFolder.STEAM, "MiSans-Bold.ttf")

__all__ = [
    "unknown_avatar_path",
    "parent_status_path",
    "friends_search_path",
    "busy_path",
    "zzz_online_path",
    "zzz_gaming_path",
    "gaming_path",
    "font_regular_path",
    "font_light_path",
    "font_bold_path",
    "default_background_path",
    "default_avatar_path",
    "default_achievement_image_path",
    "default_header_image_path",
]
