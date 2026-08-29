import argparse
import difflib
import json
import sys
import tomllib
from pathlib import Path

from civlint import engine, fixer
from civlint.context import PageContext
from civlint.index import SiteIndex, missing_index_message
from civlint.types import REGISTRY, selected_codes

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def _config() -> dict:
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f).get("tool", {}).get("civlint", {})


def _load_index():
    try:
        return SiteIndex()
    except FileNotFoundError:
        return None


def _iter_pages(args, index):
    """Yield (title, text) for the pages selected on the command line."""
    if args.all:
        if index is None:
            sys.exit(f"--all requires a site index; {missing_index_message()}")
        yield from index.all_pages(ns=args.ns, include_redirects=True)
        return
    from civwiki_tools import site  # deferred: triggers login

    if args.category:
        import pywikibot

        category = pywikibot.Category(site, f"Category:{args.category}")
        for page in category.members(namespaces=[0]):
            yield page.title(), page.text
        return
    for title in args.pages:
        page = site.page(title)
        if not page.exists():
            print(f"warning: page {title!r} does not exist", file=sys.stderr)
            continue
        yield page.title(), page.text


def cmd_check(args) -> int:
    config = _config()
    select = args.select or config.get("select")
    ignore = args.ignore or config.get("ignore")
    index = _load_index()
    if index is None:
        skipped = [
            c for c in selected_codes(select, ignore)
            if REGISTRY[c].requires_index
        ]
        if skipped:
            print(
                f"warning: skipping {len(skipped)} index rules:"
                f" {missing_index_message()}",
                file=sys.stderr,
            )
    exit_code = 0
    edited = 0
    results = []

    for title, text in _iter_pages(args, index):
        def lint_text(t, _title=title):
            return engine.lint(
                PageContext(_title, t, index), select=select, ignore=ignore
            )

        if args.fix:
            fixed_text, applied, remaining = fixer.apply_fixes(
                text, lint_text, unsafe=args.unsafe_fixes
            )
        else:
            fixed_text, applied, remaining = text, None, lint_text(text)
        if not remaining and fixed_text == text:
            continue
        # ruff semantics: with --fix, only findings that remain unfixed fail
        # the run; a fully-fixed page is a success
        if remaining:
            exit_code = 1

        if args.format == "json":
            results.append({
                "title": title,
                "fixed": dict(applied) if applied else {},
                "findings": [
                    {
                        "code": f.code,
                        "message": f.message,
                        "line": f.line(fixed_text),
                        "fixable": f.fix.applicability.value if f.fix else None,
                    }
                    for f in remaining
                ],
            })
            continue

        print(f"\n== {title} ==")
        if applied:
            summary = ", ".join(f"{c} x{n}" for c, n in sorted(applied.items()))
            print(f"  fixed: {summary}")
        for f in remaining:
            tag = f" [{f.fix.applicability.value} fix]" if f.fix else ""
            print(f"  {f.line(fixed_text)}: {f.code} {f.message}{tag}")
        if args.fix and fixed_text != text:
            if args.diff or not args.save:
                diff = difflib.unified_diff(
                    text.splitlines(keepends=True),
                    fixed_text.splitlines(keepends=True),
                    fromfile=title,
                    tofile=f"{title} (fixed)",
                )
                sys.stdout.writelines(diff)
            if args.save:
                if edited >= args.limit:
                    print(f"  (edit limit {args.limit} reached, not saving)")
                    continue
                from civwiki_tools import site

                page = site.page(title)
                # `text` may come from a stale index snapshot; saving text
                # derived from it would silently revert newer wiki edits.
                # Re-apply the fixes to the live text instead.
                live = page.get()
                if live != text:
                    fixed_live, applied, _ = fixer.apply_fixes(
                        live, lint_text, unsafe=args.unsafe_fixes
                    )
                    if fixed_live == live:
                        print("  (page changed since index; no fixes apply)")
                        continue
                    fixed_text = fixed_live
                page.text = fixed_text
                codes = ", ".join(sorted(applied or {}))
                summary = f"automated: civlint --fix ({codes})"
                try:
                    page.save(summary=summary)
                except Exception as err:
                    # a concurrent login with the same account rotates the
                    # session and invalidates our CSRF token; refresh and
                    # retry once rather than aborting the whole batch
                    from civwiki_tools.utils import relog

                    print(f"  save failed ({err}); refreshing tokens and retrying")
                    relog()
                    try:
                        page.save(summary=summary)
                    except Exception as err2:
                        print(f"  save failed again, skipping page: {err2}",
                              file=sys.stderr)
                        continue
                edited += 1
                print("  saved.")

    if args.format == "json":
        json.dump(results, sys.stdout, indent=2)
        print()
    return exit_code


def cmd_report(args) -> int:
    from civlint import report

    report.generate(args.code, ns=args.ns, limit=args.limit,
                    open_browser=args.open)
    return 0


def cmd_rule(args) -> int:
    rule = REGISTRY.get(args.code)
    if rule is None:
        sys.exit(f"unknown rule {args.code!r}")
    print(f"{rule.code}: {rule.summary}")
    if rule.requires_index:
        print("(requires site index)")
    print()
    print(rule.doc)
    return 0


def cmd_list(args) -> int:
    for code in sorted(REGISTRY):
        rule = REGISTRY[code]
        print(f"{code:8} {rule.summary}")
    return 0


def cmd_index(args) -> int:
    from civlint import index

    index.build()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="civlint")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="lint pages")
    p.add_argument("pages", nargs="*", help="page titles (fetched live)")
    p.add_argument("--all", action="store_true", help="all pages of --ns from the index")
    p.add_argument("--ns", type=int, default=0,
                   help="namespace for --all (0 articles, 10 templates)")
    p.add_argument("--category", help="lint members of a category")
    p.add_argument("--select", action="append", help="rule code prefix to run")
    p.add_argument("--ignore", action="append", help="rule code prefix to skip")
    p.add_argument("--fix", action="store_true", help="apply safe fixes")
    p.add_argument("--unsafe-fixes", action="store_true", help="also apply unsafe fixes")
    p.add_argument("--diff", action="store_true", help="show diffs of fixes")
    p.add_argument("--save", action="store_true", help="save fixes to the wiki")
    p.add_argument("--limit", type=int, default=25, help="max pages to edit with --save")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("report", help="write an HTML review report for one rule")
    p.add_argument("code")
    p.add_argument("--ns", type=int, default=0, help="namespace to scan")
    p.add_argument("--limit", type=int, help="cap pages shown in the report")
    p.add_argument("--open", action="store_true", help="open in the browser")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("rule", help="show a rule's documentation")
    p.add_argument("code")
    p.set_defaults(func=cmd_rule)

    p = sub.add_parser("list", help="list all rules")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("index", help="build/refresh the site index (requires login)")
    p.set_defaults(func=cmd_index)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
