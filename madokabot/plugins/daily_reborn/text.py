"""一键投胎的纯文字档案，不包含历史、资料来源或说明注释。"""

from .anime import ANIME_VERSION
from .anime_life import CATEGORY_NAMES, anime_life_rows
from .attributes import attribute_rows
from .games import GAMES_VERSION, game_detail_rows
from .life import life_rows
from .modes import MODE_NAMES
from .simulation import display_result


def combined_result_text(result: dict) -> str:
    """按模式生成独立消息节点，仅输出抽取内容与属性。"""
    mode = result["mode"]
    title = f"——{MODE_NAMES[mode]}投胎——"
    if result.get("result_version") == ANIME_VERSION:
        content = anime_text(result)
    elif result.get("result_version") == GAMES_VERSION:
        content = games_text(result)
    elif mode in {"anime", "games"}:
        content = identity_text(result)
    elif mode == "isekai":
        content = isekai_text(result)
    else:
        result = display_result(result)
        attributes = "\n".join(
            f"{row['name']}：{row['value_text']} 星（{row['title']}）"
            for row in attribute_rows(result["attributes"])
        )
        life_text = "\n".join(f"{row['label']}：{row['value']}" for row in life_rows(result["life"]))
        content = (
            f"出生地：{result['country']['name']}\n性别：{result['gender']}\n"
            f"抽中概率：{result['probability']:.4%}\n{attributes}\n"
            f"综合评分：{result['score']}/100\n{life_text}"
        )
    return f"{title}\n{content}"


def anime_text(result: dict) -> str:
    """按动漫分类输出星级、阵营评级、存在感、寿命婚育与分数。"""
    world = result["world"]
    lines = [
        f"世界：{world['title']} ｜ {CATEGORY_NAMES[world['category']]}",
        f"世界危险度：{world['danger']}", f"性别：{result['gender']}",
    ]
    lines.extend(f"{row['name']}：{row['value_text']} 星" for row in attribute_rows(result["attributes"]))
    if world["category"] == "battle":
        lines.extend([f"评级：{result['rank']}", f"阵营：{result['faction']}", f"战力：{result['combat']}"])
    lines.extend(f"{row['label']}：{row['value']}" for row in anime_life_rows(result))
    lines.append(f"综合评分：{result['score']}/100")
    return "\n".join(lines)


def identity_text(result: dict) -> str:
    """输出二次元或二游的全部可见随机字段及评级。"""
    lines = [f"世界：{result['world']['title']}", f"性别：{result['gender']}"]
    for section in result["sections"]:
        lines.append(f"——{section['title']}——")
        lines.extend(f"{row['label']}：{row['value']}" for row in section["rows"])
    rating = result["rating"]
    lines.append(f"{rating['label']}：{rating['value']}")
    return "\n".join(lines)


def games_text(result: dict) -> str:
    """输出二游角色的星级、觉醒次数、战斗属性及卡池表现。"""
    awakening = result["awakening"]
    lines = [f"游戏：{result['world']['title']} ｜ 地区：{result['region']}", f"性别：{result['gender']}"]
    lines.extend(f"{row['name']}：{row['value_text']} 星" for row in attribute_rows(result["attributes"]))
    lines.extend([
        f"{awakening['label']}：{awakening['count']}/{awakening['max']}次",
        f"战斗属性：{result['combat_attribute']}",
    ])
    lines.extend(f"{row['label']}：{row['value']}" for row in game_detail_rows(result))
    lines.append(f"综合评级：{result['rating']['value']}")
    return "\n".join(lines)


def isekai_text(result: dict) -> str:
    """输出父母、四项星级、世界专属人生结果及百分制综合评分。"""
    if not all(key in result for key in ("attributes", "life", "score", "body")):
        return "旧档案缺少综合人生数据"
    lines = [f"世界：{result['world']['title']}", f"种族/躯体：{result['body']}", f"性别：{result['gender']}"]
    for parent in result["parents"]:
        lines.append(parent["role"])
        lines.extend(f"{row['label']}：{row['value']}" for row in parent["fields"])
    lines.extend(f"{row['name']}：{row['value_text']}星" for row in attribute_rows(result["attributes"]))
    lines.extend(f"{row['label']}：{row['value']}" for row in result["life"])
    lines.append(f"综合评分：{result['score']}/100")
    return "\n".join(lines)
