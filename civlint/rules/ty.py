"""ty rules. See civlint/README.md for conventions."""

import re
from pathlib import Path

from mwparserfromhell import nodes

from civlint.types import Applicability, Edit, Finding, Fix, rule
from civlint.wikitext import overlaps

_DATA = Path(__file__).resolve().parent.parent / "data" / "typos.txt"


def _load_typos() -> dict[str, list[str]]:
    typos: dict[str, list[str]] = {}
    for line in _DATA.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        misspelling, corrections = line.split("\t")
        typos[misspelling.lower()] = corrections.split("|")
    return typos


_TYPOS = _load_typos()

# Standalone word tokens: runs of letters (apostrophes allowed inside) with
# no letter/digit/underscore/hyphen adjacent, so usernames like "Teh_Legend"
# and substrings like "tehsils" never match. Each token is looked up in
# _TYPOS instead of compiling a ~60k-way alternation. Curly apostrophes
# count as apostrophes so "wasn’t" is one token, not the typo "wasn".
_TOKEN_RE = re.compile(r"(?<![\w-])[A-Za-z](?:[A-Za-z'’]*[A-Za-z])?(?![\w-])")

_URL_RE = re.compile(r"(?:https?|ftp)://[^\s\[\]<>\"]+")
_QUOTE_TEMPLATES = {"quote", "cquote", "quotation", "quote box", "blockquote"}


def _match_case(source: str, correction: str) -> str:
    if source.isupper() and len(source) > 1:
        return correction.upper()
    if source[0].isupper():
        return correction[0].upper() + correction[1:]
    return correction


def _excluded_spans(ctx) -> list[tuple[int, int]]:
    """Spans that TY001 must not fire in: wikilink targets, URLs, template
    and parameter names, quote templates/blockquotes.

    Offsets are recovered by walking the mwparserfromhell tree in order;
    str(node) round-trips exactly, so node lengths give exact positions.
    """
    spans = [m.span() for m in _URL_RE.finditer(ctx.text)]

    def walk(code, pos):
        for node in code.nodes:
            visit(node, pos)
            pos += len(str(node))

    def visit(node, pos):
        if isinstance(node, nodes.Template):
            name = str(node.name)
            if name.strip().lower() in _QUOTE_TEMPLATES:
                spans.append((pos, pos + len(str(node))))
                return
            cur = pos + 2
            spans.append((cur, cur + len(name)))
            cur += len(name)
            for param in node.params:
                cur += 1  # "|"
                if param.showkey:
                    pname = str(param.name)
                    spans.append((cur, cur + len(pname) + 1))  # name and "="
                    cur += len(pname) + 1
                walk(param.value, cur)
                cur += len(str(param.value))
        elif isinstance(node, nodes.Wikilink):
            title = str(node.title)
            spans.append((pos + 2, pos + 2 + len(title)))
            if node.text is not None:
                walk(node.text, pos + 2 + len(title) + 1)
        elif isinstance(node, nodes.ExternalLink):
            url = str(node.url)
            start = pos + (1 if node.brackets else 0)
            spans.append((start, start + len(url)))
            if node.title is not None:
                walk(node.title, pos + len(str(node)) - 1 - len(str(node.title)))
        elif isinstance(node, nodes.Tag):
            s = str(node)
            if str(node.tag).lower() == "blockquote":
                spans.append((pos, pos + len(s)))
            elif node.contents is not None:
                idx = s.find(str(node.contents))
                if idx != -1:
                    walk(node.contents, pos + idx)
        elif isinstance(node, nodes.Heading):
            walk(node.title, pos + node.level)

    walk(ctx.wikicode, 0)
    return spans


@rule("TY001", "known misspelling")
def ty001(ctx):
    """Flag words from the curated misspelling list in civlint/data/typos.txt.

    The list is tab-separated, one entry per line:

        misspelling<TAB>correction               unambiguous, fixable
        misspelling<TAB>correction1|correction2  ambiguous, report-only

    Curation is by deleting lines from the file: words that are correct on
    this wiki (player names, gamer terms like "memer", foreign-language
    text, entries whose fix could destroy a legitimate word) have been
    removed. See the file header before regenerating it from upstream.

    Matching is case-insensitive on standalone words (no letter, digit,
    underscore, or hyphen adjacent) and the fix preserves the original
    casing. Tokens that are a single letter, entirely uppercase (acronyms:
    "ABL" is never a typo of "able" here), or capitalized after the first
    letter (identifier-style names) never fire. Fixes are UNSAFE: quoted
    chat logs and usernames make even certain typos risky on this wiki.
    Never fires inside wikilink targets, URLs, template or parameter
    names, quote templates, or <blockquote>s.
    """
    excluded = None  # computed lazily: most pages have no hits
    for m in _TOKEN_RE.finditer(ctx.text):
        token = m.group(0)
        # single letters, acronyms (2+ letters all-caps), and tokens with
        # internal capitals ("TeH", "McFoo") are never prose typos.
        if len(token) == 1 or any(c.isupper() for c in token[1:]):
            continue
        corrections = _TYPOS.get(token.replace("’", "'").lower())
        if corrections is None:
            continue
        if ctx.is_shielded(*m.span()):
            continue
        if excluded is None:
            excluded = _excluded_spans(ctx)
        if overlaps(excluded, *m.span()):
            continue
        word = m.group(0)
        if len(corrections) == 1:
            correction = _match_case(word, corrections[0])
            yield Finding(
                code="TY001",
                message=f'"{word}" is a misspelling of "{correction}"',
                start=m.start(),
                end=m.end(),
                fix=Fix(
                    edits=[Edit(m.start(), m.end(), correction)],
                    applicability=Applicability.UNSAFE,
                ),
            )
        else:
            options = " or ".join(
                f'"{_match_case(word, c)}"' for c in corrections
            )
            yield Finding(
                code="TY001",
                message=f'"{word}" is a misspelling of {options}',
                start=m.start(),
                end=m.end(),
            )
