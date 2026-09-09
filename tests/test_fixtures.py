"""Fixture-driven rule tests.

Each rule has fixtures under tests/fixtures/<CODE>/<case>/:

- input.wiki        the page wikitext to lint (page title = the case name)
- expected.txt      one line per expected finding: "<CODE>:<line-number>".
                    An empty file means the rule must report nothing.
- title.txt         (optional) page title to lint under, when the rule cares
                    (e.g. Template: pages); defaults to the case name
- fixed.wiki        (optional) the text after applying this rule's fixes at
                    the UNSAFE tier, to a fixpoint. Omit for report-only rules.

Only the fixture's own rule runs, so fixtures stay independent of the rest of
the catalog. Fixes must also be idempotent: fixing fixed.wiki changes nothing.
"""

from pathlib import Path

import pytest

from civlint import engine, fixer
from civlint.context import PageContext
from civlint.types import REGISTRY

FIXTURES = Path(__file__).parent / "fixtures"

CASES = sorted(
    (case_dir.parent.name, case_dir)
    for case_dir in FIXTURES.glob("*/*")
    if (case_dir / "input.wiki").is_file()
)


def _lint(code, text, title):
    return engine.lint(PageContext(title, text), select=[code])


@pytest.mark.parametrize(
    "code,case_dir", CASES, ids=[f"{c}-{d.name}" for c, d in CASES]
)
def test_fixture(code, case_dir):
    text = (case_dir / "input.wiki").read_text()
    title_file = case_dir / "title.txt"
    title = title_file.read_text().strip() if title_file.is_file() else case_dir.name
    expected = [
        line.strip()
        for line in (case_dir / "expected.txt").read_text().splitlines()
        if line.strip()
    ]
    findings = _lint(code, text, title)
    actual = [f"{f.code}:{f.line(text)}" for f in findings]
    assert actual == expected, (
        f"findings mismatch:\n  expected: {expected}\n  actual:   {actual}\n"
        + "\n".join(f"  {f.code}:{f.line(text)} {f.message}" for f in findings)
    )

    fixed_file = case_dir / "fixed.wiki"
    if fixed_file.is_file():
        fixed, _, _ = fixer.apply_fixes(
            text, lambda t: _lint(code, t, title), unsafe=True
        )
        assert fixed == fixed_file.read_text()
        refixed, applied, _ = fixer.apply_fixes(
            fixed, lambda t: _lint(code, t, title), unsafe=True
        )
        assert refixed == fixed and not applied, "fix is not idempotent"


def test_fixture_dirs_are_valid():
    for rule_dir in FIXTURES.iterdir():
        if rule_dir.name.startswith("."):
            continue
        assert (
            rule_dir.name in REGISTRY
        ), f"fixture dir for unknown rule {rule_dir.name}"


def test_every_rule_has_fixtures():
    missing = [
        code
        for code, rule in REGISTRY.items()
        if not rule.requires_index and not (FIXTURES / code).is_dir()
    ]
    assert not missing, f"rules without fixtures: {missing}"
