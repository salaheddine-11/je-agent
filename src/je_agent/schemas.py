"""LLM artifact schemas (DESIGN §4.4) — validated, referentially checked.

These are the ONLY shapes an LLM may produce. Anything outside them is discarded;
validation failure allows exactly one repair retry, then loud phase failure.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RuleName = Literal[
    "manual_entries", "period_end", "round_amounts",
    "unusual_pairs", "reversals", "unusual_users", "balance_check",
    "date_divergence", "entry_splitting", "high_risk_system_pairs",
]

StatisticalTool = Literal["benford", "isolation_forest"]


class RuleSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: RuleName
    params: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)


class RiskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selections: list[RuleSelection] = Field(min_length=1)
    statistical: list[StatisticalTool] = Field(default_factory=list)
    focus_areas: list[str] = Field(min_length=1)
    plan_note: str = Field(min_length=1)


class EntryAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_ref: str = Field(min_length=1)
    rationale_concern: Literal["none", "low", "medium", "high"]
    concern_note: str = Field(min_length=1)
    recommended_action: Literal["inspect", "accept_flag", "override"]
    priority: int = Field(ge=1, le=5)


class SuggestedFollowup(BaseModel):
    """v1.2 V4 — recorded and surfaced; NEVER auto-executed."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["additional_rule", "param_adjustment", "population_question"]
    description: str = Field(min_length=1)


class TriageReport(BaseModel):
    """Aggregated across packs; universe coverage validated post-merge (A2)."""

    model_config = ConfigDict(extra="forbid")

    assessments: list[EntryAssessment] = Field(min_length=1)
    universe_covered: int = Field(ge=0)
    suggested_followups: list[SuggestedFollowup] = Field(default_factory=list)
    pack_ids: list[str] = Field(default_factory=list)
    rubric_version: str = Field(min_length=1)
    consistency_warnings: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class NarrativeFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    value: str
    source: str


class Narrative(BaseModel):
    """C1: every numeral claim must cite a fact key; validator checks citations."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    sections: list[dict[str, str]] = Field(min_length=1)  # {heading, text} with [fact:key] cites
    cited_fact_keys: list[str] = Field(min_length=1)
