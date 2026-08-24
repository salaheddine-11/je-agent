"""Provider protocol conformance (§2.3 seam): Anthropic + OpenAI-compatible.

Verifies both providers translate the SAME internal turn sequence into their
correct wire formats — assistant tool_use replay, tool_result correlation ids,
strict role alternation — without any network access.
"""

from __future__ import annotations

import json

import pytest

from je_agent.llm.provider import (
    AnthropicProvider,
    FakeProvider,
    OpenAICompatibleProvider,
    ProviderResponse,
    ToolCall,
    Turn,
)
from je_agent.phase_runner import run_phase
from je_agent.schemas import RiskPlan


TOOLS_SPEC = [
    {
        "name": "submit_risk_plan",
        "description": "Submit the validated plan",
        "parameters": {"type": "object", "properties": {}},
    }
]


def _conversation() -> list[Turn]:
    """The canonical multi-turn shape the phase runner produces."""
    call = ToolCall(id="tc_123", name="view_flag_table",
                    arguments={"table": "flags_manual_entries"})
    return [
        Turn(role="user", content="Plan the procedures."),
        Turn(role="assistant", content="", tool_calls=[call]),
        Turn(role="tool_results",
             tool_results=[{"tool_use_id": "tc_123",
                            "result": {"status": "ok", "rows": 42}}],
             content="Note: also check period-end."),
    ]


# ---------------------------------------------------------------------------
# Anthropic mapping
# ---------------------------------------------------------------------------


def test_anthropic_message_mapping_shape():
    msgs = AnthropicProvider._to_messages(_conversation())

    assert msgs[0] == {"role": "user",
                       "content": [{"type": "text", "text": "Plan the procedures."}]}

    # assistant turn replays the tool_use block with the SAME id
    a = msgs[1]
    assert a["role"] == "assistant"
    assert a["content"][0]["type"] == "tool_use"
    assert a["content"][0]["id"] == "tc_123"
    assert a["content"][0]["name"] == "view_flag_table"

    # tool_results -> user message of tool_result blocks referencing that id,
    # with the repair/content note appended as text
    u = msgs[2]
    assert u["role"] == "user"
    assert u["content"][0]["type"] == "tool_result"
    assert u["content"][0]["tool_use_id"] == "tc_123"
    assert u["content"][1] == {"type": "text", "text": "Note: also check period-end."}


def test_anthropic_tool_spec_translation():
    spec = AnthropicProvider._to_anthropic_tools(TOOLS_SPEC)
    assert spec[0]["name"] == "submit_risk_plan"
    assert "input_schema" in spec[0]


# ---------------------------------------------------------------------------
# OpenAI-compatible mapping
# ---------------------------------------------------------------------------


def test_openai_message_mapping_shape():
    provider = OpenAICompatibleProvider(base_url="http://localhost:11434/v1",
                                        model="llama3.1:70b")
    msgs = provider._to_messages("You are an audit planner.", _conversation())

    assert msgs[0] == {"role": "system", "content": "You are an audit planner."}
    assert msgs[1] == {"role": "user", "content": "Plan the procedures."}

    # assistant carries structured tool_calls array
    a = msgs[2]
    assert a["role"] == "assistant"
    assert a["tool_calls"][0]["id"] == "tc_123"
    assert a["tool_calls"][0]["function"]["name"] == "view_flag_table"
    assert json.loads(a["tool_calls"][0]["function"]["arguments"]) == \
        {"table": "flags_manual_entries"}

    # EACH tool result gets its own role=tool message with matching call id
    t = msgs[3]
    assert t["role"] == "tool"
    assert t["tool_call_id"] == "tc_123"
    assert json.loads(t["content"])["rows"] == 42

    # pending note rides on the next user message
    assert msgs[-1]["role"] == "user"
    assert "period-end" in msgs[-1]["content"]


def test_openai_tool_spec_translation():
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    spec = provider._to_oai_tools(TOOLS_SPEC)
    assert spec[0]["type"] == "function"
    assert spec[0]["function"]["name"] == "submit_risk_plan"
    assert "parameters" in spec[0]["function"]


# ---------------------------------------------------------------------------
# end-to-end through the phase runner with a scripted OpenAI-style exchange
# ---------------------------------------------------------------------------


class ScriptedOpenAIServer(FakeProvider):
    """Simulates what OpenAICompatibleProvider.complete would return."""

    def complete(self, system, turns, tools_spec):
        # first call: model answers with a submit carrying valid args
        return ProviderResponse(
            stop_reason="tool_use",
            tool_calls=[ToolCall(id="call_abc", name="submit_risk_plan", arguments={
                "selections": [{"rule": "manual_entries", "params": {}, "rationale": "core"}],
                "focus_areas": ["period-end"], "plan_note": "ok",
            })],
            model_id="openai-compatible/llama3.1",
        )


def test_openai_style_exchange_drives_phase_to_completion(tmp_path):
    res = run_phase("RISK_PLAN", ScriptedOpenAIServer([]), "sys",
                    "brief", TOOLS_SPEC, "submit_risk_plan", RiskPlan,
                    lambda a: [])
    assert res.artifact is not None
    assert res.artifact.selections[0].rule == "manual_entries"


PLAN_OK = {
    "selections": [{"rule": "manual_entries", "params": {}, "rationale": "core"}],
    "focus_areas": ["period-end"], "plan_note": "ok",
}


def test_repair_cycle_produces_protocol_valid_history():
    """After a validation failure, history must be replayable by BOTH protocols:
    every tool_result references a preceding assistant tool_use id."""
    from je_agent.llm.provider import FakeProvider as FP

    bad = {"selections": [{"rule": "bogus_rule", "params": {}, "rationale": "x"}],
           "focus_areas": ["f"], "plan_note": "n"}
    provider = FP([
        {"tool": "submit_risk_plan", "args": bad},
        {"tool": "submit_risk_plan", "args": PLAN_OK},
    ])

    captured: dict = {}

    class Spy(FP):
        def complete(self, system, turns, tools_spec):
            captured["turns"] = list(turns)
            return super().complete(system, turns, tools_spec)

    spy = Spy.__new__(Spy)
    spy.script = provider.script
    spy.fallback_tool = None
    spy.model_id = "fake"
    spy.calls = []

    res = run_phase("RISK_PLAN", spy, "sys", "brief", [], "submit_risk_plan",
                    RiskPlan, lambda a: [])
    assert res.artifact is not None

    # verify protocol invariants on the final turn history
    turns = captured["turns"]
    open_ids = set()
    for t in turns:
        if t.role == "assistant":
            for c in t.tool_calls:
                open_ids.add(c.id)
        elif t.role == "tool_results":
            for r in t.tool_results:
                assert r["tool_use_id"] in open_ids, \
                    f"tool_result {r['tool_use_id']} has no matching assistant tool_use"
                open_ids.discard(r["tool_use_id"])
