"""EngagementConfig — frozen engagement configuration (DESIGN §3.2, incl. v1.6 Z1/Z3/Z7).

Config is loaded from YAML, validated by pydantic, and frozen verbatim into the run
folder as part of the reproducibility identity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Canonical rule order (v1.6 Z2). Single source of truth; the executor re-sorts
# any RiskPlan into this order before running.
# ---------------------------------------------------------------------------

CANONICAL_RULE_ORDER: tuple[str, ...] = (
    "manual_entries",
    "period_end",
    "round_amounts",
    "date_divergence",
    "entry_splitting",
    "balance_check",
    "unusual_users",
    "unusual_pairs",
    "reversals",
    "high_risk_system_pairs",
)

RuleName = Literal[
    "manual_entries",
    "period_end",
    "round_amounts",
    "unusual_pairs",
    "reversals",
    "unusual_users",
    "balance_check",
    "date_divergence",
    "entry_splitting",
    "high_risk_system_pairs",
]


class Materiality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: float = Field(gt=0)
    performance: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("performance")
    @classmethod
    def _performance_below_overall(cls, v: float, info) -> float:
        overall = info.data.get("overall")
        if overall is not None and v > overall:
            raise ValueError(f"performance materiality ({v}) must be <= overall ({overall})")
        return v


class ColumnMap(BaseModel):
    """Maps source headers -> canonical names only. Optional columns enable rules."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    posting_date: str | None = None
    account: str | None = None
    username: str | None = None
    description: str | None = None
    source_doc: str | None = None
    entry_ref: str | None = None           # optional explicit journal-entry id
    entry_type: str | None = None          # v1.6 Z3 tier 1: explicit manual/system column
    document_date: str | None = None       # v1.2 V2
    entry_created_date: str | None = None  # v1.2 V2


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str = "generic"
    amount_column: str                     # B2 mandatory
    currency_column: str | None = None     # v1.2 V1
    column_map: ColumnMap = Field(default_factory=ColumnMap)
    extract_through_date: str | None = None  # v1.6 Z1: declared last covered posting date (YYYY-MM-DD)


class RiskContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high_risk_users: list[str] = Field(default_factory=list)
    pressures: list[str] = Field(default_factory=list)
    fraud_risk_factors: list[str] = Field(default_factory=list)


class LlmPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["zero_retention", "pseudonymized"] = "zero_retention"
    provider_agreement_ref: str | None = None
    pseudonymize_usernames: bool = False
    pii_scrubbing: bool = True             # v1.4 X5
    pii_patterns: list[Literal["ssn", "iban", "payment_card", "email", "phone"]] = Field(
        default_factory=lambda: ["ssn", "iban", "payment_card", "email", "phone"]
    )
    redaction_terms: list[str] = Field(default_factory=list)


class RepresentativeSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    size: int = Field(default=25, gt=0)
    strata: list[Literal["month", "entry_type", "account_group", "amount_band"]] = Field(
        default_factory=lambda: ["month", "entry_type"]
    )


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_universe_size: int = Field(default=200, gt=0)
    overflow_policy: Literal["pause", "stratify", "document_limitation"] = "pause"
    pack_size: int = Field(default=20, gt=0, le=200)
    fallback_top_n_per_currency: int = Field(default=20, gt=0)
    force_include_currencies: list[str] = Field(default_factory=list)      # v1.5 Y8
    minimum_entries_per_currency: int = Field(default=0, ge=0)             # v1.5 Y8


class RuleParams(BaseModel):
    """Auditor-tunable rule parameters. All defaults per DESIGN §3.2 + v1.6."""

    model_config = ConfigDict(extra="forbid")

    period_end_window_days: int = 5
    period_end_post_close_days: int = 10
    round_number_multiple: float = 1000
    round_number_min_amount: float = 10000
    balance_tolerance: float = 0.01        # A4
    reversal_match_days: int = 10
    reversal_amount_tolerance: float = 0.01
    unusual_user_rare_threshold: int = 5
    exclude_flagged_from_baseline: bool = True   # C3
    doc_posting_gap_days: int = 5          # v1.2 V2
    split_window_days: int = 14            # v1.2 V3
    split_min_count: int = 3               # v1.2 V3
    split_threshold: float = 10000         # v1.6 Z7 — independent parameter
    split_just_below_ratio: float = 0.9    # "just below" = >= ratio*split_threshold (precision guard)
    unusual_account_share: float = 0.10    # high_risk_system_pairs: account unusual when share < this
    min_baseline_count: int = 1
    manual_entry_types: list[str] = Field(  # v1.6 Z3 tier 1
        default_factory=lambda: ["manual", "man", "m"]
    )
    system_user_patterns: list[str] = Field(  # v1.6 Z3 tier 2
        default_factory=lambda: [
            "SAP*", "WF-BATCH", "BATCH*", "SYSTEM", "AUTO*", "JOB*", "INTERFACE*", "*_RFC",
        ]
    )


class Reviewer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)  # C5 declared identity


class EngagementConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_\-]+$")
    period_end: str  # YYYY-MM-DD
    materiality: Materiality
    source: Source
    risk_context: RiskContext = Field(default_factory=RiskContext)
    llm_privacy: LlmPrivacy = Field(default_factory=LlmPrivacy)
    fx_rates: dict[str, float] = Field(default_factory=dict)
    representative_sample: RepresentativeSample = Field(default_factory=RepresentativeSample)
    review: Review = Field(default_factory=Review)
    rule_params: RuleParams = Field(default_factory=RuleParams)
    reviewer: Reviewer


# ---------------------------------------------------------------------------
# Load / freeze
# ---------------------------------------------------------------------------


def load_config(path: Path) -> EngagementConfig:
    """Load and validate an engagement YAML config."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EngagementConfig.model_validate(raw)


def freeze_config(config: EngagementConfig) -> tuple[str, str]:
    """Canonical serialization for freezing + hashing (reproducibility identity).

    Returns (canonical_yaml_text, sha256_hex).
    """
    payload = config.model_dump(mode="json")
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return yaml.safe_dump(payload, sort_keys=True, allow_unicode=True), digest


def canonical_rule_sort(rule_names: list[str]) -> list[str]:
    """Sort a RiskPlan's selections into canonical execution order (v1.6 Z2).

    Unknown rule names are rejected here; the executor re-sorts regardless of the
    order the plan listed them in.
    """
    known = set(CANONICAL_RULE_ORDER)
    unknown = [r for r in rule_names if r not in known]
    if unknown:
        raise ValueError(f"unknown rule name(s): {sorted(unknown)}")
    return sorted(set(rule_names), key=CANONICAL_RULE_ORDER.index)
