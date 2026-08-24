"""Provider connection diagnostics — the engine behind any 'Test connection' button.

Works against ANY OpenAI-compatible /chat/completions endpoint (Gemini's
generativelanguage.googleapis.com/v1beta/openai, Ollama, vLLM, Azure, OpenRouter...)
by sending a minimal completion and reporting a structured verdict.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class ConnectionTestResult:
    ok: bool
    base_url: str
    model: str
    latency_ms: int
    reply: str | None = None
    model_id: str | None = None
    error_kind: str | None = None       # auth | model_not_found | timeout | http | unexpected
    error_detail: str | None = None

    def summary(self) -> str:
        if self.ok:
            return (f"[green]✔ CONNECTED[/] {self.model} @ {self.base_url} "
                    f"({self.latency_ms} ms) — replied: {self.reply!r}")
        kind = self.error_kind or "error"
        return (f"[red]✗ FAILED[/] {self.model} @ {self.base_url} "
                f"({self.latency_ms} ms) [{kind}] {self.error_detail}")


def classify_error(status_code: int | None, body: str) -> str:
    text = (body or "").lower()
    if status_code in (401, 403) or "api key" in text or "unauthorized" in text or "permission" in text:
        return "auth"
    if status_code == 404 or "model" in text and ("not found" in text or "does not exist" in text or "not supported" in text):
        return "model_not_found"
    if status_code == 429 or "quota" in text or "rate limit" in text:
        return "rate_limited"
    return f"http_{status_code}" if status_code else "network"


def test_openai_compatible_connection(
    base_url: str,
    model: str,
    api_key: str | None = None,
    timeout_s: int = 60,
) -> ConnectionTestResult:
    """Send a 5-token ping through the exact provider class production uses."""
    started = time.perf_counter()
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model,
        "messages": [{"role": "user",
                      "content": "Reply with exactly the two characters: OK"}],
        "max_tokens": 200,
        "temperature": 0.0,
    }
    import requests

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout_s)
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            return ConnectionTestResult(
                ok=False, base_url=base_url, model=model, latency_ms=latency,
                error_kind=classify_error(resp.status_code, resp.text[:400]),
                error_detail=resp.text[:400])
        data = resp.json()
        choice = data["choices"][0]
        reply = (choice["message"].get("content") or "").strip()
        served_model = data.get("model", model)
        # tool-support probe: the phase runner REQUIRES function calling
        tools_ok, tools_note = _probe_tool_support(
            url, headers, model, api_key, timeout_s)
        result = ConnectionTestResult(
            ok=True, base_url=base_url, model=model, latency_ms=latency,
            reply=reply[:80], model_id=f"openai-compatible/{served_model}")
        result.tool_support = tools_ok          # type: ignore[attr-defined]
        result.tools_note = tools_note          # type: ignore[attr-defined]
        return result
    except requests.exceptions.Timeout:
        return ConnectionTestResult(False, base_url, model,
                                    int((time.perf_counter() - started) * 1000),
                                    error_kind="timeout",
                                    error_detail=f"no response within {timeout_s}s")
    except requests.exceptions.ConnectionError as e:
        return ConnectionTestResult(False, base_url, model,
                                    int((time.perf_counter() - started) * 1000),
                                    error_kind="network",
                                    error_detail=str(e)[:300])
    except Exception as e:  # noqa: BLE001
        return ConnectionTestResult(False, base_url, model,
                                    int((time.perf_counter() - started) * 1000),
                                    error_kind="unexpected", error_detail=str(e)[:300])


def _probe_tool_support(url: str, headers: dict, model: str,
                        api_key: str | None, timeout_s: int) -> tuple[bool, str]:
    """Verify the endpoint accepts OpenAI-style tools — mandatory for phase submission."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Call the ping tool."}],
        "max_tokens": 100,
        "tools": [{
            "type": "function",
            "function": {
                "name": "ping",
                "description": "Acknowledges connectivity.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }],
        "tool_choice": "auto",
    }
    import requests

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout_s)
        if resp.status_code != 200:
            return False, f"tools rejected: HTTP {resp.status_code}: {resp.text[:200]}"
        msg = resp.json()["choices"][0]["message"]
        if msg.get("tool_calls"):
            name = msg["tool_calls"][0]["function"]["name"]
            return True, f"function calling OK (called {name})"
        return True, "tools accepted (model chose not to call)"
    except Exception as e:  # noqa: BLE001
        return False, f"tools probe failed: {str(e)[:200]}"
