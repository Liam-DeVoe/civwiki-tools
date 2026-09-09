from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from civlint.context import PageContext


class Applicability(Enum):
    # SAFE fixes are applied by --fix. UNSAFE fixes require --unsafe-fixes.
    # A finding with no Fix at all is report-only.
    SAFE = "safe"
    UNSAFE = "unsafe"


@dataclass
class Edit:
    """A replacement of text[start:end] with `replacement`."""

    start: int
    end: int
    replacement: str


@dataclass
class Fix:
    edits: list[Edit]
    applicability: Applicability

    def span(self) -> tuple[int, int]:
        return (
            min(e.start for e in self.edits),
            max(e.end for e in self.edits),
        )


@dataclass
class Finding:
    code: str
    message: str
    # offsets into the page's raw wikitext
    start: int
    end: int
    fix: Fix | None = None

    def line(self, text: str) -> int:
        return text.count("\n", 0, self.start) + 1


RuleFunc = Callable[["PageContext"], Iterator[Finding]]


@dataclass
class Rule:
    code: str
    summary: str
    func: RuleFunc
    doc: str
    requires_index: bool


REGISTRY: dict[str, Rule] = {}


def rule(code: str, summary: str, *, requires_index: bool = False):
    """Register a rule function.

    The function receives a PageContext and yields Findings. Rules with
    requires_index=True are skipped when no site index is loaded.
    """

    def decorator(func: RuleFunc) -> RuleFunc:
        assert code not in REGISTRY, f"duplicate rule code {code}"
        REGISTRY[code] = Rule(
            code=code,
            summary=summary,
            func=func,
            doc=(func.__doc__ or summary).strip(),
            requires_index=requires_index,
        )
        return func

    return decorator


def selected_codes(select: list[str] | None, ignore: list[str] | None) -> list[str]:
    """Resolve --select/--ignore prefixes against the registry, ruff-style.

    A rule is selected if any `select` entry is a prefix of its code (or
    select is empty, meaning everything), and no `ignore` entry is.
    """
    codes = []
    for code in sorted(REGISTRY):
        if select and not any(code.startswith(s) for s in select):
            continue
        if ignore and any(code.startswith(i) for i in ignore):
            continue
        codes.append(code)
    return codes
