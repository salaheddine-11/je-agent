"""P2-M1/M2 tests: schemas, sanitize_for_llm, phase-gated loop (§4, §9.5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import adversarial_text as adv  # noqa: E402

from je_agent.hashing import canonical_json  # noqa: E402
from je_agent.llm.provider import FakeProvider, ProviderResponse  # noqa: E402
from je_agent.llm.sanitize import (  # noqa: E402
    ADVISORY_CAPTION,
    PII_PATTERNS_VERSION,
    SANITIZE_POLICY_VERSION,
    Sanitizer,
    luhn_valid,
)
from je_agent.phase_runner import PhaseFailure, run_phase  # noqa: E402
from je_agent.schemas import RiskPlan, TriageReport  # noqa: E402
from je_agent.store import RunStore  # noqa: E402


# ---------------------------------------------------------------------------
# §9.5 sanitizer suite
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", adv.INJECTION_ATTEMPTS)
def test_injection_attempts_are_detected(text):
    s = Sanitizer()
    out = s.sanitize_field("description", text)
    assert out.injection_suspected, f"NOT detected in: {text!r}"


@pytest.mark.parametrize("text", adv.BENIGN_LEDGER_PHRASES)
def test_benign_ledger_phrases_pass_clean(text):
    s = Sanitizer()
    out = s.sanitize_field("description", text)
    assert not out.injection_suspected, f"FALSE POSITIVE on: {text!r} -> {out.events}"


@pytest.mark.parametrize("text", adv.INJECTION_ATTEMPTS + adv.BENIGN_LEDGER_PHRASES)
def test_delimiter_cannot_be_broken(text):
    s = Sanitizer()
    out = s.sanitize_field("description", text)
    # exactly one pair of delimiters; inner escapes neutralized
    assert out.rendered.count("<untrusted_data>") == 1
    assert out.rendered.startswith("<untrusted_data>")
    assert out.rendered.endswith("</untrusted_data>")
    inner = out.rendered[len("<untrusted_data>"):-len("</untrusted_data>")]
    assert "</untrusted_data>" not in inner


def test_pii_scrubbing_all_classes():
    s = Sanitizer()
    compound = adv.PII_SAMPLES["compound"]
    out = s.sanitize_field("description", compound)
    assert "[EMAIL]" in out.rendered and "@" not in out.rendered.split("<untrusted_data>")[1].split("[EMAIL]")[0]
    assert "[IBAN]" in out.rendered
    assert "[PAYMENT_CARD]" in out.rendered
    counts = dict(s.scrub_counts)
    assert counts.get("pii:email") == 1 and counts.get("pii:iban") == 1


def test_card_luhn_boundary():
    valid = adv.PII_SAMPLES["payment_card_valid"].replace(" ", "")
    invalid = adv.PII_SAMPLES["payment_card_invalid"].replace(" ", "")
    assert luhn_valid(valid)
    assert not luhn_valid(invalid)

    s = Sanitizer()
    out_valid = s.sanitize_field("d", f"card {valid}")
    out_invalid = s.sanitize_field("d", f"ref {invalid}")
    assert "[PAYMENT_CARD]" in out_valid.rendered       # Luhn-valid scrubbed
    assert invalid in out_invalid.rendered              # invalid number NOT scrubbed (Y4)


def test_ssn_iban_phone_email_individually():
    s = Sanitizer()
    for key, placeholder in [("ssn", "[SSN]"), ("iban", "[IBAN]"),
                             ("phone_us", "[PHONE]"), ("email", "[EMAIL]")]:
        raw = adv.PII_SAMPLES[key]
        if key == "iban":   # module provides 'MA...' plus FR; use first token
            raw = raw.split()[0]
        out = s.sanitize_field("description", f"payment ref {raw}")
        assert placeholder in out.rendered, f"{key}: {out.rendered}"
        assert raw not in out.rendered


def test_redaction_terms_exact_literal_only():
    s = Sanitizer(redaction_terms=["Project Atlas"])
    out = s.sanitize_field("description", "Payment for Project Atlas phase 2")
    assert "[REDACTED_TERM_1]" in out.rendered and "Project Atlas" not in out.rendered
    # non-exact inflection untouched (minimal-necessary scrubbing Y4)
    out2 = s.sanitize_field("description", "Atlasian legacy system retired")
    assert "Atlasian" in out2.rendered


def test_originals_survive_scrubbing_is_rendering_only():
    original = adv.PII_SAMPLES["compound"]
    s = Sanitizer()
    rendered = s.sanitize_field("description", original).rendered
    assert original != rendered and "@" in original      # input object unchanged


def test_version_pins_present_and_stable_shape():
    for v in (SANITIZE_POLICY_VERSION, PII_PATTERNS_VERSION):
        parts = v.split(".")
        assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_accounting_context_survives_scrubbing():
    s = Sanitizer(redaction_terms=["Project Atlas"])
    text = ("Accrual reversal per policy for Project Atlas vendor invoice "
            "contact ap@client.example approved by CFO")
    out = s.sanitize_field("description", text)
    for word in ("Accrual", "reversal", "vendor invoice", "CFO"):
        assert word in out.rendered, f"over-redaction destroyed context: {out.rendered}"


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------


def test_riskplan_rejects_unknown_rule():
    with pytest.raises(ValidationError):
        RiskPlan.model_validate({
            "selections": [{"rule": "made_up", "params": {}, "rationale": "x"}],
            "focus_areas": ["f"], "plan_note": "n"})


def test_triagereport_enforces_universe_field():
    ok = TriageReport.model_validate({
        "assessments": [{"entry_ref": "E1", "rationale_concern": "low",
                         "concern_note": "n", "recommended_action": "accept_flag",
                         "priority": 3}],
        "universe_covered": 1, "rubric_version": "v1", "summary": "s"})
    assert ok.universe_covered == 1
    with pytest.raises(ValidationError):
        TriageReport.model_validate({"assessments": [], "universe_covered": 0,
                                     "rubric_version": "v1", "summary": "s"})


# ---------------------------------------------------------------------------
# phase-gated loop
# ---------------------------------------------------------------------------


PLAN_OK = {
    "selections": [
        {"rule": "manual_entries", "params": {}, "rationale": "core"},
        {"rule": "round_amounts", "params": {"multiple": 1000}, "rationale": "round"},
    ],
    "focus_areas": ["period-end"], "plan_note": "ok",
}


def _validator(artifact):
    return []   # accept everything referentially


def _store(tmp_path):
    return RunStore(tmp_path / "rs.sqlite")


def test_phase_happy_path_submits_once(tmp_path):
    provider = FakeProvider([
        {"tool": "chatter_tool", "args": {}},
        {"tool": "submit_risk_plan", "args": PLAN_OK},
    ], fallback_tool="submit_risk_plan")
    res = run_phase("RISK_PLAN", provider, "sys", "brief",
                    tools_spec=[], submit_tool="submit_risk_plan",
                    artifact_model=RiskPlan, referential_validator=_validator,
                    store=_store(tmp_path), run_id="r1")
    assert res.artifact.selections[0].rule == "manual_entries"
    assert res.turns_used == 2


def test_phase_repair_retry_then_success(tmp_path):
    bad = {**PLAN_OK, "selections": [{**PLAN_OK["selections"][0], "rule": "bogus"}]}
    provider = FakeProvider([
        {"tool": "submit_risk_plan", "args": bad},          # schema-invalid
        {"tool": "submit_risk_plan", "args": PLAN_OK},      # repaired
    ])
    res = run_phase("RISK_PLAN", provider, "sys", "brief", [],
                    "submit_risk_plan", RiskPlan, _validator)
    assert res.artifact is not None and res.turns_used == 2


def test_phase_double_failure_is_loud(tmp_path):
    bad = {**PLAN_OK, "selections": [{**PLAN_OK["selections"][0], "rule": "bogus"}]}
    provider = FakeProvider([{"tool": "submit_risk_plan", "args": bad}] * 5)
    with pytest.raises(PhaseFailure, match="twice"):
        run_phase("RISK_PLAN", provider, "sys", "brief", [],
                  "submit_risk_plan", RiskPlan, _validator)


def test_referential_repair_cycle(tmp_path):
    provider = FakeProvider([
        {"tool": "submit_risk_plan", "args": PLAN_OK},      # schema ok, refs bad
        {"tool": "submit_risk_plan", "args": PLAN_OK},
    ])
    calls = {"n": 0}

    def ref_check(_a):
        calls["n"] += 1
        return ["entry E999 not in universe"] if calls["n"] == 1 else []

    res = run_phase("RISK_PLAN", provider, "sys", "brief", [],
                    "submit_risk_plan", RiskPlan, ref_check)
    assert res.artifact is not None and calls["n"] == 2


def test_same_tool_tripwire(tmp_path):
    provider = FakeProvider([{"tool": "loop_forever", "args": {}}] * 10)
    with pytest.raises(PhaseFailure, match="tripwire"):
        run_phase("X", provider, "s", "b", [], "submit_x",
                  RiskPlan, _validator)


def test_turn_budget_exhaustion(tmp_path):
    class Chatty(FakeProvider):
        def complete(self, system, turns, tools_spec):
            return ProviderResponse(stop_reason="end_turn", text="...")

    with pytest.raises(PhaseFailure, match="budget"):
        run_phase("X", Chatty([]), "s", "b", [], "submit_x", RiskPlan, _validator)
