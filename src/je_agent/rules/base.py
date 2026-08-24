"""Rule result / error envelopes (DESIGN §5.2)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuleResult:
    rule: str
    flagged: int
    output_table: str
    notes: str | None = None
    seed: str | None = None          # statistical rules record theirs here
    extra: dict = field(default_factory=dict)


@dataclass
class RuleError:
    rule: str
    code: str                        # bad_table | bad_column | bad_param | internal
    message: str

    def __bool__(self) -> bool:      # an error is falsy in "did everything pass" checks
        return False
