from madokabot.core.resources import ResourceType, ResourceFolder, get_file

unknown_avatar_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "unknown_avatar.jpg")
parent_status_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "parent_status.png")
friends_search_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "friends_search.png")
busy_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "busy.png")
zzz_online_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "zzz_online.png")
zzz_gaming_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "zzz_gaming.png")
gaming_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "gaming.png")
default_background_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "bg_dots.png")
default_avatar_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "unknown_avatar.jpg")
default_achievement_image_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "default_achievement_image.png")
default_header_image_path = get_file(ResourceType.IMAGE, ResourceFolder.STEAM, "default_header_image.jpg")

font_regular_path = get_file(ResourceType.FONT, ResourceFolder.STEAM, "MiSans-Regular.ttf")
font_light_path   = get_file(ResourceType.FONT, ResourceFolder.STEAM, "MiSans-Light.ttf")
font_bold_path    = get_file(ResourceType.FONT, ResourceFolder.STEAM, "MiSans-Bold.ttf")

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
