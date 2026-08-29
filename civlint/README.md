# civlint

A ruff-style linter for civwiki.org. Rules are grouped by origin:

| Prefix | Origin |
|---|---|
| `ML` | MediaWiki Linter extension (lexical subset) |
| `WP` | WikiProject Check Wikipedia (upstream numbers preserved) |
| `PC` | pywikibot `cosmetic_changes` ports |
| `BA` | WikiProject Broken section anchors |
| `TY` | Typo Team/moss (known-misspellings list only) |
| `CW` | civwiki-specific rules |

## Usage

```bash
python3.12 -m civlint index                    # build the site index (login)
python3.12 -m civlint list                     # list rules
python3.12 -m civlint rule CW101              # show a rule's doc
python3.12 -m civlint check "Some Page"        # lint one page (live fetch)
python3.12 -m civlint check --all              # lint every ns-0 page from index
python3.12 -m civlint check --all --fix        # ... show diffs of safe fixes
python3.12 -m civlint check --all --fix --save # ... apply them (max --limit edits)
python3.12 -m civlint check --all --format json > findings.json
```

## Review workflow

The intended loop for turning a rule live is: scan, review its report, then
let it edit.

```bash
python3.12 -m civlint report CW101 --open        # HTML report of what the
                                                 # rule would change, per page
python3.12 -m civlint check --all --select CW101 --fix --save --limit 50
```

`report` writes `cache/review/<CODE>.html` with per-page diffs (intra-line
highlighting, whitespace changes made visible) and links to the live pages.
It shows fixes at the unsafe tier so the rule's full effect is visible;
report-only findings get context snippets instead of diffs. Use `--ns 10`
for template-namespace rules and `--limit` to sample large rules.

`--select`/`--ignore` take code prefixes (`--select CW --select WP538`).
Defaults can be set in `pyproject.toml` under `[tool.civlint]` (`select`,
`ignore`). A page can opt out of rules with an invisible comment:
`<!-- civlint: disable=WP538,TY -->`.

## Writing a rule

Rules live in `civlint/rules/<prefix>.py`. A rule is a generator registered
with `@rule`; it receives a `PageContext` and yields `Finding`s whose offsets
point into the raw wikitext:

```python
from civlint.types import Applicability, Edit, Finding, Fix, rule

@rule("CW999", "one-line summary shown in listings")
def civ999(ctx):
    """Longer doc shown by `civlint rule CW999`."""
    for m in ctx.finditer(r"pattern"):        # skips nowiki/comments/pre/...
        yield Finding(
            code="CW999",
            message="what is wrong here",
            start=m.start(),
            end=m.end(),
            fix=Fix(  # omit for report-only findings
                edits=[Edit(m.start(), m.end(), "replacement")],
                applicability=Applicability.SAFE,  # or UNSAFE
            ),
        )
```

Conventions:

- Use `ctx.finditer()` / `ctx.is_shielded()` so rules never fire inside
  comments, `<nowiki>`, `<pre>`, `<syntaxhighlight>`, `<code>`, or `<math>`.
- `ctx.wikicode` is a shared `mwparserfromhell` parse of the page.
  `ctx.template_spans` / `ctx.mask_spans` are cached outermost `{{...}}`
  (and table) spans; `ctx.node_spans()` locates parser nodes in the raw
  text. Wikitext primitives shared by several rules (category/redirect/
  heading regexes, `split_top_level`, `remove_span_and_line`, `overlaps`)
  live in `civlint/wikitext.py` — use those instead of writing new ones.
- Rules needing the site index declare `@rule(..., requires_index=True)` and
  use `ctx.index` (`resolve`, `anchors`, `categories_of`,
  `parent_categories`, ... — see `civlint/index.py`). They are
  skipped automatically when no index is available.
- SAFE fixes must be behavior-preserving on rendered output in essentially
  all cases; anything that could change meaning or lose content is UNSAFE.
- Fixes are re-linted to a fixpoint, so a fix may handle one instance at a
  time, but the result must be idempotent.

## Testing

Fixture format is documented in `tests/test_fixtures.py`; every non-index
rule must have at least one fixture. Index rules are tested in
`tests/test_<prefix>.py` against an in-memory index built with
`SiteIndex.from_pages({title: wikitext})`. Run with:

```bash
python3.12 -m pytest tests/ -q
```
