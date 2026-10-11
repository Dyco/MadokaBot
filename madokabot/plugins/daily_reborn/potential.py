"""根据五项星级评估人生潜力，并生成固定的成长剧本。"""

from .attributes import ATTRIBUTES

EVALUATION_SYSTEM = "potential_v1"
TALENT_FLOORS = {4: 70, 4.5: 82, 5: 90}
# 同时达到三星半的两项属性形成共鸣，既影响评分，也影响成长路线。
SYNERGIES = (
    ("家境", "智力", "资源与头脑", "掌舵开拓者"),
    ("智力", "运气", "灵感与机遇", "灵感破局者"),
    ("魅力", "运气", "舞台与机遇", "聚光灯宠儿"),
    ("健康", "智力", "耐力与专注", "长期探索者"),
    ("健康", "运气", "行动与机遇", "远行探索者"),
    ("家境", "魅力", "资源与人缘", "人脉经营者"),
)
ROUTES = {
    "家境": ("资源掌舵人", (
        ("广阔起点", "成长中可能接触更多课程与见识，早些找到真正想投入的方向。"),
        ("选择与经营", "家庭资源可为创业、专业深造或项目实践提供试错空间。"),
        ("积累影响", "若能把资源转化为可靠能力，有机会经营长期事业与合作网络。"),
    )),
    "健康": ("长线行动派", (
        ("活力启程", "运动、户外和实践活动可能成为成长中最有成就感的一部分。"),
        ("耐力赛道", "适合探索竞技、技术实践或需要长期投入的职业道路。"),
        ("稳步长跑", "持续行动与稳定节奏，有机会让早年的积累越走越扎实。"),
    )),
    "智力": ("知识开拓者", (
        ("求知萌芽", "对复杂问题的好奇可能成为动力，在学习与创作中找到擅长领域。"),
        ("专业突破", "可尝试科研、工程、创意设计等赛道，把理解力转化为作品。"),
        ("建立专长", "若持续钻研，有机会形成独到方法，成为某个领域的专业骨干。"),
    )),
    "魅力": ("聚光灯主角", (
        ("被人看见", "表达与交流可能带来更多朋友，也更容易获得展示自己的机会。"),
        ("走上舞台", "可探索传媒、艺术、公共沟通或需要建立信任的职业。"),
        ("个人名片", "若能持续交付作品与信誉，有机会积累稳定的受众和影响力。"),
    )),
    "运气": ("机遇捕手", (
        ("意外相遇", "成长中可能碰到启发自己的老师、朋友或一次难忘的机会。"),
        ("抓住窗口", "跨领域尝试与主动探索，可能让偶然的相遇变成重要转折。"),
        ("把握转折", "若在机会来临前做好准备，有机会走出一条出人意料的道路。"),
    )),
    "掌舵开拓者": ("掌舵开拓者", (
        ("见识与思考", "学习条件与理解力互相支撑，适合尽早接触真实项目。"),
        ("从想法到实践", "资源和专业能力结合，可探索技术创业、组织管理或创新项目。"),
        ("建立事业", "若能持续做出可靠判断，有机会把早期优势转化为长期事业。"),
    )),
    "灵感破局者": ("灵感破局者", (
        ("灵感萌芽", "好奇心可能恰好遇上合适的引路人，开启一段深入探索。"),
        ("突破窗口", "理解力与机遇相遇，可在科研、技术或创作中尝试独到解法。"),
        ("留下作品", "若能坚持把灵感完成，有机会凭代表作或关键成果被人记住。"),
    )),
    "聚光灯宠儿": ("聚光灯宠儿", (
        ("偶遇舞台", "表达天赋可能遇上一次合适的展示机会，让更多人注意到你。"),
        ("扩大舞台", "可探索内容、表演或公共表达，把关注转化为扎实的作品。"),
        ("形成风格", "持续输出与珍惜信任，有机会形成鲜明的个人品牌。"),
    )),
    "长期探索者": ("长期探索者", (
        ("扎实积累", "理解力和行动耐力互相配合，适合通过实践验证好奇心。"),
        ("深耕难题", "可探索工程、科研或长期训练，把复杂任务拆成持续的进步。"),
        ("厚积薄发", "若能长期保持投入，有机会完成难度较高、积累较深的成果。"),
    )),
    "远行探索者": ("远行探索者", (
        ("向外探索", "行动力可能带来更多见识与相遇，在实践中认识自己的边界。"),
        ("打开新地图", "可探索户外、竞技、跨地区项目等需要行动与应变的方向。"),
        ("经验成路", "若能把经历整理成专长，有机会走出兼具自由与积累的道路。"),
    )),
    "人脉经营者": ("人脉经营者", (
        ("广结善缘", "成长环境与表达优势配合，可能较早学会交流和组织协作。"),
        ("连接机会", "可探索商务、文化项目或组织协调，让合适的人一起完成事情。"),
        ("长期信任", "若能珍惜信誉并持续兑现承诺，有机会建立稳定的合作网络。"),
    )),
    "全面发展者": ("全面发展者", (
        ("多向尝试", "五项基础较为均衡，适合多尝试几种学习、实践与表达方式。"),
        ("选择主线", "可在专业、组织与创作之间找到交点，逐渐明确自己的主赛道。"),
        ("稳中拓展", "较少的明显短板有利于长期发展，关键是持续积累而非频繁换路。"),
    )),
    "逆风筑梦人": ("逆风筑梦人", (
        ("慢慢扎根", "起步条件比较普通，规律生活与一项实用技能会成为稳固基础。"),
        ("小步积累", "从可完成的目标出发，通过作品、经验与可信赖的合作获得进步。"),
        ("写出自己的路", "如果持续积累，也有机会拥有一份稳定专长和自己珍视的生活。"),
    )),
}
CHALLENGES = {
    "家境": "起步资源有限，前期更适合积累技能与合作机会。",
    "健康": "精力储备偏低，成长节奏需要留出休息与调整空间。",
    "智力": "学习可能需要更多时间，稳定的方法与重复练习更能发挥优势。",
    "魅力": "社交起步较慢，作品与长期信任会成为更稳的名片。",
    "运气": "偶然机会较少，持续准备和主动争取会是更稳的支撑。",
}


def score_label(score: int) -> tuple[str, str]:
    """按综合潜力分给出评级与基础寄语。"""
    for threshold, label, comment in (
        (85, "SSR · 天选开局", "你抽到了闪闪发光的起点，接下来去写自己的故事吧。"),
        (70, "SR · 顺风启程", "行囊里装着不少好牌，勇敢出发就好。"),
        (50, "R · 平凡新生", "平凡的开场，也可以走向很精彩的远方。"),
        (0, "N · 逆风成长", "开局有些挑战，但人生的后续章节还留着空白。"),
    ):
        if score >= threshold:
            return label, comment
    raise ValueError("综合分不能小于零")


def active_synergies(stars: dict) -> list[tuple]:
    """找出两项均达到三星半的属性组合，顺序固定以保持结果可重复。"""
    return [pair for pair in SYNERGIES if stars[pair[0]] >= 3.5 and stars[pair[1]] >= 3.5]


def calculate_score(stars: dict) -> tuple[int, dict]:
    """合并基础、天赋保底、配套支撑、多项高星、共鸣与均衡加分，上限一百分。"""
    values = list(stars.values())
    peak = max(values)
    base = round(sum(values) / len(values) * 20)
    parts = {
        "基础": base,
        "天赋": max(0, TALENT_FLOORS.get(peak, 0) - base),
        "支撑": min(6, int((sum(values) - peak - 4) / 2)) if peak >= 4 else 0,
        "高星": max(0, sum(value >= 4 for value in values) - 1) * 3,
        "共鸣": min(9, len(active_synergies(stars)) * 3),
        "均衡": 4 if min(values) >= 3 else 2 if min(values) >= 2.5 else 0,
    }
    return min(100, sum(parts.values())), parts


def evaluate_life(stars: dict) -> dict:
    """从固定属性推导评级、优势与三阶段剧本，不使用新的随机数。"""
    score, parts = calculate_score(stars)
    label, fallback = score_label(score)
    dominant = max(ATTRIBUTES, key=lambda name: stars[name])
    weakest = min(ATTRIBUTES, key=lambda name: stars[name])
    peak = stars[dominant]
    pairs = active_synergies(stars)
    best_pair = max(pairs, key=lambda pair: stars[pair[0]] + stars[pair[1]], default=None)
    if max(stars.values()) <= 2:
        route = "逆风筑梦人"
    elif min(stars.values()) >= 3:
        route = "全面发展者"
    elif best_pair and (peak < 4.5 or dominant in best_pair[:2]):
        route = best_pair[3]
    else:
        route = dominant
    title, stages = ROUTES[route]
    highlights = []
    if peak >= 4:
        highlights.append(f"{dominant} {peak:g} 星 · 天赋突出")
    highlights.extend(pair[2] for pair in pairs[:2])
    if parts["均衡"]:
        highlights.append("五项基础均衡")
    if not highlights:
        highlights.append(f"围绕{dominant}逐步积累")
    if peak == 5:
        summary = f"{dominant}达到传说级，即使其他条件普通，也拥有一条格外突出的优势赛道。"
    elif peak == 4.5:
        summary = f"{dominant}是极罕见的强项，围绕这项优势深耕，有机会打开更大的成长空间。"
    elif peak == 4:
        summary = f"{dominant}明显突出，选择能发挥它的方向，比单纯追求面面俱到更有潜力。"
    elif min(stars.values()) >= 3:
        summary = "五项基础都较为扎实，适合在多次尝试中找到方向，再把积累做深。"
    else:
        summary = fallback
    challenge = CHALLENGES[weakest] if stars[weakest] <= 1.5 else (
        "五项没有明显短板，选定方向后的持续积累更重要。" if min(stars.values()) >= 3
        else f"可以优先补强{weakest}，让优势更容易转化为长期成果。"
    )
    return {
        "evaluation_system": EVALUATION_SYSTEM, "score": score, "label": label, "comment": summary,
        "potential": {
            "title": title, "summary": summary, "highlights": highlights[:3],
            "challenge": challenge, "breakdown": parts,
            "stages": [{"stage": stage, "title": heading, "text": text} for stage, (heading, text) in zip(("少年", "青年", "中年"), stages)],
        },
    }
