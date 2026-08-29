"""CW rules: civwiki-specific checks. See civlint/README.md for conventions."""

import re

import mwparserfromhell
from mwparserfromhell.nodes import Comment, Heading, Template, Text

from civlint.index import MAGIC_WORDS, normalize_title
from civlint.types import Applicability, Edit, Finding, Fix, rule
from civlint.wikitext import (
    CATEGORY_RE,
    COMMENT_RE,
    REDIRECT_RE,
    remove_span_and_line,
    transcluded_spans,
)

def _top_level_spans(ctx):
    """(offset, node) for each top-level node of ctx.wikicode."""
    offset = 0
    for node in ctx.wikicode.nodes:
        yield offset, node
        offset += len(str(node))


def _template_expansion(index, name: str) -> tuple[bool, int] | None:
    """(expands to nothing, trailing newlines), None if unknown."""
    if name.partition(":")[0].upper() in MAGIC_WORDS:
        return (True, 0)
    return index.template_info(name)


@rule("CW101", "blank line rendered at top of article", requires_index=True)
def civ101(ctx):
    """Blank lines at the top of a page that render as an empty paragraph
    above the article.

    Mediawiki renders an empty paragraph where the text has, after template
    expansion, three or more consecutive newlines (two at the very start of
    the page). So visibility depends on the template before the gap: a
    template whose expansion ends with a newline shows a gap after a single
    blank line, one that doesn't needs two. Expansion behavior per template
    is cached in the site index; for templates missing from it the rule
    conservatively assumes no trailing newline. Semantics validated against
    the wiki's parse API on a rendered sample.

    The fix shrinks each gap to the widest run that renders nothing.
    """
    # trailing newlines of the page-so-far after template expansion; the
    # page start counts as one virtual newline
    tail = 1
    known = True
    for offset, node in _top_level_spans(ctx):
        s = str(node)
        if isinstance(node, Comment):
            continue
        if isinstance(node, Template):
            info = _template_expansion(ctx.index, normalize_title(str(node.name)))
            if info is None:
                tail, known = 0, False
            elif not info[0]:  # empty expansions pass the tail through
                tail, known = info[1], True
            continue
        if not isinstance(node, Text):
            break
        ws = len(s) - len(s.lstrip())
        gap = s[:ws] if ws < len(s) else s
        n = gap.count("\n")
        after_gap = ctx.text[offset + len(gap):].strip()
        if n and after_gap and not ctx.is_shielded(offset, offset + len(gap)):
            visible = tail + n >= 3
            if visible and not known:
                # unknown template: only flag what renders regardless of it
                visible = n >= 3
            keep = max(2 - tail, 1)
            if visible:
                yield Finding(
                    code="CW101",
                    message="blank line at the top of the article renders as"
                    " an empty paragraph",
                    start=offset,
                    end=offset + len(gap),
                    fix=Fix(
                        edits=[Edit(offset, offset + len(gap), "\n" * keep)],
                        applicability=Applicability.SAFE,
                    )
                    if tail + keep < 3
                    else None,
                )
        if ws < len(s):
            break  # body content starts inside this text node
        tail += n


@rule("CW102", "empty heading")
def civ102(ctx):
    """A heading whose title is empty or only whitespace/comments, e.g.
    `== ==` or `== <!--todo--> ==`, renders as a blank section header.

    The fix (unsafe: the heading may have been a placeholder for planned
    content) deletes the heading line.
    """
    for offset, node in _top_level_spans(ctx):
        if not isinstance(node, Heading):
            continue
        if COMMENT_RE.sub("", str(node.title)).strip():
            continue
        end = offset + len(str(node))
        # only check the start: a comment inside the title is itself a
        # shielded span but doesn't shield the heading markup
        if ctx.is_shielded(offset):
            continue
        del_end = end + 1 if ctx.text[end : end + 1] == "\n" else end
        yield Finding(
            code="CW102",
            message=f"empty heading (level {node.level})",
            start=offset,
            end=end,
            fix=Fix(
                edits=[Edit(offset, del_end, "")],
                applicability=Applicability.UNSAFE,
            ),
        )


@rule("CW110", "literal signature tildes in article text")
def civ110(ctx):
    """A run of 3, 4, or 5 tildes is signature markup (`~~~~` expands to a
    signature on save) and never belongs in article text. Wrap it in
    <nowiki> if the tildes are intentional, otherwise remove it.
    """
    for m in ctx.finditer(r"(?<!~)~{3,5}(?!~)"):
        yield Finding(
            code="CW110",
            message="literal signature tildes; wrap in <nowiki> or remove",
            start=m.start(),
            end=m.end(),
        )


# a wikilink; the label part may contain nested (complete) links, as in
# image captions
_LINK_RE = re.compile(
    r"\[\[([^\[\]|\n]*)(?:\|(?:[^\[\]]|\[\[[^\[\]]*\]\])*)?\]\]"
)
_LINK_NAMESPACES = {
    "file", "image", "category", "template", "project", "civwiki", "help",
}


@rule("CW103", "redlink: link to a nonexistent page", requires_index=True)
def civ103(ctx):
    """An internal link whose target does not exist on the wiki (following
    redirects). Links with a namespace prefix other than
    File/Image/Category/Template/Project/Help are assumed to be interwiki and
    skipped, as are category membership tags, pure-fragment links, and
    templated targets.
    """
    for m in ctx.finditer(_LINK_RE):
        title = m.group(1).partition("#")[0].strip()
        colon = title.startswith(":")
        title = title.lstrip(":").strip()
        if not title or "://" in title or "{" in title:
            continue
        if ":" in title:
            prefix = title.partition(":")[0].strip().lower()
            if prefix not in _LINK_NAMESPACES:
                continue  # probably interwiki
            if prefix == "category" and not colon:
                continue  # category membership, not a link
        if ctx.index.resolve(title) is None:
            yield Finding(
                code="CW103",
                message=f"links to nonexistent page '{title}'",
                start=m.start(),
                end=m.end(),
            )


def _ancestor_categories(index, category: str, depth: int = 3) -> set[str]:
    """Categories reachable upward from `category` within `depth` steps."""
    seen = {category}
    frontier = {category}
    out: set[str] = set()
    for _ in range(depth):
        frontier = {
            p for c in frontier for p in index.parent_categories(c)
        } - seen
        out |= frontier
        seen |= frontier
    return out


@rule("CW120", "redundant parent category", requires_index=True)
def civ120(ctx):
    """The page is in both a category and one of that category's ancestor
    categories (up to three levels up); membership in the ancestor is
    redundant. The fix (unsafe: some parent categories intentionally hold
    pages directly) removes the ancestor's category tag.
    """
    links = [(normalize_title(m["name"]), m) for m in ctx.finditer(CATEGORY_RE)]
    if len(links) < 2:
        return
    ancestors = {name: _ancestor_categories(ctx.index, name) for name, _ in links}
    for name, m in links:
        child = next(
            (
                other
                for other in sorted(ancestors)
                if other != name
                and name in ancestors[other]
                # mutual ancestry means a category cycle; firing on both
                # would strip the page's categorization entirely
                and other not in ancestors[name]
            ),
            None,
        )
        if child is None:
            continue
        s, e = m.span()
        del_start, del_end = remove_span_and_line(ctx.text, s, e)
        yield Finding(
            code="CW120",
            message=f"category '{name}' is redundant: the page is already in"
            f" its subcategory '{child}'",
            start=s,
            end=e,
            fix=Fix(
                edits=[Edit(del_start, del_end, "")],
                applicability=Applicability.UNSAFE,
            ),
        )


@rule("CW121", "double redirect", requires_index=True)
def civ121(ctx):
    """This page redirects to a page that is itself a redirect, so readers
    land on the intermediate page instead of the destination. The fix
    retargets the redirect at the final destination, keeping any fragment.
    If the redirect chain loops or ends at a missing page there is no safe
    rewrite and the finding is report-only.
    """
    m = REDIRECT_RE.match(ctx.text)
    if m is None or ctx.index.redirect_target(m["target"]) is None:
        return
    target = m["target"].strip()
    final = ctx.index.resolve(target)
    start, end = m.start("open"), m.end()  # the [[...]] link
    if final is None:
        yield Finding(
            code="CW121",
            message=f"redirects to '{target}', itself a redirect whose chain"
            " is broken or loops",
            start=start,
            end=end,
        )
        return
    yield Finding(
        code="CW121",
        message=f"double redirect via '{target}'; final target is '{final}'",
        start=start,
        end=end,
        fix=Fix(
            edits=[Edit(m.start("target"), m.end("target"), final)],
            applicability=Applicability.SAFE,
        ),
    )


@rule("CW130", "template transcludes trailing whitespace")
def cw130(ctx):
    """A template whose transcluded output ends with whitespace, which is
    invisible on the template page but transcludes into every article. A
    trailing newline makes a single blank line after the template call
    render as an empty paragraph (see CW101); trailing spaces can leave a
    stray space before adjacent article text. The usual cause is whitespace
    between the end of the template body and `<noinclude>`.

    The fix deletes the trailing transcluded whitespace. Unsafe: a template
    designed to be stacked into line-start syntax (e.g. a table-row template
    used as `{{row}}{{row}}`) may need the newline — check the template's
    transclusions before accepting.
    """
    if not ctx.title.startswith("Template:"):
        return
    if ctx.title.endswith("/doc"):
        return  # doc subpages transclude only into <noinclude> blocks
    if REDIRECT_RE.match(ctx.text):
        return
    spans = transcluded_spans(ctx.text)
    # trailing transcluded whitespace, mapped back to source spans
    edits = []
    newlines = 0
    for s, e in reversed(spans):
        chunk = ctx.text[s:e]
        stripped = len(chunk.rstrip())
        if stripped:
            if stripped < len(chunk):
                edits.append(Edit(s + stripped, e, ""))
                newlines += chunk[stripped:].count("\n")
            break
        edits.append(Edit(s, e, ""))
        newlines += chunk.count("\n")
    if not edits:
        return
    edits.reverse()
    message = (
        "transcluded output ends with a newline; articles get a stray"
        " blank line"
        if newlines
        else "transcluded output ends with spaces; articles get stray"
        " whitespace"
    )
    yield Finding(
        code="CW130",
        message=message,
        start=edits[0].start,
        end=edits[-1].end,
        fix=Fix(edits=edits, applicability=Applicability.UNSAFE),
    )


_CW131_MIN_NAMED_PARAMS = 4


@rule("CW131", "many-parameter template call on one line")
def cw131(ctx):
    """A template call alone on its line with four or more named parameters
    all crammed onto that line — typically a one-line infobox. One parameter
    per line is much easier to read and edit. Inline uses are not flagged:
    the call must both start and end its line.

    The fix puts each parameter on its own line. Mediawiki strips whitespace
    around named parameter names and values, so the rewrite is
    render-preserving (safe). A call that also has unnamed parameters is
    report-only, since their whitespace is part of the value.
    """
    for s, e in ctx.template_spans:
        raw = ctx.text[s:e]
        if "\n" in raw:
            continue
        if s > 0 and ctx.text[s - 1] != "\n":
            continue
        nl = ctx.text.find("\n", e)
        if ctx.text[e : len(ctx.text) if nl == -1 else nl].strip():
            continue
        parsed = mwparserfromhell.parse(raw)
        if len(parsed.nodes) != 1 or not isinstance(parsed.nodes[0], Template):
            continue
        tpl = parsed.nodes[0]
        name = str(tpl.name).strip()
        if name.startswith("#") or name.partition(":")[0].upper() in MAGIC_WORDS:
            continue
        named = sum(1 for p in tpl.params if p.showkey)
        if named < _CW131_MIN_NAMED_PARAMS:
            continue
        fix = None
        if named == len(tpl.params):
            body = "".join(f"\n|{str(p).strip()}" for p in tpl.params)
            fix = Fix(
                edits=[Edit(s, e, "{{" + name + body + "\n}}")],
                applicability=Applicability.SAFE,
            )
        yield Finding(
            code="CW131",
            message=f"{named} named parameters on one line; put one"
            " parameter per line",
            start=s,
            end=e,
            fix=fix,
        )


@rule(
    "CW132",
    "unnamed argument to a template with no positional parameters",
    requires_index=True,
)
def cw132(ctx):
    """An unnamed argument passed to a template whose source never reads
    positional parameters ({{{1}}} and so on), so the template silently
    ignores it. The usual cause is a pipe typed where an `=` was meant, as
    in `|alt|Some caption` for `|alt=Some caption`.

    Parameter names come from the template's transcluded source in the site
    index. Templates whose parameters can't be enumerated are skipped
    entirely: missing pages, Lua-backed templates (#invoke reads arguments
    the wikitext never mentions), and computed {{{...}}} names.

    Two shapes get a fix, both unsafe since they change what the template
    receives: an argument whose text is one of the template's parameter
    names, followed by another unnamed argument, gains the missing `=`; and
    an empty argument (a stray `||`) is deleted. Anything else is
    report-only.
    """
    for s, _, tpl in ctx.node_spans(ctx.wikicode.filter_templates()):
        if ctx.is_shielded(s):
            continue
        if all(p.showkey for p in tpl.params):
            continue
        name = str(tpl.name).strip()
        if name.startswith((":", "#", "{")):
            continue
        if name.partition(":")[0].upper() in MAGIC_WORDS:
            continue
        declared = ctx.index.template_params(name)
        if declared is None or any(d.isdigit() for d in declared):
            continue
        named_keys = {str(p.name).strip() for p in tpl.params if p.showkey}
        # str(tpl) reproduces the source exactly, so parameter offsets
        # follow arithmetically: {{, name, then "|" + param, repeated
        spans = []
        pos = s + 2 + len(str(tpl.name))
        for p in tpl.params:
            spans.append((pos + 1, pos + 1 + len(str(p))))
            pos = spans[-1][1]
        i = 0
        while i < len(tpl.params):
            p = tpl.params[i]
            ps, pe = spans[i]
            if p.showkey:
                i += 1
                continue
            value = str(p).strip()
            nxt = tpl.params[i + 1] if i + 1 < len(tpl.params) else None
            if (
                value in declared
                and value not in named_keys
                and nxt is not None
                and not nxt.showkey
                # a following argument that is itself a parameter name is a
                # run of bare names, not a name|value pair to merge
                and str(nxt).strip() not in declared
            ):
                yield Finding(
                    code="CW132",
                    message=f"unnamed argument '{value}'; likely a missing"
                    f" '=' ('{name}' has a '{value}' parameter)",
                    start=ps - 1,
                    end=spans[i + 1][1],
                    fix=Fix(
                        # trailing whitespace of the argument, the pipe, and
                        # the next argument's leading whitespace become "="
                        edits=[
                            Edit(
                                ps + len(str(p).rstrip()),
                                spans[i + 1][0]
                                + len(str(nxt))
                                - len(str(nxt).lstrip()),
                                "=",
                            )
                        ],
                        applicability=Applicability.UNSAFE,
                    ),
                )
                i += 2
                continue
            if value:
                fix = None
                message = (
                    f"unnamed argument to '{name}', which has no"
                    " positional parameters"
                )
            else:
                fix = Fix(
                    edits=[Edit(ps - 1, pe, "")],
                    applicability=Applicability.UNSAFE,
                )
                message = f"empty argument to '{name}' (stray '|')"
            yield Finding(
                code="CW132", message=message, start=ps - 1, end=pe, fix=fix
            )
            i += 1
