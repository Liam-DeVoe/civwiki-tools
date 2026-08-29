from civlint import rules as _rules  # noqa: F401  (imports register all rules)
from civlint.context import PageContext
from civlint.types import REGISTRY, Finding, selected_codes


def lint(
    ctx: PageContext,
    select: list[str] | None = None,
    ignore: list[str] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    for code in selected_codes(select, ignore):
        rule = REGISTRY[code]
        if any(code.startswith(s) for s in ctx.suppressed):
            continue
        if rule.requires_index and ctx.index is None:
            continue
        findings.extend(rule.func(ctx))
    findings.sort(key=lambda f: (f.start, f.code))
    return findings
