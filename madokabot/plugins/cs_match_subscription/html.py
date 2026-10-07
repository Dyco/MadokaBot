"""HTML解析树管理。"""

from collections.abc import Iterator
from contextlib import contextmanager

from bs4 import BeautifulSoup


@contextmanager
def parsed_html(html: str) -> Iterator[BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    try:
        yield soup
    finally:
        # 根节点不连接部分子树，decompose前需逐一销毁子节点。
        soup.clear(decompose=True)
        soup.decompose()
