"""Token-based artifact opening: scoped, expiring, HMAC — never the API key."""

from __future__ import annotations

import time

from je_agent.api import _issue_token, _verify_token  # noqa: E402


def test_token_valid_for_matching_scoped_pair():
    t = _issue_token("RUN_A", "report.pdf")
    assert _verify_token("RUN_A", "report.pdf", t) is True


def test_token_rejects_wrong_run_or_artifact():
    t = _issue_token("RUN_A", "report.pdf")
    assert _verify_token("RUN_B", "report.pdf", t) is False  # wrong run
    assert _verify_token("RUN_A", "report.html", t) is False  # wrong artifact


def test_token_does_not_leak_key():
    # token is tiny + opaque; never contains the API key
    t = _issue_token("RUN_A", "report.pdf")
    assert "test-key-123" not in t
    assert len(t) < 120


def test_token_expires():
    # shrink TTL via env, then confirm expiry is honored
    import os
    old = os.environ.get("JEAGENT_ARTIFACT_TTL")
    os.environ["JEAGENT_ARTIFACT_TTL"] = "-1"  # already expired
    try:
        t = _issue_token("RUN_A", "report.pdf", ttl=-1)
        assert _verify_token("RUN_A", "report.pdf", t) is False
    finally:
        if old is None:
            os.environ.pop("JEAGENT_ARTIFACT_TTL", None)
        else:
            os.environ["JEAGENT_ARTIFACT_TTL"] = old


def test_malformed_token_rejected():
    assert _verify_token("RUN_A", "report.pdf", "") is False
    assert _verify_token("RUN_A", "report.pdf", "nonsense") is False
    assert _verify_token("RUN_A", "report.pdf", "1.badbadbad") is False
