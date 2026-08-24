"""Offline tests for connection diagnostics (error classification, result shape)."""

from __future__ import annotations

from je_agent.llm.diagnostics import ConnectionTestResult, classify_error


def test_auth_errors():
    assert classify_error(401, '{"error": "invalid API key"}') == "auth"
    assert classify_error(403, "permission denied") == "auth"
    assert classify_error(400, "API key not valid") == "auth"


def test_model_not_found():
    assert classify_error(404, "model not found") == "model_not_found"
    assert classify_error(404, "models/gemini-2.0-flash is no longer available") == "model_not_found"
    assert classify_error(400, "The model does not exist") == "model_not_found"


def test_rate_limit_and_fallback():
    assert classify_error(429, "quota exceeded") == "rate_limited"
    assert classify_error(500, "boom") == "http_500"
    assert classify_error(None, "") == "network"


def test_result_summary_shapes():
    ok = ConnectionTestResult(True, "u", "m", 100, reply="OK")
    assert "CONNECTED" in ok.summary()
    bad = ConnectionTestResult(False, "u", "m", 100,
                               error_kind="auth", error_detail="bad key")
    assert "FAILED" in bad.summary() and "auth" in bad.summary()
