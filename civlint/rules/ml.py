"""ml rules. See civlint/README.md for conventions."""

import re

from civlint.types import Applicability, Edit, Finding, Fix, rule
from civlint.wikitext import FILE_PREFIX_RE, split_top_level

_OBSOLETE_TAGS = ("font", "center", "tt", "strike", "big")
_OBSOLETE_RE = re.compile(
    rf"<({'|'.join(_OBSOLETE_TAGS)})\b([^<>]*)>", re.IGNORECASE
)
# a font tag whose attributes are exactly one color=... assignment
_FONT_COLOR_RE = re.compile(
    r"""\s*color\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>]+))\s*""",
    re.IGNORECASE,
)
_SIMPLE_RENAMES = {"tt": "code", "strike": "s"}


def _matching_close(ctx, tag: str, pos: int) -> re.Match | None:
    """The close tag balancing an open <tag> at `pos`, or None."""
    pat = re.compile(rf"<(/?){tag}\b[^<>]*>", re.IGNORECASE)
    depth = 1
    for m in pat.finditer(ctx.text, pos):
        if ctx.is_shielded(*m.span()) or re.search(r"/\s*>$", m.group(0)):
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m
    return None


@rule("ML001", "obsolete HTML tag")
def ml001(ctx):
    """Obsolete HTML tag: <font>, <center>, <tt>, <strike>, <big>.

    <tt> and <strike> pairs are renamed to <code> and <s> (safe). A
    <font color=...> with no other attributes becomes a color: span, a
    bare <center> pair becomes a text-align:center div, and a bare <big>
    pair becomes a font-size:larger span (all unsafe). Anything else —
    font size/face, unmatched or self-closed tags — is reported without
    a fix.
    """
    for m in ctx.finditer(_OBSOLETE_RE):
        tag = m.group(1).lower()
        attrs = m.group(2)
        fix = None
        if not attrs.rstrip().endswith("/"):  # self-closed: report only
            close = _matching_close(ctx, tag, m.end())
            simple_close = close is not None and re.fullmatch(
                rf"</{tag}\s*>", close.group(0), re.IGNORECASE
            )
            if tag in _SIMPLE_RENAMES and not attrs.strip() and simple_close:
                new = _SIMPLE_RENAMES[tag]
                fix = Fix(
                    edits=[
                        Edit(m.start(), m.end(), f"<{new}>"),
                        Edit(close.start(), close.end(), f"</{new}>"),
                    ],
                    applicability=Applicability.SAFE,
                )
            elif tag == "center" and not attrs.strip() and simple_close:
                fix = Fix(
                    edits=[
                        Edit(
                            m.start(), m.end(),
                            '<div style="text-align:center;">',
                        ),
                        Edit(close.start(), close.end(), "</div>"),
                    ],
                    applicability=Applicability.UNSAFE,
                )
            elif tag == "big" and not attrs.strip() and simple_close:
                fix = Fix(
                    edits=[
                        Edit(
                            m.start(), m.end(),
                            '<span style="font-size:larger;">',
                        ),
                        Edit(close.start(), close.end(), "</span>"),
                    ],
                    applicability=Applicability.UNSAFE,
                )
            elif tag == "font" and simple_close:
                cm = _FONT_COLOR_RE.fullmatch(attrs)
                color = cm and next(g for g in cm.groups() if g is not None)
                if color and '"' not in color:
                    fix = Fix(
                        edits=[
                            Edit(
                                m.start(), m.end(),
                                f'<span style="color:{color};">',
                            ),
                            Edit(close.start(), close.end(), "</span>"),
                        ],
                        applicability=Applicability.UNSAFE,
                    )
        yield Finding(
            code="ML001",
            message=f"obsolete HTML tag <{tag}>",
            start=m.start(),
            end=m.end(),
            fix=fix,
        )


# HTML tags valid in wikitext that must not be written self-closed. Void
# tags (br, hr, wbr) and extension tags (ref, gallery, ...) are absent, as
# are unknown tags, which mediawiki renders as literal text.
_HTML_NONVOID = {
    "abbr", "b", "bdi", "bdo", "big", "blockquote", "caption", "center",
    "cite", "data", "dd", "del", "dfn", "div", "dl", "dt", "em", "font",
    "h1", "h2", "h3", "h4", "h5", "h6", "i", "ins", "kbd", "li", "mark",
    "ol", "p", "q", "rb", "rp", "rt", "rtc", "ruby", "s", "samp", "small",
    "span", "strike", "strong", "sub", "sup", "table", "tbody", "td",
    "tfoot", "th", "thead", "time", "tr", "tt", "u", "ul", "var",
}
_SELF_CLOSED_RE = re.compile(r"<([A-Za-z][\w-]*)((?:\s[^<>]*?)?)\s*/\s*>")


@rule("ML002", "self-closed non-void HTML tag")
def ml002(ctx):
    """Self-closed non-void HTML tag, e.g. <span/> or <div style=... />.

    Mediawiki treats these as unclosed open tags. No fix: the author may
    have meant an open-and-close pair (<tag></tag>) or a closing tag
    (</tag>), and the two render differently. Void tags (<br/>) and
    extension tags (<ref/>, <references/>) are legitimately
    self-closable and do not fire.
    """
    for m in ctx.finditer(_SELF_CLOSED_RE):
        tag = m.group(1)
        if tag.lower() not in _HTML_NONVOID:
            continue
        yield Finding(
            code="ML002",
            message=f"self-closed non-void HTML tag <{tag}/>",
            start=m.start(),
            end=m.end(),
        )


_IMAGE_KEYWORDS = {
    "thumb", "thumbnail", "frame", "framed", "frameless", "border", "left",
    "right", "center", "centre", "none", "baseline", "sub", "super", "top",
    "text-top", "middle", "bottom", "text-bottom", "upright",
}
# a table inside a file caption is legal, and its row/cell pipes are not
# param separators; pipe attribution is ambiguous, so skip the whole link
_TABLE_IN_LINK_RE = re.compile(r"^\s*\{\|", re.M)
_IMAGE_SIZE_RE = re.compile(r"\d+px|x\d+px|\d+x\d+px")
_IMAGE_NAMED_RE = re.compile(
    r"(alt|link|page|class|lang|thumb|upright)\s*=", re.IGNORECASE
)


def _is_image_option(param: str) -> bool:
    param = param.strip()
    if not param:  # empty params are ignored by mediawiki
        return True
    return bool(
        param.lower() in _IMAGE_KEYWORDS
        or _IMAGE_SIZE_RE.fullmatch(param.lower())
        or _IMAGE_NAMED_RE.match(param)
    )


@rule("ML003", "bogus image option")
def ml003(ctx):
    """Bogus option in a file link, e.g. [[File:X.png|thumb|blah|caption]].

    Every parameter of a file link must be a recognized image option
    (thumb, left, 200px, alt=..., ...) except the caption, which mediawiki
    takes to be the last unrecognized parameter. Any other unrecognized
    parameter is silently dropped when rendering, so it is reported here.
    No fix: the intent (typoed option? misplaced caption?) is unknowable.
    Links whose caption holds table markup are skipped entirely: the
    table's pipes are indistinguishable from param separators here.
    """
    for base, bend, link in ctx.node_spans(ctx.wikicode.filter_wikilinks()):
        if not FILE_PREFIX_RE.match(str(link.title)):
            continue
        if ctx.is_shielded(base, bend):
            continue
        inner = ctx.text[base + 2 : bend - 2]
        if _TABLE_IN_LINK_RE.search(inner):
            continue
        params = list(split_top_level(inner))[1:]  # first segment = title
        bogus = [(s, e) for s, e in params if not _is_image_option(inner[s:e])]
        for s, e in bogus[:-1]:  # last unrecognized param is the caption
            yield Finding(
                code="ML003",
                message=f"bogus image option '{inner[s:e].strip()}'",
                start=base + 2 + s,
                end=base + 2 + e,
            )


_EXTLINK_RE = re.compile(
    r"\[(?:https?|ftp)://(?:[^\][\n]|\[\[[^\][\n]*?\]\])*\]"
)


@rule("ML004", "wikilink inside external link")
def ml004(ctx):
    """Wikilink inside a bracketed external link.

    In [http://... text [[Page]] more], the wikilink's brackets terminate
    the external link early, breaking it and leaking brackets into the
    rendered text. No fix: the author must decide which link to keep.
    """
    for m in ctx.finditer(_EXTLINK_RE):
        if "[[" in m.group(0):
            yield Finding(
                code="ML004",
                message="wikilink inside external link breaks the external link",
                start=m.start(),
                end=m.end(),
            )
