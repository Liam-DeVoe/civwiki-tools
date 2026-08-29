"""Local site index: a sqlite snapshot of the wiki used by cross-page rules.

Built by ``civlint index`` (network); read-only during linting so that
``civlint check`` and the tests never require a login.
"""

import re
import sqlite3
from pathlib import Path
from typing import Iterator

from civlint.anchors import page_anchors
from civlint.wikitext import CATEGORY_RE, REDIRECT_RE, transcluded_spans

DEFAULT_PATH = Path(__file__).parent.parent / "cache" / "index.db"

# namespaces crawled with full text vs titles-only (existence checks).
# ns 14 (Category) needs text so the category parent/child graph is known.
TEXT_NAMESPACES = (0, 10, 14)
TITLE_NAMESPACES = (4, 6, 12)

_SCHEMA = """
CREATE TABLE pages (
    title TEXT PRIMARY KEY,  -- normalized, with namespace prefix
    ns INTEGER NOT NULL,
    redirect TEXT,           -- normalized direct target, if a redirect
    text TEXT                -- NULL for titles-only namespaces
);
CREATE TABLE anchors (title TEXT, anchor TEXT);
CREATE TABLE categories (page TEXT, category TEXT);  -- category w/o prefix
-- expansion behavior of templates used at the top of articles, for CW101:
-- whether the template expands to nothing, and how many newlines its
-- expansion ends with (both affect whether a following blank line renders)
CREATE TABLE template_info (
    name TEXT PRIMARY KEY,   -- normalized template name
    empty INTEGER NOT NULL,
    tail INTEGER NOT NULL
);
CREATE INDEX idx_anchors ON anchors (title);
CREATE INDEX idx_categories_page ON categories (page);
CREATE INDEX idx_categories_cat ON categories (category);
"""


# magic words used in template syntax that render no output where they appear
MAGIC_WORDS = {"DISPLAYTITLE", "DEFAULTSORT"}

# aliases resolve to the namespace name pages are stored under; "Project" is
# civwiki's ns-4 alias for "CivWiki"
_NAMESPACE_ALIASES = {
    "category": "Category",
    "template": "Template",
    "file": "File",
    "image": "File",
    "project": "CivWiki",
    "civwiki": "CivWiki",
    "help": "Help",
}

_NAMESPACE_IDS = {
    "CivWiki": 4,
    "File": 6,
    "Template": 10,
    "Help": 12,
    "Category": 14,
}


def missing_index_message(path: Path = DEFAULT_PATH) -> str:
    return f"no site index at {path}; run `civlint index` first"


def normalize_title(title: str) -> str:
    title = title.replace("_", " ").strip().lstrip(":").lstrip()
    title = re.sub(r"\s+", " ", title)
    if ":" in title:
        prefix, _, rest = title.partition(":")
        prefix_norm = _NAMESPACE_ALIASES.get(prefix.strip().lower())
        if prefix_norm is not None:
            rest = rest.strip()
            return f"{prefix_norm}:{rest[:1].upper()}{rest[1:]}"
    return title[:1].upper() + title[1:]


def extract_redirect(text: str) -> str | None:
    m = REDIRECT_RE.match(text or "")
    return normalize_title(m["target"]) if m else None


def _insert_page(db: sqlite3.Connection, title: str, ns: int, text: str | None):
    """Insert one page, extracting its redirect/anchors/categories."""
    title = normalize_title(title)
    redirect = extract_redirect(text) if text is not None else None
    db.execute(
        "INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?)",
        (title, ns, redirect, text),
    )
    if text is None or redirect is not None:
        return
    for anchor in page_anchors(text):
        db.execute("INSERT INTO anchors VALUES (?, ?)", (title, anchor))
    for m in CATEGORY_RE.finditer(text):
        db.execute(
            "INSERT INTO categories VALUES (?, ?)",
            (title, normalize_title(m["name"])),
        )


class SiteIndex:
    def __init__(self, path: Path = DEFAULT_PATH):
        if not Path(path).exists():
            raise FileNotFoundError(missing_index_message(path))
        self.db = sqlite3.connect(path)
        self._template_params_cache: dict[str, frozenset[str] | None] = {}

    @classmethod
    def from_pages(
        cls,
        pages: dict[str, str | None],
        template_info: dict[str, tuple[bool, int]] | None = None,
    ) -> "SiteIndex":
        """In-memory index built from {title: wikitext}, for tests.

        Namespaces are inferred from title prefixes; pass titles-only pages
        (files etc.) with text=None. template_info maps template name to
        (expands to nothing, trailing newlines of expansion).
        """
        ix = cls.__new__(cls)
        ix.db = sqlite3.connect(":memory:")
        ix._template_params_cache = {}
        ix.db.executescript(_SCHEMA)
        for title, text in pages.items():
            prefix = normalize_title(title).partition(":")[0]
            ns = _NAMESPACE_IDS.get(prefix, 0)
            _insert_page(ix.db, title, ns, text)
        for name, (empty, tail) in (template_info or {}).items():
            ix.db.execute(
                "INSERT INTO template_info VALUES (?, ?, ?)",
                (normalize_title(name), int(empty), tail),
            )
        return ix

    def template_params(self, name: str) -> frozenset[str] | None:
        """Parameter names the template's transcluded source reads, following
        redirects. None when they can't be enumerated: the template is
        missing from the index, uses Lua (#invoke reads arguments the
        wikitext never mentions), or computes parameter names dynamically.
        """
        title = normalize_title(name)
        if not title.startswith("Template:"):
            title = f"Template:{title}"
        if title not in self._template_params_cache:
            self._template_params_cache[title] = self._template_params(title)
        return self._template_params_cache[title]

    def _template_params(self, title: str) -> frozenset[str] | None:
        import mwparserfromhell

        target = self.resolve(title)
        row = (
            self._one("SELECT text FROM pages WHERE title = ?", target)
            if target
            else None
        )
        if row is None or row[0] is None:
            return None
        body = "".join(row[0][s:e] for s, e in transcluded_spans(row[0]))
        # conservative: any #invoke (including {{safesubst:#invoke:...}}
        # wrappers) means Lua reads arguments the wikitext never mentions
        if "#invoke:" in body.lower():
            return None
        params = set()
        for arg in mwparserfromhell.parse(body).filter_arguments():
            if arg.name.filter_arguments() or arg.name.filter_templates():
                return None  # computed name, e.g. {{{ {{{n}}} }}}
            params.add(str(arg.name).strip())
        return frozenset(params)

    def template_info(self, name: str) -> tuple[bool, int] | None:
        """(expands to nothing, trailing newlines) for a template, if known."""
        row = self._one(
            "SELECT empty, tail FROM template_info WHERE name = ?",
            normalize_title(name),
        )
        return (bool(row[0]), row[1]) if row else None

    def _one(self, query: str, *args) -> tuple | None:
        return self.db.execute(query, args).fetchone()

    def redirect_target(self, title: str) -> str | None:
        row = self._one(
            "SELECT redirect FROM pages WHERE title = ?", normalize_title(title)
        )
        return row[0] if row else None

    def resolve(self, title: str) -> str | None:
        """Follow redirects to a final existing title, None if missing/loop."""
        seen = set()
        title = normalize_title(title)
        while title not in seen:
            seen.add(title)
            row = self._one(
                "SELECT redirect FROM pages WHERE title = ?", title
            )
            if row is None:
                return None
            if row[0] is None:
                return title
            title = row[0]
        return None

    def anchors(self, title: str) -> set[str]:
        rows = self.db.execute(
            "SELECT anchor FROM anchors WHERE title = ?", (normalize_title(title),)
        )
        return {r[0] for r in rows}

    def all_pages(
        self, ns: int = 0, include_redirects: bool = False
    ) -> Iterator[tuple[str, str]]:
        """(title, text) for every page in a text namespace."""
        redirect_filter = "" if include_redirects else " AND redirect IS NULL"
        rows = self.db.execute(
            "SELECT title, text FROM pages"
            f" WHERE ns = ? AND text IS NOT NULL{redirect_filter}"
            " ORDER BY title",
            (ns,),
        )
        yield from rows


def _leading_template_calls(text: str) -> Iterator[tuple[str, str]]:
    """(normalized name, as-written call) for each template in a page's
    leading region (templates/comments/whitespace before the first body
    content)."""
    import mwparserfromhell
    from mwparserfromhell.nodes import Comment, Template, Text

    for node in mwparserfromhell.parse(text).nodes:
        if isinstance(node, Template):
            name = normalize_title(str(node.name))
            # magic words and parser functions expand per-page; rules
            # special-case them instead of looking them up
            if name.partition(":")[0].upper() in MAGIC_WORDS or name.startswith("#"):
                continue
            yield name, str(node)
        elif isinstance(node, Comment):
            continue
        elif isinstance(node, Text) and not str(node).strip():
            continue
        else:
            return


def _fetch_template_info(site, calls: dict[str, str]) -> Iterator[tuple[str, bool, int]]:
    """Expand one representative as-written call per template and yield
    (name, expands to nothing, trailing newlines of expansion)."""
    for name, call in sorted(calls.items()):
        r = site.simple_request(
            action="expandtemplates", text=call, prop="wikitext"
        ).submit()
        expansion = r["expandtemplates"]["wikitext"]
        trailing_ws = expansion[len(expansion.rstrip()):]
        yield name, expansion.strip() == "", trailing_ws.count("\n")


def build(path: Path = DEFAULT_PATH) -> None:
    """Crawl the wiki and (re)build the index. Requires login."""
    from civwiki_tools import site  # deferred: triggers login

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(_SCHEMA)

    leading_calls: dict[str, str] = {}
    for ns in TEXT_NAMESPACES:
        count = 0
        for page in site.allpages(namespace=ns, content=True, filterredir="all"):
            _insert_page(db, page.title(), ns, page.text)
            if ns == 0:
                for name, call in _leading_template_calls(page.text):
                    leading_calls.setdefault(name, call)
            count += 1
            if count % 200 == 0:
                print(f"  ns {ns}: {count} pages")
        print(f"ns {ns}: {count} pages (with text)")

    print(f"expanding {len(leading_calls)} leading templates")
    for name, empty, tail in _fetch_template_info(site, leading_calls):
        db.execute(
            "INSERT OR REPLACE INTO template_info VALUES (?, ?, ?)",
            (name, int(empty), tail),
        )

    for ns in TITLE_NAMESPACES:
        count = 0
        for page in site.allpages(namespace=ns, content=False, filterredir="all"):
            _insert_page(db, page.title(), ns, None)
            count += 1
        print(f"ns {ns}: {count} titles")

    db.commit()
    db.close()
    tmp.replace(path)
    print(f"index written to {path}")
