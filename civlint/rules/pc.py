"""PC rules: ports of pywikibot's cosmetic_changes methods.

Each rule reimplements one CosmeticChangesToolkit method for an English,
article-namespace wiki; site- and language-specific branches are dropped.
"""

import re
from html.entities import name2codepoint

from civlint.types import Applicability, Edit, Finding, Fix, rule
from civlint.wikitext import (
    CATEGORY_RE,
    COMMENT_RE,
    HEADING_RE,
    REDIRECT_RE,
    overlaps,
    remove_span_and_line,
)


def _first_lower(s: str) -> str:
    return s[:1].lower() + s[1:]


def _pc001_rebuild(text: str, cat_spans: list[tuple[int, int]]) -> str:
    cats = [text[s:e] for s, e in cat_spans]
    # remove each category link; drop its line entirely if nothing else is on it
    for s, e in reversed(cat_spans):
        ds, de = remove_span_and_line(text, s, e)
        text = text[:ds] + text[de:]
    body = text.rstrip()
    block = "\n".join(cats) + "\n"
    return body + "\n\n" + block if body else block


@rule("PC001", "category links not grouped at the bottom of the page")
def pc001(ctx):
    """Ports cosmetic_changes.standardizePageFooter (category part).

    Fires on a category link followed by non-category, non-whitespace
    content. The fix (attached to the first finding only; the others are
    report-only) moves all top-level category links to the end of the page,
    in order, one per line, after a single blank line.
    """
    cats = [
        m
        for m in ctx.finditer(CATEGORY_RE)
        if not overlaps(ctx.template_spans, *m.span())
    ]
    cat_spans = [m.span() for m in cats]
    fixed = False
    for i, m in enumerate(cats):
        # content after this link, with later category links blanked out
        parts = []
        pos = m.end()
        for s, e in cat_spans[i + 1 :]:
            parts.append(ctx.text[pos:s])
            pos = e
        parts.append(ctx.text[pos:])
        if not "".join(parts).strip():
            continue
        fix = None
        if not fixed:
            fixed = True
            fix = Fix(
                edits=[Edit(0, len(ctx.text), _pc001_rebuild(ctx.text, cat_spans))],
                applicability=Applicability.UNSAFE,
            )
        yield Finding(
            code="PC001",
            message="category link is not at the bottom of the page",
            start=m.start(),
            end=m.end(),
            fix=fix,
        )


_PIPED_LINK_RE = re.compile(r"\[\[(?P<title>[^\]\|\n#:]+)\|(?P<label>[^\]\|\n]+)\]\]")
# linktrail for an English wiki: characters that may follow ]] as part of
# the rendered link word


@rule("PC002", "piped link where the pipe is unnecessary")
def pc002(ctx):
    """Ports cosmetic_changes.cleanUpLinks (pipe simplification part).

    [[Foo|foo]] -> [[foo]] when target and label differ only in
    first-letter case. Links with fragments or namespace prefixes are
    skipped. Unlike upstream, [[Foo|Foos]] is NOT collapsed to [[Foo]]s:
    the linktrail form renders the same but reads worse in the source.
    """
    for m in ctx.finditer(_PIPED_LINK_RE):
        title, label = m["title"], m["label"]
        if _first_lower(title) != _first_lower(label):
            continue
        new = f"[[{label}]]"
        yield Finding(
            code="PC002",
            message=f"piped link can be simplified to {new}",
            start=m.start(),
            end=m.end(),
            fix=Fix(
                edits=[Edit(m.start(), m.end(), new)],
                applicability=Applicability.SAFE,
            ),
        )


_ENTITY_RE = re.compile(
    r"&(?:#(?P<dec>\d+)|#[xX](?P<hex>[0-9A-Fa-f]+)|(?P<name>[A-Za-z][A-Za-z0-9]*));"
)
# upstream resolveHtmlEntities ignore list: codepoints whose entities either
# affect wikitext parsing or are kept intentionally by editors
_ENTITY_IGNORE = {
    38,  # & (&amp;)
    39,  # ' (&#39;) - would form ''/''' markup
    60,  # < (&lt;)
    62,  # > (&gt;)
    91,  # [ - used intentionally inside links
    93,  # ] - used intentionally inside links
    124,  # | - used intentionally in templates/tables
    160,  # non-breaking space (&nbsp;)
    173,  # soft hyphen (&shy;)
    8206,  # left-to-right mark
    8207,  # right-to-left mark
}


@rule("PC003", "HTML entity that can be a literal character")
def pc003(ctx):
    """Ports cosmetic_changes.resolveHtmlEntities.

    Replaces numeric and named HTML entities with the character itself,
    except the upstream ignore list (amp, lt, gt, apostrophe, nbsp, shy,
    brackets, pipe, directional marks).
    """
    for m in ctx.finditer(_ENTITY_RE):
        if m["dec"]:
            cp = int(m["dec"])
        elif m["hex"]:
            cp = int(m["hex"], 16)
        else:
            cp = name2codepoint.get(m["name"])
            if cp is None:
                continue
        if cp in _ENTITY_IGNORE:
            continue
        if not 32 <= cp <= 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
            continue
        yield Finding(
            code="PC003",
            message=f"replace {m.group()} with {chr(cp)!r}",
            start=m.start(),
            end=m.end(),
            fix=Fix(
                edits=[Edit(m.start(), m.end(), chr(cp))],
                applicability=Applicability.SAFE,
            ),
        )


@rule("PC004", "empty section")
def pc004(ctx):
    """Ports cosmetic_changes.removeEmptySections.

    A heading whose own body (up to the next heading or EOF) is only
    whitespace and comments is removed together with that body. Kept if
    the next heading is deeper (the section has subsections), or if the
    body contains anything else (categories, templates, ...).
    """
    headings = [
        (m.start(), m.end(), len(m["eq"]))
        for m in ctx.finditer(HEADING_RE)
        if not overlaps(ctx.template_spans, m.start(), m.end())
    ]
    for i, (start, end, level) in enumerate(headings):
        if i + 1 < len(headings):
            next_start, next_level = headings[i + 1][0], headings[i + 1][2]
        else:
            next_start, next_level = len(ctx.text), 0
        if COMMENT_RE.sub("", ctx.text[end:next_start]).strip():
            continue
        if next_level > level:
            continue  # has subsections; they are judged on their own
        yield Finding(
            code="PC004",
            message="section is empty",
            start=start,
            end=end,
            fix=Fix(
                edits=[Edit(start, next_start, "")],
                applicability=Applicability.UNSAFE,
            ),
        )


_TRAILING_WS_RE = re.compile(r"(?m)[ \t]+$")


@rule("PC005", "trailing whitespace at end of line")
def pc005(ctx):
    """Ports cosmetic_changes.removeUselessSpaces (trailing part).

    Strips spaces/tabs at end of line, except on pre-formatted lines
    (leading space), inside tables, and inside templates.
    """
    skip = []
    depth = 0
    pos = 0
    for line in ctx.text.splitlines(keepends=True):
        in_table = depth > 0 or line.startswith("{|")
        if line.startswith("{|"):
            depth += 1
        elif line.startswith("|}") and depth:
            depth -= 1
        if in_table or line.startswith(" "):
            skip.append((pos, pos + len(line)))
        pos += len(line)
    for m in ctx.finditer(_TRAILING_WS_RE):
        if overlaps(skip, *m.span()) or overlaps(ctx.template_spans, *m.span()):
            continue
        yield Finding(
            code="PC005",
            message="trailing whitespace",
            start=m.start(),
            end=m.end(),
            fix=Fix(
                edits=[Edit(m.start(), m.end(), "")],
                applicability=Applicability.SAFE,
            ),
        )


_HEADER_SPACING_RE = re.compile(
    r"(?m)^(={1,6})[ \t]*(?P<title>.*[^\s=])[ \t]*\1[ \t]*\r?\n"
)


@rule("PC006", "heading spacing is not `== Title ==`")
def pc006(ctx):
    """Ports cosmetic_changes.cleanUpSectionHeaders.

    Normalizes headings to a single space between the = runs and the
    title, and strips whitespace after the closing =.
    """
    for m in ctx.finditer(_HEADER_SPACING_RE):
        new = f"{m[1]} {m['title']} {m[1]}\n"
        if new == m.group():
            continue
        yield Finding(
            code="PC006",
            message="heading spacing should be `== Title ==`",
            start=m.start(),
            end=m.end(),
            fix=Fix(
                edits=[Edit(m.start(), m.end(), new)],
                applicability=Applicability.SAFE,
            ),
        )


_LIST_RE = re.compile(r"(?m)^(?P<bullet>[:;]*(\*+|#+)[:;\*#]*)(?P<char>[^\s\*#:;].*?)")


@rule("PC007", "list item marker not followed by a space")
def pc007(ctx):
    """Ports cosmetic_changes.putSpacesInLists.

    Inserts a space after */# list markers (upstream requires the marker
    run to contain a * or #, so plain ;/: lines are untouched). Skips
    #REDIRECT lines and lines inside templates.
    """
    for m in ctx.finditer(_LIST_RE):
        if overlaps(ctx.template_spans, *m.span()) or REDIRECT_RE.match(
            ctx.text, m.start()
        ):
            continue
        yield Finding(
            code="PC007",
            message="missing space after list marker",
            start=m.start(),
            end=m.end("bullet"),
            fix=Fix(
                edits=[Edit(m.end("bullet"), m.end("bullet"), " ")],
                applicability=Applicability.SAFE,
            ),
        )


_EXT_DOUBLE_RE = re.compile(r"\[\[(?P<url>https?://[^\]]+?)\]\]?")
_EXT_PIPE_RE = re.compile(
    r"\[(?P<url>https?://[^\|\] \r\n]+?) +\| *(?P<label>[^\|\]]+?)\]"
)
_EXT_PIPE_EXTENSION_RE = re.compile(
    r"\[(?P<url>https?://[^\|\] ]+?(\.pdf|\.html?|\.php|\.aspx?|\.jsp)) *"
    r"\| *(?P<label>[^\|\]]+?)\]"
)


@rule("PC008", "malformed external link syntax")
def pc008(ctx):
    """Ports cosmetic_changes.fixSyntaxSave (generic external-link part).

    [[http://...]] -> [http://...]; [url |label] with whitespace before
    the pipe -> [url label]; likewise a pipe directly after a URL ending
    in a known file extension. The upstream conversion of self-wiki URLs
    to wikilinks needs live site URLs and is not ported.
    """

    def ext_double(m):
        # a pipe inside [[https://...|label]] is the wikilink separator;
        # kept verbatim it would be percent-encoded into the URL
        url, _, label = m["url"].partition("|")
        label = label.strip()
        return f"[{url.strip()} {label}]" if label else f"[{url.strip()}]"

    cases = [
        (_EXT_DOUBLE_RE, ext_double),
        (_EXT_PIPE_RE, lambda m: f"[{m['url']} {m['label']}]"),
        (_EXT_PIPE_EXTENSION_RE, lambda m: f"[{m['url']} {m['label']}]"),
    ]
    for pattern, repl in cases:
        for m in ctx.finditer(pattern):
            yield Finding(
                code="PC008",
                message="malformed external link",
                start=m.start(),
                end=m.end(),
                fix=Fix(
                    edits=[Edit(m.start(), m.end(), repl(m))],
                    applicability=Applicability.SAFE,
                ),
            )


_BOLD_RE = re.compile(r"<(b|strong)>(.*?)</\1>", re.IGNORECASE)
_ITALIC_RE = re.compile(r"<(i|em)>(.*?)</\1>", re.IGNORECASE)
_HR_RE = re.compile(r"(?<=\n)<hr[ /]*>(?=\r?\n)", re.IGNORECASE)
_HR_ATTR_RE = re.compile(r"<hr ([^>/]+?)>", re.IGNORECASE)
_HTML_HEADER_RE = re.compile(
    r"(?<=[\r\n]) *<h([1-7])> *([^<]+?) *</h\1> *(?=[\r\n])", re.IGNORECASE
)


@rule("PC009", "HTML formatting that has wikitext markup")
def pc009(ctx):
    """Ports cosmetic_changes.fixHtml.

    <b>/<strong> -> ''', <i>/<em> -> '', a bare <hr> on its own line ->
    ----, <hr attrs> -> XHTML <hr attrs />, and <hN>Title</hN> on its own
    line -> an == heading. Only attribute-free tag pairs are converted.
    """
    cases = [
        (_BOLD_RE, lambda m: f"'''{m[2]}'''"),
        (_ITALIC_RE, lambda m: f"''{m[2]}''"),
        (_HR_RE, lambda m: "----"),
        (_HR_ATTR_RE, lambda m: f"<hr {m[1]} />"),
        (_HTML_HEADER_RE, lambda m: "{0} {1} {0}".format("=" * int(m[1]), m[2])),
    ]
    for pattern, repl in cases:
        for m in ctx.finditer(pattern):
            yield Finding(
                code="PC009",
                message=f"replace HTML with {repl(m)!r}",
                start=m.start(),
                end=m.end(),
                fix=Fix(
                    edits=[Edit(m.start(), m.end(), repl(m))],
                    applicability=Applicability.SAFE,
                ),
            )


_REF_NAME_RE = re.compile(r'<ref +name(= *| *=)"', re.IGNORECASE)
_REF_EMPTY_RE = re.compile(r"<ref\s*/>|<ref *>\s*</ref>", re.IGNORECASE)
_REF_SELFCLOSE_RE = re.compile(r"<ref\s+([^>]+?)\s*>\s*</ref>", re.IGNORECASE)


@rule("PC010", "reference tag cleanup")
def pc010(ctx):
    """Ports cosmetic_changes.fixReferences.

    Normalizes `<ref name=...` spacing, removes empty <ref></ref> and
    bare <ref/> tags, and self-closes empty refs with attributes.
    """
    for m in ctx.finditer(_REF_NAME_RE):
        if m.group() == '<ref name="':
            continue
        yield Finding(
            code="PC010",
            message="normalize spacing in <ref name=...>",
            start=m.start(),
            end=m.end(),
            fix=Fix(
                edits=[Edit(m.start(), m.end(), '<ref name="')],
                applicability=Applicability.SAFE,
            ),
        )
    for m in ctx.finditer(_REF_EMPTY_RE):
        yield Finding(
            code="PC010",
            message="remove empty <ref> tag",
            start=m.start(),
            end=m.end(),
            fix=Fix(
                edits=[Edit(m.start(), m.end(), "")],
                applicability=Applicability.SAFE,
            ),
        )
    for m in ctx.finditer(_REF_SELFCLOSE_RE):
        yield Finding(
            code="PC010",
            message="self-close empty <ref> tag",
            start=m.start(),
            end=m.end(),
            fix=Fix(
                edits=[Edit(m.start(), m.end(), f"<ref {m[1]}/>")],
                applicability=Applicability.SAFE,
            ),
        )


_PRETTYTABLE_RE = re.compile(r'(class="[^"]*)prettytable([^"]*")')


@rule("PC011", "deprecated prettytable class")
def pc011(ctx):
    """Ports cosmetic_changes.fixStyle: class="prettytable" ->
    class="wikitable"."""
    for m in ctx.finditer(_PRETTYTABLE_RE):
        yield Finding(
            code="PC011",
            message='replace class "prettytable" with "wikitable"',
            start=m.start(),
            end=m.end(),
            fix=Fix(
                edits=[Edit(m.start(), m.end(), f"{m[1]}wikitable{m[2]}")],
                applicability=Applicability.SAFE,
            ),
        )
