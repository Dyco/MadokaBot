"""一键投胎的纯文字档案，不包含历史、资料来源或说明注释。"""

from .attributes import attribute_rows
from .modes import MODE_NAMES
from .simulation import display_result


def combined_result_text(result: dict) -> str:
    """按模式生成独立消息节点，仅输出抽取内容与属性。"""
    mode = result["mode"]
    title = f"——{MODE_NAMES[mode]}投胎——"
    if mode in {"anime", "games"}:
        content = identity_text(result)
    elif mode == "isekai":
        content = isekai_text(result)
    else:
        result = display_result(result)
        attributes = "\n".join(
            f"{row['name']}：{row['value_text']} 星（{row['title']}）"
            for row in attribute_rows(result["attributes"])
        )
        content = (
            f"出生地：{result['country']['name']}\n性别：{result['gender']}\n"
            f"抽中概率：{result['probability']:.4%}\n{attributes}\n"
            f"综合潜力：{result['score']}/100 · {result['label']}"
        )
    return f"{title}\n{content}"


def identity_text(result: dict) -> str:
    """输出二次元或二游的全部可见随机字段及评级。"""
    lines = [f"世界：{result['world']['title']}", f"性别：{result['gender']}"]
    for section in result["sections"]:
        lines.append(f"——{section['title']}——")
        lines.extend(f"{row['label']}：{row['value']}" for row in section["rows"])
    rating = result["rating"]
    lines.append(f"{rating['label']}：{rating['value']}")
    return "\n".join(lines)


def isekai_text(result: dict) -> str:
    """输出异世界出生条件、父母身份与力量及家庭成长内容。"""
    child = result["child"]
    household = result["household"]
    lineage = f" · {child['lineage']}" if child["lineage"] else ""
    lines = [f"世界：{result['world']['title']}"]
    if "setting" in result:
        lines.append(f"时代：{result['setting']['name']}")
    lines.extend([
        f"出生地：{result['birthplace']['name']}",
        f"种族：{child['species']}{lineage}",
        f"性别：{result['gender']}",
        f"出生状态：{child['birth_state']}",
        f"家庭：{household['name']}（{household['rarity']}）",
    ])
    for parent in result["parents"]:
        lineage = f" · {parent['lineage']}" if parent["lineage"] else ""
        powers = "；".join(power["name"] for power in parent.get("powers", [parent["power"]]))
        lines.extend([
            f"{parent['role']}：{parent['species']}{lineage} · {parent['occupation']}",
            f"身份：{parent['identity']}",
            f"实力：{powers}",
        ])
        if parent.get("affiliation"):
            lines.append(f"关系：{parent['affiliation']}")
    lines.append(f"家庭资源：{'、'.join(household['resources'])}")
    lines.append(f"{child.get('trait_label', '先天特征')}：{child['trait']['name']}")
    lines.extend(f"{row['label']}：{row['name']}" for row in child.get("aspects", []))
    lines.extend([
        f"成长方向：{'、'.join(household['directions'])}",
        f"成长课题：{household['challenge']}",
    ])
    return "\n".join(lines)
