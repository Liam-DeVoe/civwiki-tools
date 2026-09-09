"""Pure-text wikitext primitives shared by the index builder and rules."""

import re
from collections.abc import Iterable, Iterator

# Canonical category-link matcher, based on the strictest historical variant.
# The namespace word is case-insensitive; `name` excludes brackets, pipes,
# and newlines and is whitespace-trimmed; `sortkey` is everything after the
# first pipe (and may itself contain pipes).
CATEGORY_RE = re.compile(
    r"\[\[\s*(?i:category)\s*:\s*(?P<name>[^\[\]\|\n]*?)\s*"
    r"(?:\|(?P<sortkey>[^\[\]\n]*))?\]\]"
)

# Canonical #REDIRECT matcher, used with .match() at page start. Tolerances
# are the deliberate union of the historical per-caller variants: optional
# ':' after #REDIRECT, an optional #fragment, an optional |piped suffix,
# exactly one leading '#', and an optional closing ]] (some working
# redirects have a ']' inside the fragment, keeping ']]' from ever matching).
REDIRECT_RE = re.compile(
    r"\s*#redirect\s*:?\s*(?P<open>\[\[)(?P<target>[^\]|#\n]+)"
    r"(?P<fragment>#[^\]|\n]*)?(?:\|[^\]\n]*)?(?:\]\])?",
    re.IGNORECASE,
)

# A heading line: an = run, a title, the same run, optional trailing
# whitespace. Mismatched runs still match on the shorter run, like mediawiki.
HEADING_RE = re.compile(
    r"^(?P<eq>={1,6})(?P<title>.+?)(?P=eq)(?P<trail>[ \t]*)$", re.MULTILINE
)

# A File:/Image: namespace prefix, as at the start of a file link's title.
FILE_PREFIX_RE = re.compile(r"\s*(?:file|image)\s*:", re.IGNORECASE)

# An html comment. An unclosed comment runs to end of page, matching both
# mediawiki rendering and context.py's shield regex.
COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)


def overlaps(spans: Iterable[tuple[int, int]], start: int, end: int) -> bool:
    """True if the half-open interval [start, end) intersects any span."""
    return any(s < end and start < e for s, e in spans)


def split_top_level(s: str) -> Iterator[tuple[int, int]]:
    """(start, end) spans of |-separated segments of s, ignoring pipes
    nested inside [[...]] or {{...}}."""
    depth = start = i = 0
    while i < len(s):
        if s[i : i + 2] in ("[[", "{{"):
            depth += 1
            i += 2
        elif s[i : i + 2] in ("]]", "}}"):
            depth -= 1
            i += 2
        elif s[i] == "|" and depth == 0:
            yield start, i
            start = i = i + 1
        else:
            i += 1
    yield start, len(s)


def remove_span_and_line(text: str, start: int, end: int) -> tuple[int, int]:
    """Deletion span for removing text[start:end]: the span itself if other
    text shares its line, else the whole line including its newline."""
    line_start = text.rfind("\n", 0, start) + 1
    nl = text.find("\n", end)
    line_end = len(text) if nl == -1 else nl
    if text[line_start:start].strip() or text[end:line_end].strip():
        return start, end
    return line_start, min(line_end + 1, len(text))


_ONLYINCLUDE_RE = re.compile(
    r"<onlyinclude>(.*?)</onlyinclude>", re.DOTALL | re.IGNORECASE
)
_NOINCLUDE_RE = re.compile(
    r"<noinclude>.*?(?:</noinclude>|\Z)", re.DOTALL | re.IGNORECASE
)
_INCLUDEONLY_TAG_RE = re.compile(r"</?includeonly>", re.IGNORECASE)


def transcluded_spans(text: str) -> list[tuple[int, int]]:
    """Spans of `text` that a transclusion of this page emits.

    With <onlyinclude>, only those blocks transclude; otherwise everything
    except <noinclude> blocks and the <includeonly> tags themselves.
    """
    if _ONLYINCLUDE_RE.search(text):
        return [m.span(1) for m in _ONLYINCLUDE_RE.finditer(text)]
    excluded = [m.span() for m in _NOINCLUDE_RE.finditer(text)]
    excluded += [m.span() for m in _INCLUDEONLY_TAG_RE.finditer(text)]
    excluded.sort()
    spans, pos = [], 0
    for s, e in excluded:
        if s > pos:
            spans.append((pos, s))
        pos = max(pos, e)
    if pos < len(text):
        spans.append((pos, len(text)))
    return spans
