"""Heading/anchor normalization shared by the index builder and BA rules.

Mediawiki turns a heading into a fragment anchor by stripping markup and
replacing spaces with underscores. We compare fragments in normalized space
form (underscores back to spaces) so that ``[[Page#Some Section]]`` matches a
``== Some Section ==`` heading.
"""

import html
import re
from urllib.parse import unquote

import mwparserfromhell

from civlint.wikitext import COMMENT_RE, HEADING_RE

ANCHOR_TEMPLATES = {"anchor", "anchors"}


def normalize_fragment(fragment: str) -> str:
    """Normalize a link fragment or heading-derived anchor for comparison."""
    fragment = unquote(fragment)
    # legacy ".XX" percent-style encoding produced by older mediawiki
    fragment = re.sub(r"\.([0-9A-F]{2})", lambda m: chr(int(m.group(1), 16)), fragment)
    fragment = html.unescape(fragment)
    fragment = fragment.replace("_", " ")
    return re.sub(r"\s+", " ", fragment).strip()


def heading_anchor(heading_wikitext: str) -> str:
    """Anchor for a heading's inner wikitext (markup stripped)."""
    code = mwparserfromhell.parse(heading_wikitext)
    return normalize_fragment(code.strip_code(normalize=True, collapse=True))


def page_anchors(text: str) -> set[str]:
    """All normalized anchors defined by a page: headings and {{anchor}}s."""
    # mediawiki strips comments before parsing headings, so a heading with a
    # trailing comment still defines its anchor
    without_comments = COMMENT_RE.sub("", text)
    anchors = {
        heading_anchor(m["title"]) for m in HEADING_RE.finditer(without_comments)
    }
    code = mwparserfromhell.parse(text)
    for template in code.filter_templates():
        if template.name.strip().lower() in ANCHOR_TEMPLATES:
            for param in template.params:
                if not param.showkey:
                    anchors.add(normalize_fragment(str(param.value).strip()))
    anchors.discard("")
    return anchors
