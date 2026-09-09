"""HTML review reports: what a rule would do, before letting it edit.

`civlint report CODE` runs one rule over every page in the site index and
writes cache/review/<CODE>.html showing, per page, the findings and the diff
its fixes would produce (at the unsafe tier, so the rule's full effect is
visible). Read-only: nothing is saved to the wiki.
"""

import difflib
import html
import webbrowser
from pathlib import Path

from civlint import engine, fixer
from civlint.context import PageContext
from civlint.index import SiteIndex
from civlint.types import REGISTRY

REVIEW_DIR = Path(__file__).parent.parent / "cache" / "review"

CSS = """
body { font-family: -apple-system, sans-serif; margin: 2rem auto; max-width: 70rem; }
pre { margin: 0; white-space: pre-wrap; word-break: break-all; font-size: 13px; }
.del { background: #ffeef0; }
.add { background: #e6ffec; }
.delseg { background: #ffb3ba; border-radius: 2px; }
.addseg { background: #97e8a9; border-radius: 2px; }
.hunk { color: #888; }
mark { background: #fff3a3; }
details { border: 1px solid #ddd; border-radius: 6px; margin: .5rem 0; padding: .3rem .6rem; }
summary { cursor: pointer; font-weight: 600; }
.meta { color: #555; font-weight: 400; }
.finding { color: #555; font-size: 13px; margin: .2rem 0; }
a { color: #36c; text-decoration: none; }
"""


def _visible_ws(s):
    """Changed whitespace rendered as visible glyphs."""
    return html.escape(s).replace(" ", "·").replace("\t", "⇥")


def _intraline(old, new):
    """(old_html, new_html) with only the changed segments highlighted."""
    out_old, out_new = [], []
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            out_old.append(html.escape(old[i1:i2]))
            out_new.append(html.escape(new[j1:j2]))
            continue
        if i2 > i1:
            out_old.append(f'<span class="delseg">{_visible_ws(old[i1:i2])}</span>')
        if j2 > j1:
            out_new.append(f'<span class="addseg">{_visible_ws(new[j1:j2])}</span>')
    return "".join(out_old), "".join(out_new)


def diff_html(before, after):
    lines = []
    dels, adds = [], []

    def flush():
        # pair removed/added lines index-wise for intra-line highlighting
        old_htmls, new_htmls = [], []
        for k in range(max(len(dels), len(adds))):
            old = dels[k] if k < len(dels) else None
            new = adds[k] if k < len(adds) else None
            if old is not None and new is not None:
                oh, nh = _intraline(old, new)
                old_htmls.append(oh)
                new_htmls.append(nh)
            elif old is not None:
                old_htmls.append(html.escape(old))
            else:
                new_htmls.append(html.escape(new))
        lines.extend(f'<pre class="del">-{h}</pre>' for h in old_htmls)
        lines.extend(f'<pre class="add">+{h}</pre>' for h in new_htmls)
        dels.clear()
        adds.clear()

    for line in difflib.unified_diff(
        before.splitlines(), after.splitlines(), lineterm="", n=2
    ):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("-"):
            dels.append(line[1:])
        elif line.startswith("+"):
            adds.append(line[1:])
        else:
            flush()
            cls = ' class="hunk"' if line.startswith("@@") else ""
            lines.append(f"<pre{cls}>{html.escape(line)}</pre>")
    flush()
    return "\n".join(lines)


def context_html(text, finding):
    """For report-only findings: nearby lines with the finding span marked."""
    line_start = text.rfind("\n", 0, finding.start) + 1
    line_end = text.find("\n", finding.end)
    line_end = len(text) if line_end == -1 else line_end
    before = html.escape(text[line_start : finding.start])
    marked = html.escape(text[finding.start : finding.end])
    after = html.escape(text[finding.end : line_end])
    return f"<pre>{before}<mark>{marked}</mark>{after}</pre>"


def generate(code, ns=0, limit=None, open_browser=False):
    rule = REGISTRY.get(code)
    if rule is None:
        raise SystemExit(f"unknown rule {code!r}")

    ix = SiteIndex()
    sections = []
    total_findings = 0
    total_pages = 0
    changed_pages = 0

    for title, text in ix.all_pages(ns=ns, include_redirects=True):

        def lint(t, _title=title):
            return engine.lint(PageContext(_title, t, ix), select=[code])

        findings = lint(text)
        if not findings:
            continue
        total_pages += 1
        total_findings += len(findings)
        fixed = fixer.apply_fixes(text, lint, unsafe=True)[0]
        if fixed != text:
            changed_pages += 1
        if limit and len(sections) >= limit:
            continue

        finding_lines = "\n".join(
            f'<div class="finding">line {f.line(text)}: {html.escape(f.message)}'
            + (f" [{f.fix.applicability.value} fix]" if f.fix else " [report only]")
            + "</div>"
            + ("" if fixed != text else context_html(text, f))
            for f in findings
        )
        body = diff_html(text, fixed) if fixed != text else ""
        url = f"https://civwiki.org/wiki/{html.escape(title.replace(' ', '_'))}"
        sections.append(
            f"<details><summary>{html.escape(title)} "
            f'<span class="meta">({len(findings)})</span> '
            f'<a href="{url}" target="_blank">wiki</a></summary>'
            f"{finding_lines}{body}</details>"
        )

    shown = ""
    if limit and total_pages > limit:
        shown = f" (showing first {limit} pages)"
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / f"{code}.html"
    out.write_text(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{code} review</title>
<style>{CSS}</style></head><body>
<h1>{code}: {html.escape(rule.summary)}</h1>
<pre style="color:#555">{html.escape(rule.doc)}</pre>
<p><b>{total_findings}</b> findings on <b>{total_pages}</b> pages;
fixes change <b>{changed_pages}</b> pages{shown}.</p>
{"".join(sections)}
</body></html>""")
    print(
        f"{code}: {total_findings} findings, {total_pages} pages, "
        f"{changed_pages} changed -> {out}"
    )
    if open_browser:
        webbrowser.open(out.as_uri())
