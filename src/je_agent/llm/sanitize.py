"""sanitize_for_llm — the single deterministic component at the LLM boundary (§4.10).

Four jobs, in order: DELIMIT, SCAN (injection), SCRUB (PII), RECORD.
Never mutates stored data — only transforms the LLM-bound rendering. Carries its
own reproducibility identity (v1.5 Y1): policy/scanner/pattern versions are pinned
in the run record; a sanitizer change changes run identity.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Versioned identity (Y1) — bump on any behavioral change
# ---------------------------------------------------------------------------

SANITIZE_POLICY_VERSION = "1.0.0"
INJECTION_SCANNER_VERSION = "1.0.0"
PII_PATTERNS_VERSION = "1.0.0"

UNTRUSTED_OPEN = "<untrusted_data>"
UNTRUSTED_CLOSE = "</untrusted_data>"

# ---------------------------------------------------------------------------
# Injection scanner (Y2 precision discipline: model-directed patterns only;
# benign accounting verbs never match alone)
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    # instruction override: ignore/disregard/forget ... any qualifier ... rules
    (r"(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|your\s+|their\s+)?"
     r"(?:previous\s+|prior\s+|above\s+|earlier\s+|existing\s+|other\s+|all\s+|hidden\s+)*"
     r"(?:instructions?|rules?|constraints?|directives?|guardrails?|safety)", "instruction_override"),
    (r"new\s+(?:instructions?|directive|directives?|rules?)\s*:", "instruction_override"),
    (r"(?:you\s+are\s+now|from\s+now\s+on)[^.;]{0,40}(?:unrestricted|unfiltered|free|jailbroken)", "identity_override"),
    (r"\[\s*(?:system|assistant|developer)\s*\]", "fake_role_marker"),
    (r"<<\s*/?\s*sys\s*>>", "fake_role_marker"),
    (r"<\|\s*(?:im_start|system|endoftext)\s*\|>", "fake_role_marker"),
    (r"\bassistant\s*:", "fake_role_marker"),
    (r"</?\s*untrusted_data\s*>", "delimiter_escape"),
    (r"\]\]\s*>", "delimiter_escape"),
    (r"(?:mark|classify|rate|flag|approve|accept)\s+(?:this|the)\s+(?:entry|transaction|item)"
     r"[^.;]{0,50}?\b(?:low|no|none|minimal)\s+concern", "outcome_manipulation"),
    (r"(?:rate|classify)\s+[^.;]{0,30}\bas\b\s+(?:low concern|not suspicious|safe)", "outcome_manipulation"),
    (r"auto-?approve|approve\s+silently|silently\s+approve", "outcome_manipulation"),
    (r"skip\s+(?:the\s+)?(?:reviewer|review|approval)\s+queue", "outcome_manipulation"),
    (r"(?:must\s+be\s+approved|must\s+approve\s+(?:every|all)|approve\s+(?:every|all)\s+"
     r"(?:journal\s+)?entr)", "outcome_manipulation"),
    (r"(?:confirm|verified|verified by)[^.;]{0,30}\bit\s+is\s+(?:low concern|not suspicious|safe)", "outcome_manipulation"),
    (r"granted\s+by\s+(?:model|system|admin)", "fake_role_marker"),
    # exfiltration / probing
    (r"(?:reveal|print|repeat|show|display|echo)\s+[^.;]{0,40}"
     r"(?:system\s+prompt|instructions?|hidden\s+configuration)", "exfiltration"),
    (r"(?:export|send|transmit|exfiltrate|leak)\s+[^.;]{0,60}"
     r"(?:configuration|instructions?|system\s+prompt|credentials|api[- ]?keys?)", "exfiltration"),
    (r"(?:developer|administrator|admin)\s+(?:directive|override|message)\s*:", "context_probe"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE | re.MULTILINE), tag) for p, tag in _INJECTION_PATTERNS]


@dataclass
class SanitizationEvent:
    field_name: str
    kind: str            # delimited | injection_suspected | pii_scrubbed | control_chars_escaped
    detail: str
    count: int = 1


@dataclass
class SanitizedValue:
    rendered: str
    events: list[SanitizationEvent] = field(default_factory=list)

    @property
    def injection_suspected(self) -> bool:
        return any(e.kind == "injection_suspected" for e in self.events)


# ---------------------------------------------------------------------------
# PII scrubbing classes (X5) — structured identifiers + Luhn for cards (Y4)
# ---------------------------------------------------------------------------

def luhn_valid(digits: str) -> bool:
    digits = digits.replace(" ", "").replace("-", "")
    if not digits.isdigit() or len(digits) < 12:
        return False
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_PII_RES = {
    "ssn": (
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[SSN]",
        None,
    ),
    "iban": (
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
        "[IBAN]",
        None,
    ),
    "payment_card": (
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        "[PAYMENT_CARD]",
        luhn_valid,
    ),
    "email": (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "[EMAIL]",
        None,
    ),
    "phone": (
        re.compile(r"(?<!\w)(?:\+\d{1,3}[-. ]?)?(?:\(\d{2,4}\)[- ]?)?\d{3}[-. ]\d{3,4}(?:[-. ]\d{2,4})?(?!\w)"),
        "[PHONE]",
        None,
    ),
}

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\u2028\u2029]")


class Sanitizer:
    """One instance per engagement; redaction_terms_hash pins the term list (Y1)."""

    def __init__(self,
                 pii_scrubbing: bool = True,
                 pii_patterns: list[str] | None = None,
                 redaction_terms: list[str] | None = None):
        self.pii_scrubbing = pii_scrubbing
        self.pii_patterns = pii_patterns or ["ssn", "iban", "payment_card", "email", "phone"]
        self.redaction_terms = [t for t in (redaction_terms or []) if t]
        self.redaction_terms_hash = hashlib.sha256(
            json.dumps(sorted(self.redaction_terms)).encode("utf-8")).hexdigest()
        self.scrub_counts: dict[str, int] = {}

    # -- public API ---------------------------------------------------------

    def sanitize_field(self, field_name: str, value: str) -> SanitizedValue:
        out = SanitizedValue(rendered=value or "")
        if not value:
            return out

        # 1) escape control characters so data cannot break rendering (X1)
        ctrl = _CONTROL_CHARS_RE.findall(out.rendered)
        if ctrl:
            out.rendered = _CONTROL_CHARS_RE.sub(
                lambda m: f"\\u{ord(m.group(0)):04x}", out.rendered)
            out.events.append(SanitizationEvent(
                field_name, "control_chars_escaped",
                f"{len(ctrl)} control char(s) escaped", len(ctrl)))

        # 2) scan BEFORE scrubbing (attacks may ride inside would-be PII)
        for rx, tag in _COMPILED:
            m = rx.search(out.rendered)
            if m:
                out.events.append(SanitizationEvent(
                    field_name, "injection_suspected", f"pattern {tag}: {m.group(0)[:60]!r}"))
                break   # one warning per entry suffices to raise salience

        # 3) PII scrub (X5/Y4)
        if self.pii_scrubbing:
            for cls in self.pii_patterns:
                rx, placeholder, validator = _PII_RES[cls]
                def _sub(m: re.Match) -> str:
                    token = m.group(0)
                    if validator is not None and not validator(token):
                        return token          # e.g., card failing Luhn stays (Y4 minimal)
                    key = f"pii:{cls}"
                    self.scrub_counts[key] = self.scrub_counts.get(key, 0) + 1
                    out.events.append(SanitizationEvent(
                        field_name, "pii_scrubbed", f"{cls} -> {placeholder.strip('[]')}"))
                    return placeholder
                out.rendered = rx.sub(_sub, out.rendered)

        # 4) literal redaction terms (client codenames), exact matches only
        for i, term in enumerate(self.redaction_terms, start=1):
            if term in out.rendered:
                n = out.rendered.count(term)
                out.rendered = out.rendered.replace(term, f"[REDACTED_TERM_{i}]")
                self.scrub_counts[f"term:{term}"] = self.scrub_counts.get(f"term:{term}", 0) + n
                out.events.append(SanitizationEvent(
                    field_name, "pii_scrubbed", f"redaction term #{i} x{n}", n))

        # 5) delimit LAST: neutralize BOTH tag forms inside the value, then wrap
        safe_inner = re.sub(r"</?\s*untrusted_data\s*>",
                            lambda m: m.group(0).replace("<", "\\u003c").replace(">", "\\u003e"),
                            out.rendered)
        if safe_inner != out.rendered:
            out.events.append(SanitizationEvent(
                field_name, "control_chars_escaped", "delimiter-like tag neutralized"))
        out.rendered = f"{UNTRUSTED_OPEN}{safe_inner}{UNTRUSTED_CLOSE}"
        return out

    def render_pack(self, entries: list[dict], fields: list[str]) -> tuple[str, list[SanitizationEvent]]:
        """Render a triage pack grouped BY DOCUMENT: the entry_ref appears exactly
        once as 'document <ref>' followed by its lines, so the model cannot mistake
        a per-line label for a separate assessable id."""
        all_events: list[SanitizationEvent] = []
        docs: dict[str, list[dict]] = {}
        order: list[str] = []
        for e in entries:
            ref = str(e.get("entry_ref"))
            if ref not in docs:
                docs[ref] = []
                order.append(ref)
            docs[ref].append(e)

        blocks = []
        for i, ref in enumerate(order, start=1):
            lines = docs[ref]
            first = lines[0]
            head = [
                f"DOCUMENT {i} of {len(order)} — entry_ref: {ref}",
                f"  rules_hit: {first.get('rules_hit')}",
                f"  flag_reasons:",
            ]
            sv_flags = self.sanitize_field("flag_reasons", str(first.get("flag_reasons") or ""))
            for ln in sv_flags.rendered.splitlines():
                head.append(f"    {ln}")
            all_events.extend(sv_flags.events)
            blocks.append("\n".join(head))
            for e in lines:
                body = [f"  - line_no: {e.get('line_no')}"]
                for k in ("posting_date", "account", "username", "amount", "currency"):
                    if e.get(k) is not None:
                        body.append(f"      {k}: {e[k]}")
                for fname in fields:
                    if fname == "flag_reasons":
                        continue
                    v = e.get(fname)
                    sv = self.sanitize_field(fname, str(v) if v else "")
                    body.append(f"      {fname}: {sv.rendered}")
                    all_events.extend(sv.events)
                blocks.append("\n".join(body))
        return "\n".join(blocks), all_events


ADVISORY_CAPTION = ("Injection suspicion is an advisory technical signal. It does "
                    "not by itself prove fraud. Evaluate the accounting substance.")
