"""ba rules. See civlint/README.md for conventions."""

import difflib

from civlint.anchors import normalize_fragment, page_anchors
from civlint.types import Finding, rule
from civlint.wikitext import FILE_PREFIX_RE, REDIRECT_RE


def _broken(fragment: str, anchors: set[str]) -> str | None:
    """None if the fragment resolves; else a message suffix (may suggest)."""
    frag = normalize_fragment(fragment)
    if not frag or frag in anchors:
        return None
    for a in sorted(anchors):
        if a.lower() == frag.lower():
            return f"; did you mean '{a}'?"
    close = difflib.get_close_matches(frag, sorted(anchors), n=1, cutoff=0.75)
    return f"; did you mean '{close[0]}'?" if close else ""


def _target_anchors(ctx, target: str) -> tuple[str, set[str]] | None:
    """(display title, anchors) for a link target, or None to skip it."""
    if target == "":  # same-page link: use the page's own current text
        return ctx.title, page_anchors(ctx.text)
    if FILE_PREFIX_RE.match(target):
        return None
    resolved = ctx.index.resolve(target)
    if resolved is None:  # missing page: CW103's job, not ours
        return None
    # the index only has text (hence anchors) for ns 0 and Category
    if ":" in resolved and not resolved.startswith("Category:"):
        return None
    return resolved, ctx.index.anchors(resolved)


@rule("BA001", "broken section anchor in wikilink", requires_index=True)
def ba001(ctx):
    """[[Page#Section]] link whose section does not exist on Page.

    The target is resolved through redirects; #Section must match a heading
    or {{anchor}} on the resolved page (compared via normalize_fragment).
    Links to missing pages and interwiki-style prefixes are skipped, as are
    redirect pages themselves (BA002 covers those).
    """
    if REDIRECT_RE.match(ctx.text):
        return
    for start, end, link in ctx.node_spans(ctx.wikicode.filter_wikilinks()):
        title = str(link.title)
        if "#" not in title:
            continue
        if ctx.is_shielded(start, end):
            continue
        target, frag = title.split("#", 1)
        target = target.strip().lstrip(":").strip()
        resolved = _target_anchors(ctx, target)
        if resolved is None:
            continue
        display, anchors = resolved
        suffix = _broken(frag, anchors)
        if suffix is None:
            continue
        yield Finding(
            code="BA001",
            message=(
                f"section '#{frag.strip()}' not found"
                f" on [[{display}]]{suffix}"
            ),
            start=start,
            end=end,
        )


@rule("BA002", "redirect to a broken section anchor", requires_index=True)
def ba002(ctx):
    """#REDIRECT [[Page#Section]] whose section does not exist on Page.

    Fires on the redirect page itself, checked the same way as BA001.
    """
    m = REDIRECT_RE.match(ctx.text)
    if m is None or m["fragment"] is None:
        return
    frag = m["fragment"][1:]
    if not frag.strip():
        return
    resolved = _target_anchors(ctx, m["target"].strip().lstrip(":").strip())
    if resolved is None:
        return
    display, anchors = resolved
    suffix = _broken(frag, anchors)
    if suffix is None:
        return
    yield Finding(
        code="BA002",
        message=(
            f"redirect to section '#{frag.strip()}' which does not"
            f" exist on [[{display}]]{suffix}"
        ),
        start=m.start("open"),
        end=m.end("fragment"),
    )
