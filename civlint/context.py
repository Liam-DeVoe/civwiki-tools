import re
from collections.abc import Iterable, Iterator
from functools import cached_property
from typing import TYPE_CHECKING

import mwparserfromhell

from civlint.wikitext import overlaps

if TYPE_CHECKING:
    from civlint.index import SiteIndex

# Regions whose contents must never be linted or edited: html comments and
# tags whose body is not wikitext. An unclosed tag shields to end of page,
# matching how mediawiki renders it.
_SHIELD_TAGS = "nowiki|pre|syntaxhighlight|source|code|math|score|templatedata"
_SHIELD_RE = re.compile(
    rf"<!--.*?(?:-->|\Z)"
    rf"|<(?P<tag>{_SHIELD_TAGS})\b[^<>]*/>"
    rf"|<(?P<tag2>{_SHIELD_TAGS})\b[^<>]*>.*?(?:</(?P=tag2)\s*>|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_SUPPRESS_RE = re.compile(r"<!--\s*civlint:\s*disable=([\w\s,]+?)\s*-->")

_TEMPLATE_TOKEN_RE = re.compile(r"\{\{|\}\}")
_MASK_TOKEN_RE = re.compile(r"\{\{|\}\}|\{\||\|\}")


class PageContext:
    def __init__(self, title: str, text: str, index: "SiteIndex | None" = None):
        self.title = title
        self.text = text
        self.index = index

    @cached_property
    def wikicode(self) -> mwparserfromhell.wikicode.Wikicode:
        return mwparserfromhell.parse(self.text)

    @cached_property
    def shielded(self) -> list[tuple[int, int]]:
        """Spans of comments/nowiki/pre/etc, sorted, non-overlapping."""
        return [m.span() for m in _SHIELD_RE.finditer(self.text)]

    def is_shielded(self, start: int, end: int | None = None) -> bool:
        """True if [start, end) overlaps any shielded region."""
        if end is None:
            end = start + 1
        return overlaps(self.shielded, start, end)

    def finditer(self, pattern: str | re.Pattern) -> Iterator[re.Match]:
        """re.finditer over the page text, skipping shielded matches."""
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        for m in pattern.finditer(self.text):
            if not self.is_shielded(*m.span()):
                yield m

    def _bracket_spans(
        self, token_re: re.Pattern, keep_unclosed: bool
    ) -> list[tuple[int, int]]:
        """Outermost spans of balanced bracket runs over unshielded tokens."""
        spans: list[tuple[int, int]] = []
        stack: list[int] = []
        for m in self.finditer(token_re):
            if m.group() in ("{{", "{|"):
                stack.append(m.start())
            elif stack:
                start = stack.pop()
                if not stack:
                    spans.append((start, m.end()))
        if stack and keep_unclosed:
            spans.append((stack[0], len(self.text)))
        return spans

    @cached_property
    def template_spans(self) -> list[tuple[int, int]]:
        """Spans of outermost {{...}} runs; unclosed runs are dropped."""
        return self._bracket_spans(_TEMPLATE_TOKEN_RE, keep_unclosed=False)

    @cached_property
    def mask_spans(self) -> list[tuple[int, int]]:
        """Spans of outermost {{...}} / {|...|} runs, sharing one stack (a
        }} may close a {|, as in loose real-world markup); an unclosed run
        extends to end of page."""
        return self._bracket_spans(_MASK_TOKEN_RE, keep_unclosed=True)

    def node_spans(self, nodes: Iterable) -> Iterator[tuple[int, int, object]]:
        """(start, end, node) for mwparserfromhell nodes in document order.

        Locates each node with an advancing text.find on str(node); nodes
        whose text cannot be found are skipped. The cursor advances only
        past a node's start so nested nodes are still found. No shield
        check: callers differ on what part of the node must be unshielded.
        """
        cursor = 0
        for node in nodes:
            raw = str(node)
            start = self.text.find(raw, cursor)
            if start == -1:
                continue
            cursor = start + 1
            yield start, start + len(raw), node

    @cached_property
    def suppressed(self) -> set[str]:
        """Codes/prefixes disabled page-wide via `civlint: disable=...`."""
        codes: set[str] = set()
        for m in _SUPPRESS_RE.finditer(self.text):
            # only honor real comments: a disable comment quoted inside
            # <nowiki>/<pre> (e.g. on a page documenting civlint) is display
            # text, not a directive. Its enclosing shield span starts before
            # the "<!--"; a genuine comment's shield span starts exactly at it.
            if any(s < m.start() and m.end() <= e for s, e in self.shielded):
                continue
            codes.update(c.strip() for c in m.group(1).split(",") if c.strip())
        return codes
