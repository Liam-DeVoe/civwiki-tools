from collections import Counter
from typing import Callable

from civlint.types import Applicability, Finding

MAX_ITERATIONS = 5


def _apply_round(
    text: str, findings: list[Finding], unsafe: bool
) -> tuple[str, Counter]:
    """Apply as many non-overlapping eligible fixes as possible, in one pass."""
    applied: Counter = Counter()
    taken: list[tuple[int, int]] = []
    edits = []
    for f in findings:
        if f.fix is None:
            continue
        if f.fix.applicability is Applicability.UNSAFE and not unsafe:
            continue
        span = f.fix.span()
        # closed-interval overlap: a zero-width edit (insertion) at position P
        # must conflict with a span starting or ending at P, or the two could
        # interleave and corrupt text. Deferred fixes apply in a later round.
        if any(s <= span[1] and span[0] <= e for s, e in taken):
            continue
        taken.append(span)
        edits.extend(f.fix.edits)
        applied[f.code] += 1
    for edit in sorted(edits, key=lambda e: (e.start, e.end), reverse=True):
        text = text[: edit.start] + edit.replacement + text[edit.end :]
    return text, applied


def apply_fixes(
    text: str,
    lint_text: Callable[[str], list[Finding]],
    unsafe: bool = False,
) -> tuple[str, Counter, list[Finding]]:
    """Fix `text` to a fixpoint.

    lint_text must build a fresh context and return findings for the text it
    is given; it is re-run after each round so that cascading fixes apply and
    offsets stay valid. Returns (fixed text, counts of applied fixes by code,
    remaining findings of the fixed text).
    """
    total: Counter = Counter()
    for _ in range(MAX_ITERATIONS):
        findings = lint_text(text)
        new_text, applied = _apply_round(text, findings, unsafe)
        if not applied or new_text == text:
            return text, total, findings
        total += applied
        text = new_text
    return text, total, lint_text(text)
