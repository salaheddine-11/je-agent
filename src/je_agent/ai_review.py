"""AI reviewer (Feature 2) — produces review decisions from triage assessments.

When `review.mode = "ai"`, the pipeline has no human in the loop for the review
stage. This module converts the LLM triage output into hash-chained decisions
with an explicit, audit-defensible mapping and a confidence floor:

  recommended_action accept_flag + concern in {none, low}  -> accept (conf high)
  recommended_action accept_flag + concern in {medium}     -> accept (conf med) if >= ai_min_confidence
  recommended_action inspect OR concern high              -> inspect
  anything below ai_min_confidence                       -> ai_default_decision

Every decision reasons from the model's own concern_note, so the AI reviewer's
judgment is transparent and traceable — never a bare accept. The reviewer
identity is "ai-reviewer" and reviewer_source "ai", which the report renders as
an AI-authored review (never presented as human judgment).
"""
from __future__ import annotations

from .review import DecisionInput, submit_decisions
from .schemas import TriageReport


def _decision_for(a, cfg) -> tuple[str, str, float]:
    """Map a triage assessment to (decision, reason, confidence)."""
    concern = a.rationale_concern
    action = a.recommended_action
    note = a.concern_note.strip() or "no additional detail"

    # high concern always inspect, regardless of recommended action
    if concern == "high":
        return ("inspect", f"High concern: {note}", 0.95)

    if action == "accept_flag":
        if concern in ("none", "low"):
            return ("accept", f"Low concern, model recommends accept: {note}", 0.9)
        if concern == "medium":
            return ("accept", f"Model recommends accept (medium concern): {note}", 0.7)
        return ("inspect", f"accept-flagged but concern {concern}: {note}", 0.6)

    if action == "inspect":
        return ("inspect", f"Model recommends substantive testing: {note}", 0.85)

    if action == "override":
        # override = flagged but model thinks it's a false positive -> accept
        return ("accept", f"Model flags as false positive (override): {note}", 0.8)

    return (cfg.review.ai_default_decision, f"No clear recommendation ({action}); default: {note}", 0.5)


def run_ai_review(store, config, universe, triage: TriageReport) -> dict:
    """Generate + record AI review decisions for every universe entry.

    Returns {"recorded": int, "decisions": {entry_ref: decision}, "bypasses": int}.
    """
    triage_by_ref = {a.entry_ref: a for a in triage.assessments}
    inputs: list[DecisionInput] = []
    summary: dict[str, str] = {}
    n_bypass = 0

    for e in universe.entries:
        ref = e["entry_ref"]
        a = triage_by_ref.get(ref)
        if a is None:
            # no triage assessment for this entry (shouldn't happen when coverage
            # is complete) — conservative inspect with an explicit reason.
            inputs.append(DecisionInput(entry_ref=ref, decision="inspect",
                                        reason="No triage assessment available; conservative substantive testing."))
            summary[ref] = "inspect"
            continue

        decision, reason, confidence = _decision_for(a, config)
        if confidence < config.review.ai_min_confidence:
            decision = config.review.ai_default_decision
            n_bypass += 1
        inputs.append(DecisionInput(entry_ref=ref, decision=decision, reason=reason))
        summary[ref] = decision

    recorded = submit_decisions(store, config.run_id, "ai-reviewer", "ai", inputs)
    return {"recorded": recorded, "decisions": summary, "bypasses": n_bypass}
