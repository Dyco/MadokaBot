import re
from html import unescape as html_unescape

import bbcode
from pyquery import PyQuery as Pq
from yarl import URL

from .config import config


def handle_bbcode(html: Pq) -> str:
    rss_str = html_unescape(str(html))

    rss_str = re.sub(
        r"(\[url=[^]]+])?\[img[^]]*].+\[/img](\[/url])?", "", rss_str, flags=re.I
    )

    bbcode_tags = [
        "align",
        "b",
        "backcolor",
        "color",
        "font",
        "size",
        "table",
        "tbody",
        "td",
        "tr",
        "u",
        "url",
    ]

    for i in bbcode_tags:
        rss_str = re.sub(rf"\[{i}=[^]]+]", "", rss_str, flags=re.I)
        rss_str = re.sub(rf"\[/?{i}]", "", rss_str, flags=re.I)

    rss_str = re.sub(
        r"(\[[^]]+|\[img][^\[\]]+) \.\.\n?</p>", "</p>", rss_str, flags=re.I
    )

    bbcode_search = re.search(r"\[/(\w+)]", rss_str)
    if bbcode_search and re.search(f"\\[{bbcode_search[1]}", rss_str):
        parser = bbcode.Parser()
        parser.escape_html = False
        rss_str = parser.format(rss_str)

    return rss_str


def handle_lists(html: Pq, rss_str: str) -> str:
    for ul in html("ul").items():
        for li in ul("li").items():
            li_str_search = re.search("<li>(.+)</li>", repr(str(li)))
            rss_str = rss_str.replace(
                str(li), f"\n- {li_str_search[1]}"  # type: ignore
            ).replace("\\n", "\n")
    for ol in html("ol").items():
        for index, li in enumerate(ol("li").items()):
            li_str_search = re.search("<li>(.+)</li>", repr(str(li)))
            rss_str = rss_str.replace(
                str(li), f"\n{index + 1}. {li_str_search[1]}"  # type: ignore
            ).replace("\\n", "\n")
    rss_str = re.sub("</(ul|ol)>", "\n", rss_str)
    rss_str = rss_str.replace("<li>", "- ").replace("</li>", "")
    return rss_str


def handle_links(html: Pq, rss_str: str) -> str:
    for a in html("a").items():
        a_match = re.search(
            r"<a [^>]+>.*?</a>", html_unescape(str(a)), flags=re.DOTALL
        )
        if not a_match:
            continue
        a_str = a_match.group()
        href = a.attr("href") or ""
        if a.text() and str(a.text()) != href:
            if re.search(
                r"https://m\.weibo\.cn/p/index\?extparam=\S+&containerid=\w+",
                href,
            ):
                rss_str = rss_str.replace(a_str, "")
            elif (
                href.startswith("https://m.weibo.cn/search?containerid=")
                and re.search("#.+#", a.text())
            ) or (
                href.startswith("https://weibo.com/")
                and a.text().startswith("@")
            ):
                rss_str = rss_str.replace(a_str, a.text())
            else:
                if href.startswith("https://weibo.cn/sinaurl?u="):
                    href = URL(href).query.get("u", href)
                rss_str = rss_str.replace(a_str, f" {a.text()}: {href}\n")
        else:
            rss_str = rss_str.replace(a_str, f" {href}\n")
    return rss_str


def handle_html_tag(html: Pq) -> str:
    rss_str = html_unescape(str(html))

    rss_str = handle_lists(html, rss_str)
    rss_str = handle_links(html, rss_str)

    html_tags = [
        "b",
        "blockquote",
        "code",
        "dd",
        "del",
        "div",
        "dl",
        "dt",
        "em",
        "figure",
        "font",
        "i",
        "iframe",
        "ol",
        "p",
        "pre",
        "s",
        "small",
        "span",
        "strong",
        "sub",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    ]

    for i in ["p", "pre"]:
        rss_str = re.sub(f"</{i}>", f"</{i}>\n\n", rss_str)

    for i in html_tags:
        rss_str = re.sub(f"<{i} [^>]+>", "", rss_str)
        rss_str = re.sub(f"</?{i}>", "", rss_str)

    rss_str = re.sub(r"<(br|hr)\s?/?>|<(br|hr) [^>]+>", "\n", rss_str)
    rss_str = re.sub(r"<h\d [^>]+>", "\n", rss_str)
    rss_str = re.sub(r"</?h\d>", "\n", rss_str)

    rss_str = re.sub(
        r"<video[^>]*>(.*?</video>)?|<img[^>]+>", "", rss_str, flags=re.DOTALL
    )

    while "\n\n\n" in rss_str:
        rss_str = rss_str.replace("\n\n\n", "\n\n")
    rss_str = rss_str.strip()

    if 0 < config.max_length < len(rss_str):
        rss_str = f"{rss_str[: config.max_length]}..."

    return rss_str
