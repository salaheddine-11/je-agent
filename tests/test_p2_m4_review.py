"""P2-M4 tests: review store — hash chains (W7/Z6), DQ acks (X3/Y5), dispositions (Y2)."""

from __future__ import annotations

import pytest

from je_agent.review import (
    ReviewError,
    acknowledge_dq_warnings,
    effective_decisions,
    record_injection_disposition,
    submit_decisions,
    verify_all_chains,
)
from je_agent.store import RunStore


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "rs.sqlite")


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------


def test_decisions_chain_and_effective_resolution(store):
    submit_decisions(store, "r1", "jdoe", "declared", [
        DecisionInput := __import__("je_agent.review", fromlist=["DecisionInput"]).DecisionInput(
            entry_ref="E1", decision="inspect"),
        __import__("je_agent.review", fromlist=["DecisionInput"]).DecisionInput(
            entry_ref="E2", decision="accept"),
    ])
    # supersede E1 with an override (+ reason)
    from je_agent.review import DecisionInput

    submit_decisions(store, "r1", "jdoe", "declared",
                     [DecisionInput(entry_ref="E1", decision="override",
                                    reason="substance-based: routine accrual")])

    eff = effective_decisions(store, "r1")
    assert eff["E1"]["decision"] == "override"
    assert eff["E1"]["reason"] == "substance-based: routine accrual"
    assert eff["E2"]["decision"] == "accept"

    report = verify_all_chains(store, "r1")
    assert report["review_decisions"].intact
    assert report["review_decisions"].length == 3


def test_override_without_reason_rejected(store):
    from je_agent.review import DecisionInput

    with pytest.raises(ReviewError, match="mandatory reason"):
        submit_decisions(store, "r1", "jdoe", "declared",
                         [DecisionInput(entry_ref="E9", decision="override")])


def test_tampered_decision_breaks_chain_at_exact_row(store, tmp_path):
    from je_agent.review import DecisionInput

    submit_decisions(store, "r1", "jdoe", "declared", [
        DecisionInput(entry_ref="A", decision="accept"),
        DecisionInput(entry_ref="B", decision="accept"),
        DecisionInput(entry_ref="C", decision="inspect"),
    ])
    # simulate tampering directly in the DB
    store.con.execute("UPDATE review_decisions SET decision='override' WHERE entry_ref='B'")
    store.con.commit()

    rep = verify_all_chains(store, "r1")["review_decisions"]
    assert not rep.intact
    assert rep.first_bad_index == 1


# ---------------------------------------------------------------------------
# DQ acknowledgments
# ---------------------------------------------------------------------------


def test_dq_ack_critical_raises_limitation(store):
    accepted, limitations = acknowledge_dq_warnings(store, "r1", "jdoe", "declared", [
        {"warning_id": "dq_unbalanced_docs", "scope": "document_type=SA",
         "reason": "statistical postings expected unbalanced"},
    ])
    assert accepted == 1
    assert limitations and "critical" in limitations[0]
    assert verify_all_chains(store, "r1")["dq_acknowledgments"].intact


def test_non_dismissible_class_refused(store):
    for wid in ("dq_duplicate_extract", "dq_extract_shortfall_declared"):
        with pytest.raises(ReviewError, match="NON-DISMISSIBLE"):
            acknowledge_dq_warnings(store, "r1", "jdoe", "declared",
                                    [{"warning_id": wid, "reason": "try anyway"}])


def test_dq_ack_requires_reason(store):
    with pytest.raises(ReviewError, match="reason"):
        acknowledge_dq_warnings(store, "r1", "jdoe", "declared",
                                [{"warning_id": "dq_missing_fields"}])


# ---------------------------------------------------------------------------
# injection dispositions
# ---------------------------------------------------------------------------


def test_injection_disposition_annotates_never_deletes(store):
    rid = record_injection_disposition(store, "r1", "jdoe", "declared",
                                       "JE001/description", "false_positive",
                                       "ledger language, not model-directed")
    assert rid > 0
    n = store.con.execute(
        "SELECT count(*) FROM injection_dispositions WHERE event_ref='JE001/description'"
    ).fetchone()[0]
    assert n == 1          # recorded; nothing deleted anywhere
    assert verify_all_chains(store, "r1")["injection_dispositions"].intact


def test_invalid_disposition_rejected(store):
    with pytest.raises(ReviewError, match="invalid disposition"):
        record_injection_disposition(store, "r1", "jdoe", "declared",
                                     "JE001", "delete_it", "no")
