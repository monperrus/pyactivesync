"""MS-ASWBXML binary XML codec: writer, reader, and small tree helpers."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from ._codepages import CODEPAGES, PAGE_INDEX, PAGE_ORDER, REVERSE

SWITCH_PAGE = 0x00
END = 0x01
ENTITY = 0x02
STR_I = 0x03
LITERAL = 0x04
OPAQUE = 0xC3

# A parsed WBXML node: (tag_path, text-or-None, children). Leaf text/opaque
# nodes use the synthetic tag paths "#text" / "#opaque".
Node = tuple[str, "str | bytes | None", list[Any]]
NodeBuilder = Callable[["WBXMLWriter"], None]


def _mb_uint_bytes(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


class WBXMLWriter:
    """Builds a WBXML document from a nested tree of ``tag()``/``wtag()`` calls."""

    def __init__(self) -> None:
        self.body = bytearray()
        self.current_page = 0

    def _switch(self, page_name: str) -> None:
        page = PAGE_INDEX[page_name]
        if page != self.current_page:
            self.body.append(SWITCH_PAGE)
            self.body.append(page)
            self.current_page = page

    def tag(
        self,
        page_name: str,
        name: str,
        children: Iterable[NodeBuilder] | None = None,
        text: str | None = None,
        opaque: bytes | None = None,
    ) -> WBXMLWriter:
        self._switch(page_name)
        token = CODEPAGES[page_name][name]
        has_content = bool(children) or text is not None or opaque is not None
        self.body.append(token | (0x40 if has_content else 0x00))
        if text is not None:
            self.body.append(STR_I)
            self.body.extend(text.encode("utf-8"))
            self.body.append(0x00)
        if opaque is not None:
            self.body.append(OPAQUE)
            self.body.extend(_mb_uint_bytes(len(opaque)))
            self.body.extend(opaque)
        if children:
            for child in children:
                child(self)
        if has_content:
            self.body.append(END)
        return self

    def render(self) -> bytes:
        header = bytes([0x03, 0x01, 0x6A, 0x00])  # version 1.3, unknown PID, UTF-8, no str table
        return header + bytes(self.body)


def wtag(
    page: str,
    name: str,
    children: Iterable[NodeBuilder] | None = None,
    text: str | None = None,
    opaque: bytes | None = None,
) -> NodeBuilder:
    """Return a closure that appends one tag (+ children) into a WBXMLWriter."""

    def build(writer: WBXMLWriter) -> None:
        writer.tag(page, name, children, text, opaque)

    return build


class WBXMLReader:
    """Parses a WBXML document into a tree of ``Node`` tuples."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 3  # skip version, publicid, charset
        strtbl_len, self.pos = self._mb_uint()
        self.pos += strtbl_len  # skip string table
        self.page = 0

    def _mb_uint(self, pos: int | None = None) -> tuple[int, int]:
        result = 0
        pos = self.pos if pos is None else pos
        while True:
            b = self.data[pos]
            result = (result << 7) | (b & 0x7F)
            pos += 1
            if not (b & 0x80):
                break
        return result, pos

    def parse(self) -> list[Node]:
        nodes, self.pos = self._parse_body(self.pos)
        return nodes

    def _parse_body(self, pos: int) -> tuple[list[Node], int]:
        nodes: list[Node] = []
        while pos < len(self.data):
            b = self.data[pos]
            if b == END:
                return nodes, pos + 1
            if b == SWITCH_PAGE:
                self.page = self.data[pos + 1]
                pos += 2
                continue
            if b == STR_I:
                end = self.data.index(0x00, pos + 1)
                nodes.append(("#text", self.data[pos + 1 : end].decode("utf-8"), []))
                pos = end + 1
                continue
            if b == OPAQUE:
                length, pos = self._mb_uint(pos + 1)
                nodes.append(("#opaque", self.data[pos : pos + length], []))
                pos += length
                continue
            has_content = bool(b & 0x40)
            token = b & 0x3F
            page_name = PAGE_ORDER.get(self.page, f"page{self.page}")
            tag_name = REVERSE.get(self.page, {}).get(token, f"0x{token:02X}")
            pos += 1
            children: list[Node] = []
            if has_content:
                children, pos = self._parse_body(pos)
            nodes.append((f"{page_name}.{tag_name}", None, children))
        return nodes, pos


def find(nodes: list[Node], path: str) -> Node | None:
    """Find the first descendant node by dotted tag path, e.g. ``"FolderHierarchy.FolderSync"``."""
    for name, text, children in nodes:
        if name == path:
            return name, text, children
        found = find(children, path)
        if found:
            return found
    return None


def find_all(nodes: list[Node], path: str) -> list[Node]:
    out: list[Node] = []
    for name, text, children in nodes:
        if name == path:
            out.append((name, text, children))
        out.extend(find_all(children, path))
    return out


def text_of(node: Node | None) -> str | None:
    if not node:
        return None
    _, _, children = node
    for name, text, _ in children:
        if name == "#text":
            assert text is None or isinstance(text, str)
            return text
    return None


def opaque_of(node: Node | None) -> bytes | None:
    if not node:
        return None
    _, _, children = node
    for name, data, _ in children:
        if name == "#opaque":
            assert isinstance(data, (bytes, bytearray))
            return bytes(data)
    return None


def leaves(nodes: list[Node]) -> dict[str, str]:
    """Flatten a subtree into ``{tag_name: text}`` for every leaf with text content."""
    out: dict[str, str] = {}
    for name, _, children in nodes:
        text = next((t for n, t, _ in children if n == "#text"), None)
        if text is not None:
            out[name] = text
        else:
            out.update(leaves(children))
    return out
