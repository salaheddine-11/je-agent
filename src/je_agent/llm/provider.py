"""LLM provider abstraction (DESIGN §2.3 seam).

Phase 2 ships FakeProvider (deterministic, scripted) + AnthropicProvider.
Every provider returns the same envelope so the phase runner never knows the
difference; failure degrades to loud phase error, never silent fabrication.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])


@dataclass
class ProviderResponse:
    stop_reason: str                     # tool_use | end_turn | max_tokens | error
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = ""


@dataclass
class Turn:
    """One conversation turn as stored/replayed by the runner.

    role: user | assistant | tool_results.
    An assistant turn may carry tool_calls; a tool_results turn carries the
    matching results (and optionally content — e.g. a repair instruction riding
    on the same message so protocols that require strict alternation stay happy).
    """
    role: str                            # user | assistant | tool_results
    content: str = ""
    tool_results: list[dict] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    model_id: str

    @abstractmethod
    def complete(self, system: str, turns: list[Turn], tools_spec: list[dict]) -> ProviderResponse:
        """One completion over the conversation. Implementations must be stateless."""


class FakeProvider(LLMProvider):
    """Scripted provider for tests: replans a queue of canned responses.

    Each queued item is either a ProviderResponse or a dict-shaped tool call:
        {"tool": "submit_risk_plan", "args": {...}}
    When the queue empties, the provider emits a deterministic submit fallback if
    one was registered via `fallback_tool`, else end_turn.
    """

    def __init__(self, script: list[dict | ProviderResponse],
                 fallback_tool: str | None = None,
                 model_id: str = "fake/deterministic"):
        self.script = list(script)
        self.fallback_tool = fallback_tool
        self.model_id = model_id
        self.calls: list[tuple[str, list[Turn]]] = []   # observation hook for tests

    def complete(self, system: str, turns: list[Turn], tools_spec: list[dict]) -> ProviderResponse:
        self.calls.append((system, [t for t in turns]))
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, ProviderResponse):
                return item
            return ProviderResponse(
                stop_reason="tool_use",
                tool_calls=[ToolCall(name=item["tool"], arguments=item.get("args", {}))],
                model_id=self.model_id,
            )
        if self.fallback_tool:
            # minimal valid args: empty object — validators decide if acceptable
            return ProviderResponse(
                stop_reason="tool_use",
                tool_calls=[ToolCall(name=self.fallback_tool, arguments={})],
                model_id=self.model_id,
            )
        return ProviderResponse(stop_reason="end_turn", text="", model_id=self.model_id)


class AnthropicProvider(LLMProvider):
    """Real Claude via the Anthropic SDK. Tool use drives phase submission."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514",
                 max_tokens: int = 4096, temperature: float = 0.0,
                 base_url: str | None = None):
        import os

        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ValueError("AnthropicProvider requires ANTHROPIC_API_KEY")
        self.model_id = f"anthropic/{model}"
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature   # pinned to 0 for logged judgment
        self._base_url = base_url

    @staticmethod
    def _to_anthropic_tools(tools_spec: list[dict]) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools_spec
        ]

    @staticmethod
    def _to_messages(turns: list[Turn]) -> list[dict]:
        """Internal turns -> Anthropic messages.

        - user turns -> user text message
        - assistant turns (with tool_calls) -> assistant content with tool_use blocks
          (the API requires tool_results to reference these ids)
        - tool_results turns -> user message of tool_result blocks (+ any content,
          e.g. a repair note riding along)
        """
        messages: list[dict] = []
        for t in turns:
            if t.role == "user":
                messages.append({"role": "user", "content": [{"type": "text", "text": t.content}]})
            elif t.role == "assistant":
                blocks: list[dict] = []
                if t.content:
                    blocks.append({"type": "text", "text": t.content})
                for c in t.tool_calls:
                    blocks.append({"type": "tool_use", "id": c.id, "name": c.name,
                                   "input": c.arguments})
                if blocks:
                    messages.append({"role": "assistant", "content": blocks})
            elif t.role == "tool_results":
                inner: list[dict] = []
                for r in t.tool_results:
                    payload = r.get("result")
                    inner.append({
                        "type": "tool_result",
                        "tool_use_id": r["tool_use_id"],
                        "content": json.dumps(payload) if not isinstance(payload, str) else payload,
                    })
                if t.content:
                    inner.append({"type": "text", "text": t.content})
                if inner:
                    messages.append({"role": "user", "content": inner})
        return messages

    def complete(self, system: str, turns: list[Turn], tools_spec: list[dict]) -> ProviderResponse:
        import anthropic

        client = (anthropic.Anthropic(api_key=self._api_key, base_url=self._base_url)
                  if self._base_url else anthropic.Anthropic(api_key=self._api_key))
        resp = client.messages.create(
            model=self._model,
            system=system,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            tools=self._to_anthropic_tools(tools_spec),
            messages=self._to_messages(turns),
        )
        out = ProviderResponse(
            stop_reason=resp.stop_reason or "end_turn",
            input_tokens=getattr(getattr(resp, "usage", None), "input_tokens", 0),
            output_tokens=getattr(getattr(resp, "usage", None), "output_tokens", 0),
            model_id=f"anthropic/{resp.model}",
        )
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                out.text += block.text
            elif getattr(block, "type", "") == "tool_use":
                out.tool_calls.append(ToolCall(id=block.id, name=block.name,
                                               arguments=dict(block.input)))
        return out


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI Chat Completions protocol — covers OpenAI, Azure OpenAI, Ollama (/v1),
    vLLM, LM Studio, OpenRouter, and every other /chat/completions server.

    Config: base_url (e.g. http://localhost:11434/v1), model name as served by the
    endpoint; api_key optional for local servers (a placeholder works).
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 max_tokens: int = 4096, temperature: float = 0.0):
        import os

        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "not-needed")
        self._max_tokens = max_tokens
        self._temperature = temperature
        self.model_id = f"openai-compatible/{model}@{self._base_url}"

    # -- translation ---------------------------------------------------------

    @staticmethod
    def _to_oai_tools(tools_spec: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools_spec
        ]

    @staticmethod
    def _to_messages(system: str, turns: list[Turn]) -> list[dict]:
        """Internal turns -> OpenAI messages.

        - leading system message
        - assistant w/ tool_calls -> role=assistant + tool_calls array
        - tool_results -> one role=tool message PER result (each tool_call must be
          answered by its own tool message); a repair/content note rides on the
          next user turn instead of inside a tool message.
        """
        msgs: list[dict] = [{"role": "system", "content": system}]
        pending_notes: list[str] = []
        for t in turns:
            if t.role == "user":
                content = "\n".join([*pending_notes, t.content]) if pending_notes else t.content
                msgs.append({"role": "user", "content": content})
                pending_notes.clear()
            elif t.role == "assistant":
                m: dict = {"role": "assistant", "content": t.content or None}
                if t.tool_calls:
                    m["tool_calls"] = [{
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    } for c in t.tool_calls]
                msgs.append(m)
            elif t.role == "tool_results":
                for r in t.tool_results:
                    payload = r.get("result")
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": r["tool_use_id"],
                        "content": json.dumps(payload) if not isinstance(payload, str) else payload,
                    })
                if t.content:
                    pending_notes.append(t.content)
        if pending_notes:
            msgs.append({"role": "user", "content": "\n".join(pending_notes)})
        return msgs

    # -- request -----------------------------------------------------------------

    def complete(self, system: str, turns: list[Turn], tools_spec: list[dict]) -> ProviderResponse:
        import re as _re
        import requests

        body: dict = {
            "model": self._model,
            "messages": self._to_messages(system, turns),
            "temperature": self._temperature,
        }
        if tools_spec:
            body["tools"] = self._to_oai_tools(tools_spec)

        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
        url = f"{self._base_url}/chat/completions"

        # free-tier RPM pacing: never send more than one request per min_interval
        now = time.monotonic()
        since = now - getattr(self.__class__, "_last_request_ts", 0.0)
        min_interval = float(os.environ.get("JEAGENT_RPM_INTERVAL", "3.5"))
        if since < min_interval:
            time.sleep(min_interval - since)
        self.__class__._last_request_ts = time.monotonic()

        resp = None
        last_error_body = ""
        for attempt in range(8):                     # patient enough for 60s windows
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=600)
            except requests.exceptions.ConnectionError:
                if attempt == 7:
                    raise
                time.sleep(min(45.0, (2 ** attempt) * 3))
                continue

            if resp.status_code not in (429,) and resp.status_code < 500:
                break

            last_error_body = resp.text[:800]
            # honor server hint ("Please retry in 15.28s") else exponential
            hinted = _re.search(r"retry in\s+([0-9.]+)\s*s", last_error_body, _re.IGNORECASE)
            retry_after = resp.headers.get("Retry-After")
            if hinted:
                delay = float(hinted.group(1)) + 2.0
            elif (retry_after or "").replace(".", "", 1).isdigit():
                delay = float(retry_after)
            else:
                delay = min(90.0, (2 ** attempt) * 8)
            time.sleep(delay)

        if resp is None:
            raise RuntimeError("provider request never completed (retries exhausted)")
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]

        out = ProviderResponse(
            stop_reason={"tool_calls": "tool_use", "stop": "end_turn",
                         "length": "max_tokens"}.get(choice.get("finish_reason"),
                                                     choice.get("finish_reason") or "end_turn"),
            text=msg.get("content") or "",
            input_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            output_tokens=data.get("usage", {}).get("completion_tokens", 0),
            model_id=f"openai-compatible/{data.get('model', self._model)}",
        )
        for tc in msg.get("tool_calls") or []:
            args_raw = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
            except json.JSONDecodeError:
                args = {}     # malformed JSON -> empty args; schema validation rejects loudly
            out.tool_calls.append(ToolCall(id=tc.get("id") or uuid.uuid4().hex[:16],
                                           name=tc["function"]["name"], arguments=args))
        return out
