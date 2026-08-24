"""Phase-gated LLM loop (DESIGN §4.2, §4.6).

Each phase is a bounded session that MUST end by calling its submit tool:
  - turn budget 12; same-tool-call tripwire at 3; one validate_or_repair retry.
Everything the model says outside the submit call is discarded; arguments become
the artifact only after schema + referential validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from .llm.provider import LLMProvider, ProviderResponse, ToolCall, Turn
from .store import RunStore

T = TypeVar("T", bound=BaseModel)

TURN_BUDGET = 12
SAME_TOOL_TRIPWIRE = 3


class PhaseFailure(RuntimeError):
    def __init__(self, phase: str, reason: str):
        super().__init__(f"[{phase}] {reason}")
        self.phase = phase
        self.reason = reason


@dataclass
class PhaseResult:
    phase: str
    artifact: BaseModel | None
    turns_used: int
    llm_outputs: list[dict] = field(default_factory=list)


def run_phase(
    phase_name: str,
    provider: LLMProvider,
    system_prompt: str,
    user_brief: str,
    tools_spec: list[dict],
    submit_tool: str,
    artifact_model: type[T],
    referential_validator: Callable[[T], list[str]],
    store: RunStore | None = None,
    run_id: str | None = None,
    context_hash: str = "",
) -> PhaseResult:
    """Drive one bounded phase session to a validated artifact."""
    turns: list[Turn] = [Turn(role="user", content=user_brief)]
    tool_call_counts: dict[str, int] = {}
    llm_outputs: list[dict] = []
    repaired = False

    for turn_no in range(1, TURN_BUDGET + 1):
        resp: ProviderResponse = provider.complete(system_prompt, turns, tools_spec)

        if store and run_id:
            _record_llm_output(store, run_id, phase_name, turn_no, context_hash,
                               user_brief, resp)

        if resp.stop_reason != "tool_use" or not resp.tool_calls:
            turns.append(Turn(role="user",
                              content=f"You must end the phase by calling {submit_tool}. "
                                      "Anything else is discarded."))
            continue

        call: ToolCall = resp.tool_calls[0]
        tool_call_counts[call.name] = tool_call_counts.get(call.name, 0) + 1

        # tripwire: identical non-submit call repeated -> escalate
        if call.name != submit_tool and tool_call_counts[call.name] >= SAME_TOOL_TRIPWIRE:
            raise PhaseFailure(phase_name,
                               f"tripwire: {call.name} repeated {tool_call_counts[call.name]}x")

        if call.name == submit_tool:
            try:
                artifact = artifact_model.model_validate(call.arguments)
            except ValidationError as e:
                if repaired:
                    raise PhaseFailure(phase_name, f"validation failed twice: {e}") from e
                repaired = True
                # replay the assistant's submit attempt, then answer it with a repair note
                turns.append(Turn(role="assistant", content=resp.text,
                                  tool_calls=[call]))
                turns.append(Turn(role="tool_results", tool_results=[{
                    "tool_use_id": call.id,
                    "result": {"status": "validation_error", "errors": str(e)[:2000]},
                }], content=(f"Your {submit_tool} arguments failed validation. Fix the "
                             "errors and resubmit — this is your only repair retry.")))
                continue

            problems = referential_validator(artifact)
            if problems:
                if repaired:
                    raise PhaseFailure(
                        phase_name, f"referential validation failed twice: {problems}")
                repaired = True
                turns.append(Turn(role="assistant", content=resp.text,
                                  tool_calls=[call]))
                turns.append(Turn(role="tool_results", tool_results=[{
                    "tool_use_id": call.id,
                    "result": {"status": "referential_error",
                               "problems": problems[:20]},
                }], content=("Referential validation rejected your submission. Reference "
                             "ONLY entries/rules present in tool results and resubmit.")))
                continue

            return PhaseResult(phase_name, artifact, turn_no, llm_outputs)

        # ordinary (non-submit) tool call inside the phase: record + ack generically
        turns.append(Turn(role="assistant", content=resp.text, tool_calls=[call]))
        turns.append(Turn(role="tool_results", tool_results=[{
            "tool_use_id": call.id,
            "result": {"status": "ok", "note": "observed; results live in DuckDB tables"},
        }]))

    raise PhaseFailure(phase_name, f"turn budget {TURN_BUDGET} exhausted")


def _record_llm_output(store: RunStore, run_id: str, phase: str, turn: int,
                       context_hash: str, request_delta: str,
                       resp) -> None:
    con = store.con
    con.execute(
        """INSERT INTO llm_outputs (run_id, phase, turn, ts, context_hash,
           request_json, response_json, stop_reason, input_tokens, output_tokens, model_id)
           VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)""",
        [run_id, phase, turn, context_hash, request_delta[:2000],
         json.dumps({"text": resp.text[-4000:], "tools": [
             {"name": c.name, "args": c.arguments} for c in resp.tool_calls]}),
         resp.stop_reason, resp.input_tokens, resp.output_tokens, resp.model_id],
    )
    store.con.commit()
