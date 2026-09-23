"""限定 HTML 解析树的生命周期，避免大批循环引用等待 GC。"""

from collections.abc import Iterator
from contextlib import contextmanager

from bs4 import BeautifulSoup


@contextmanager
def parsed_html(html: str) -> Iterator[BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    try:
        yield soup
    finally:
        # html.parser 创建的根节点 next_element 可能为 None；仅调用
        # soup.decompose() 不会遍历这些子树，必须先显式销毁子节点。
        soup.clear(decompose=True)
        soup.decompose()
