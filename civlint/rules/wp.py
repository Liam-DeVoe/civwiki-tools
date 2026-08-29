"""WP rules: ports of WikiProject Check Wikipedia checks, keeping the
upstream check numbers (upstream check 2 -> WP002)."""

import re

from civlint.types import Applicability, Edit, Finding, Fix, rule
from civlint.wikitext import (
    CATEGORY_RE,
    FILE_PREFIX_RE,
    HEADING_RE,
    remove_span_and_line,
    split_top_level,
)

# Any <br>-shaped tag, valid or not.
BR = r"<\s*/?\s*br(?![a-zA-Z])[^<>\n]*>"
_BR_END = re.compile(rf"({BR})\s*\Z", re.I)


def _in_ext_link(text, pos):
    """True if pos is preceded on its line by an unclosed [proto:// opener."""
    line_start = text.rfind("\n", 0, pos) + 1
    return bool(
        re.search(r"\[[a-zA-Z][a-zA-Z0-9+.\-]*://[^\]\n]*$", text[line_start:pos])
    )


def _link_balance(ctx):
    """Unmatched [[ and ]] positions, resetting at each blank line."""
    opens, closes, stack = [], [], []
    for m in ctx.finditer(r"\[\[|\]\]|\n[ \t]*\n"):
        tok = m.group()
        if tok == "[[":
            stack.append(m.start())
        elif tok == "]]":
            if stack:
                stack.pop()
            else:
                closes.append(m.start())
        else:
            opens.extend(stack)
            stack.clear()
    opens.extend(stack)
    return sorted(opens), closes


def _brace_balance(ctx):
    """Unmatched {{ and }} positions over the whole page."""
    closes, stack = [], []
    for m in ctx.finditer(r"\{\{|\}\}"):
        if m.group() == "{{":
            stack.append(m.start())
        elif stack:
            stack.pop()
        else:
            closes.append(m.start())
    return stack, closes


_BR_TAG = re.compile(r"<\s*(/?)\s*br(?![a-zA-Z])([^<>\n]*)>", re.I)
_BR_OK = {"<br>", "<br/>", "<br />"}
_BR_JUNK = re.compile(r"[\s/\\.]*")
_BR_CLEAR = re.compile(r"""[\s/\\.]*clear\s*=\s*["']?[\w ]*["']?[\s/\\.]*""", re.I)


@rule("WP002", "malformed <br>")
def cw002(ctx):
    """A <br> written as </br>, <br.>, <br >, <BR>, <br clear=all>, etc.
    Normalized to plain <br>. Valid <br>, <br/> and <br /> are left alone,
    as are br tags with attributes other than the obsolete clear."""
    for m in ctx.finditer(_BR_TAG):
        if m.group(0) in _BR_OK:
            continue
        attrs = m.group(2)
        if not (_BR_JUNK.fullmatch(attrs) or _BR_CLEAR.fullmatch(attrs)):
            continue
        yield Finding(
            code="WP002",
            message=f"malformed <br>: {m.group(0)}",
            start=m.start(),
            end=m.end(),
            fix=Fix([Edit(m.start(), m.end(), "<br>")], Applicability.SAFE),
        )


_H_OPEN = re.compile(r"^(={2,6})([^=\n][^\n]*?)[ \t]*$", re.M)


@rule("WP008", "heading missing closing = run")
def cw008(ctx):
    """A line starting with 2-6 = signs and title text but no closing =
    run, e.g. `== Title`. Lines inside templates or tables are skipped,
    since = there is usually parameter syntax, not a heading."""
    masked = ctx.mask_spans
    for m in ctx.finditer(_H_OPEN):
        title = m.group(2)
        if not title.strip() or title.rstrip().endswith("="):
            continue
        if any(s <= m.start() < e for s, e in masked):
            continue
        yield Finding(
            code="WP008",
            message="heading has no closing = run",
            start=m.start(),
            end=m.end(),
        )


@rule("WP009", "multiple categories on one line")
def cw009(ctx):
    """More than one [[Category:...]] link on a single line. Each category
    is moved onto its own line."""
    last = None  # (line start, end of previous category on that line)
    for m in ctx.finditer(CATEGORY_RE):
        line_start = ctx.text.rfind("\n", 0, m.start()) + 1
        if last and last[0] == line_start:
            gap = ctx.text[last[1] : m.start()]
            repl = gap.rstrip(" \t") + "\n"
            yield Finding(
                code="WP009",
                message="multiple category links on one line",
                start=m.start(),
                end=m.end(),
                fix=Fix([Edit(last[1], m.start(), repl)], Applicability.SAFE),
            )
        last = (line_start, m.end())


@rule("WP010", "unmatched [[")
def cw010(ctx):
    """A [[ with no matching ]] before the next blank line. Openers inside
    an external link's brackets are skipped."""
    opens, _ = _link_balance(ctx)
    for pos in opens:
        if _in_ext_link(ctx.text, pos):
            continue
        yield Finding(
            code="WP010", message="unmatched [[", start=pos, end=pos + 2
        )


_INVIS = {
    "­": "U+00AD soft hyphen",
    "​": "U+200B zero-width space",
    "‎": "U+200E left-to-right mark",
    "‏": "U+200F right-to-left mark",
    "﻿": "U+FEFF byte order mark",
}


@rule("WP016", "invisible unicode character")
def cw016(ctx):
    """Invisible or control characters (BOM, zero-width space, directional
    marks, soft hyphen). Removed."""
    for m in ctx.finditer("[" + "".join(_INVIS) + "]"):
        yield Finding(
            code="WP016",
            message=f"invisible character {_INVIS[m.group()]}",
            start=m.start(),
            end=m.end(),
            fix=Fix([Edit(m.start(), m.end(), "")], Applicability.SAFE),
        )


@rule("WP017", "duplicate category")
def cw017(ctx):
    """The same category appears more than once (case- and
    underscore-insensitive, ignoring sort keys). Later duplicates are
    removed, along with their line if nothing else is on it."""
    seen = set()
    for m in ctx.finditer(CATEGORY_RE):
        key = re.sub(r"[\s_]+", " ", m["name"]).strip().lower()
        if key not in seen:
            seen.add(key)
            continue
        s, e = m.span()
        edit = Edit(*remove_span_and_line(ctx.text, s, e), "")
        yield Finding(
            code="WP017",
            message=f"duplicate category: {m['name']}",
            start=s,
            end=e,
            fix=Fix([edit], Applicability.SAFE),
        )


@rule("WP019", "level-1 heading")
def cw019(ctx):
    """A = Title = heading. Articles should start at level 2 (== Title ==);
    level 1 is reserved for the page title."""
    for m in ctx.finditer(HEADING_RE):
        if len(m["eq"]) == 1:
            yield Finding(
                code="WP019",
                message="level-1 heading",
                start=m.start(),
                end=m.end(),
            )


@rule("WP022", "category link with stray spacing or casing")
def cw022(ctx):
    """A category link like [[ category : Foo ]] with extra whitespace or a
    non-canonical namespace spelling. Rewritten as [[Category:Foo]],
    preserving any sort key."""
    for m in ctx.finditer(CATEGORY_RE):
        sort = m["sortkey"]
        canonical = f"[[Category:{m['name']}" + (
            f"|{sort}]]" if sort is not None else "]]"
        )
        if m.group(0) == canonical:
            continue
        yield Finding(
            code="WP022",
            message=f"category link should be {canonical}",
            start=m.start(),
            end=m.end(),
            fix=Fix([Edit(m.start(), m.end(), canonical)], Applicability.SAFE),
        )


@rule("WP025", "heading hierarchy skips a level")
def cw025(ctx):
    """A heading more than one level deeper than the heading before it,
    e.g. ==== directly after ==."""
    prev = None
    for m in ctx.finditer(HEADING_RE):
        level = len(m["eq"])
        if prev is not None and level > prev + 1:
            yield Finding(
                code="WP025",
                message=f"heading level jumps from {prev} to {level}",
                start=m.start(),
                end=m.end(),
            )
        prev = level


@rule("WP043", "unmatched {{")
def cw043(ctx):
    """A {{ with no matching }} anywhere on the page."""
    opens, _ = _brace_balance(ctx)
    for pos in opens:
        yield Finding(
            code="WP043", message="unmatched {{", start=pos, end=pos + 2
        )


@rule("WP044", "bold markup in heading")
def cw044(ctx):
    """A heading title containing ''' bold markers. Headings are already
    bold; the markers are stripped."""
    for m in ctx.finditer(HEADING_RE):
        title = m["title"]
        if "'''" not in title:
            continue
        base = m.start("title")
        edits = [
            Edit(base + q.start(), base + q.end(), "")
            for q in re.finditer("'''", title)
        ]
        yield Finding(
            code="WP044",
            message="bold markup in heading",
            start=m.start(),
            end=m.end(),
            fix=Fix(edits, Applicability.SAFE),
        )


@rule("WP046", "unmatched ]]")
def cw046(ctx):
    """A ]] with no matching [[ before it in the same paragraph."""
    _, closes = _link_balance(ctx)
    for pos in closes:
        if _in_ext_link(ctx.text, pos):
            continue
        yield Finding(
            code="WP046", message="unmatched ]]", start=pos, end=pos + 2
        )


@rule("WP047", "unmatched }}")
def cw047(ctx):
    """A }} with no matching {{ before it on the page."""
    _, closes = _brace_balance(ctx)
    for pos in closes:
        yield Finding(
            code="WP047", message="unmatched }}", start=pos, end=pos + 2
        )


_LIST_BR = re.compile(rf"^[*#:;][^\n]*?([ \t]*(?:{BR}))[ \t]*$", re.I | re.M)


@rule("WP054", "list item ends with <br>")
def cw054(ctx):
    """A list item ending with a <br> before the newline. The break is
    redundant (the list already breaks the line) and is removed."""
    for m in ctx.finditer(_LIST_BR):
        yield Finding(
            code="WP054",
            message="list item ends with <br>",
            start=m.start(1),
            end=m.end(1),
            fix=Fix([Edit(m.start(1), m.end(), "")], Applicability.SAFE),
        )


@rule("WP057", "heading ends with a colon")
def cw057(ctx):
    """A heading title ending with a colon, e.g. == History: ==. The colon
    is removed."""
    for m in ctx.finditer(HEADING_RE):
        stripped = m["title"].rstrip()
        if not stripped.endswith(":"):
            continue
        pos = m.start("title") + len(stripped) - 1
        yield Finding(
            code="WP057",
            message="heading ends with a colon",
            start=m.start(),
            end=m.end(),
            fix=Fix([Edit(pos, pos + 1, "")], Applicability.SAFE),
        )


@rule("WP059", "template parameter ends with <br>")
def cw059(ctx):
    """A template parameter value ending with a <br>. The break is usually
    left over from an old layout and is removed. Unsafe because a trailing
    break can be intentional inside some templates."""
    for start, _end, tmpl in ctx.node_spans(ctx.wikicode.filter_templates()):
        # str(tmpl) is "{{" + name + ("|" + param)* + "}}", so param offsets
        # can be computed cumulatively. A raw.find(param) search would
        # mislocate a param whose text repeats earlier in the template.
        cursor = start + 2 + len(str(tmpl.name))
        for param in tmpl.params:
            pstr = str(param)
            pstart = cursor + 1
            cursor = pstart + len(pstr)
            value = str(param.value)
            bm = _BR_END.search(value)
            if not bm:
                continue
            voff = pstart + len(pstr) - len(value)
            s, e = voff + bm.start(1), voff + bm.end(1)
            if ctx.is_shielded(s, e) or ctx.text[s:e] != bm.group(1):
                continue
            yield Finding(
                code="WP059",
                message=f"template parameter '{str(param.name).strip()}' "
                "ends with <br>",
                start=s,
                end=e,
                fix=Fix([Edit(s, e, "")], Applicability.UNSAFE),
            )


@rule("WP065", "file caption ends with <br>")
def cw065(ctx):
    """A [[File:...]] caption (the last unnamed parameter) ending with a
    <br>. The break is removed."""
    for start, _end, link in ctx.node_spans(ctx.wikicode.filter_wikilinks()):
        title = str(link.title)
        if link.text is None or not FILE_PREFIX_RE.match(title):
            continue
        inner = str(link.text)
        caption = next(
            (
                (ps, pe)
                for ps, pe in reversed(list(split_top_level(inner)))
                if not re.match(r"\s*[a-zA-Z]+\s*=", inner[ps:pe])
            ),
            None,
        )
        if caption is None:
            continue
        ps, pe = caption
        bm = _BR_END.search(inner[ps:pe])
        if not bm:
            continue
        coff = start + 2 + len(title) + 1 + ps
        s, e = coff + bm.start(1), coff + bm.end(1)
        if ctx.is_shielded(s, e) or ctx.text[s:e] != bm.group(1):
            continue
        yield Finding(
            code="WP065",
            message="file caption ends with <br>",
            start=s,
            end=e,
            fix=Fix([Edit(s, e, "")], Applicability.SAFE),
        )


@rule("WP074", "wikilink with no target")
def cw074(ctx):
    """A link with an empty target, like [[|text]]."""
    for m in ctx.finditer(r"\[\[[ \t]*\|"):
        yield Finding(
            code="WP074",
            message="wikilink with no target",
            start=m.start(),
            end=m.end(),
        )


_PCT_LINK = re.compile(r"\[\[([^\[\]\|\n]*%20[^\[\]\|\n]*)(?=\||\]\])")


@rule("WP076", "%20 in wikilink target")
def cw076(ctx):
    """An internal link whose target contains %20 instead of a space."""
    for m in ctx.finditer(_PCT_LINK):
        base = m.start(1)
        edits = [
            Edit(base + q.start(), base + q.end(), " ")
            for q in re.finditer("%20", m.group(1))
        ]
        yield Finding(
            code="WP076",
            message="%20 in wikilink target",
            start=m.start(),
            end=m.end(),
            fix=Fix(edits, Applicability.SAFE),
        )


_EXT_NL = re.compile(r"\[(?:https?|ftp)://[^\]\n]*\n[^\]\n]*\]", re.I)


@rule("WP080", "external link with line break")
def cw080(ctx):
    """A bracketed external link with a raw newline before the closing ],
    which breaks the link."""
    for m in ctx.finditer(_EXT_NL):
        yield Finding(
            code="WP080",
            message="external link contains a line break",
            start=m.start(),
            end=m.end(),
        )


_DEFAULTSORT = re.compile(r"\{\{\s*DEFAULTSORT\s*:(\s+)", re.I)


@rule("WP088", "DEFAULTSORT with leading whitespace")
def cw088(ctx):
    """{{DEFAULTSORT: X}} with whitespace before the sort key, which sorts
    the page before all letters. The whitespace is removed."""
    for m in ctx.finditer(_DEFAULTSORT):
        yield Finding(
            code="WP088",
            message="DEFAULTSORT key has leading whitespace",
            start=m.start(),
            end=m.end(),
            fix=Fix([Edit(m.start(1), m.end(1), "")], Applicability.SAFE),
        )


@rule("WP092", "duplicate heading")
def cw092(ctx):
    """Two headings with the same rendered title text, which produces
    duplicate anchors."""
    seen = set()
    for m in ctx.finditer(HEADING_RE):
        key = re.sub(
            r"\s+", " ", m["title"].replace("'''", "").replace("''", "")
        ).strip()
        if key in seen:
            yield Finding(
                code="WP092",
                message=f"duplicate heading: {key}",
                start=m.start(),
                end=m.end(),
            )
        else:
            seen.add(key)


@rule("WP113", "line break inside wikilink")
def cw113(ctx):
    """A newline inside a wikilink's target or label, like [[foo\\nbar]].
    Replaced with a space. Unsafe because the intended text may have been
    two separate things."""
    for m in ctx.finditer(r"\[\[[^\[\]]*\]\]"):
        if "\n" not in m.group(0):
            continue
        edits = [
            Edit(m.start() + q.start(), m.start() + q.end(), " ")
            for q in re.finditer("\n", m.group(0))
        ]
        yield Finding(
            code="WP113",
            message="line break inside wikilink",
            start=m.start(),
            end=m.end(),
            fix=Fix(edits, Applicability.UNSAFE),
        )


@rule("WP538", "whitespace after heading")
def cw538(ctx):
    """Trailing spaces or tabs after the closing = run of a heading."""
    for m in ctx.finditer(HEADING_RE):
        if not m["trail"]:
            continue
        yield Finding(
            code="WP538",
            message="whitespace after heading",
            start=m.start("trail"),
            end=m.end("trail"),
            fix=Fix(
                [Edit(m.start("trail"), m.end("trail"), "")], Applicability.SAFE
            ),
        )
