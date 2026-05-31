"""redact.py — mask secret-shaped substrings in free text + a backstop for annotations.

This is NOT the primary defense for code. The Python parser's primary defense is
*not emitting string VALUES at all* — a string/bytes literal renders as its type
(`API_KEY = <str>`), so a hardcoded credential in a constant / default arg / dict
can never reach a summary. Detecting "is this string a secret?" by name or shape is
a losing arms race (an adversarial review broke every such regex), so we don't rely
on it for code.

These patterns guard the two places a raw string still reaches a summary:
  1. a string embedded in a type annotation (e.g. `Literal['...']`), and
  2. the extracted text of PDF / DOCX documents (free prose — "hide all strings"
     is not possible there).
They are quote- and length-independent on purpose: the v0.1.2 attempt anchored on a
closing quote, so a truncated value slipped past. Case-insensitive keyword matching
uses scoped `(?i:...)` groups (a bare leading `(?i)` would force-flag the whole
pattern and Python rejects `(?i)` mid-pattern).
"""
from __future__ import annotations

import re

# Provider / structured token shapes (case-sensitive prefixes) + key=value secrets
# (case-insensitive keyword via scoped (?i:...)). No surrounding-quote dependence.
_STRUCTURED = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{8,}"                              # Anthropic
    r"|sk-[A-Za-z0-9_-]{16,}"                                # OpenAI
    r"|(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{8,}"           # Stripe
    r"|gh[pousr]_[A-Za-z0-9]{16,}"                           # GitHub
    r"|glpat-[A-Za-z0-9_-]{16,}"                             # GitLab
    r"|AKIA[0-9A-Z]{12,}|ASIA[0-9A-Z]{12,}"                  # AWS access key id
    r"|xox[baprs]-[A-Za-z0-9-]{8,}"                          # Slack token
    r"|AIza[0-9A-Za-z_-]{20,}"                               # Google
    r"|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"          # SendGrid
    r"|hooks\.slack\.com/services/[A-Za-z0-9/]+"             # Slack webhook URL
    r"|discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+"  # Discord webhook
    r"|eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}(?:\.[A-Za-z0-9_-]+)?"  # JWT (2+ segs)
    r"|-----BEGIN[ A-Z]*PRIVATE KEY-----"                    # PEM private key
    r"|[A-Za-z][\w.+-]*://[^\s/:@]+:[^\s/@]+@"               # URL with user:pass@
    # key=value / key: value  (connection strings, env dumps, config prose). The
    # (?!<) skips our own rendered type placeholders (`api_key=<str>`) so the
    # backstop never re-mangles a value the parser already hid.
    r"|(?i:password|passwd|pwd|passphrase|secret|api[_-]?key|access[_-]?key"
    r"|account[_-]?key|shared[_-]?access[_-]?key|client[_-]?secret|auth[_-]?token"
    r"|access[_-]?token|refresh[_-]?token|session[_-]?token|private[_-]?key)"
    r"\s*[=:]\s*(?!<[a-z]+>)[^\s;,'\"]{4,}"
    # scheme-prefixed auth tokens:  Bearer <t> / Basic <b64> / SSWS <t>
    r"|(?i:bearer|basic|ssws)\s+[A-Za-z0-9+/=._-]{8,}")

# Generic long opaque blob (hex key / base64). Quote-independent. FP-prone on prose,
# so callers pass opaque=False for documents.
_OPAQUE = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


def redact_secrets(text: str, *, opaque: bool = True) -> str:
    """Replace secret-shaped substrings with `<redacted>`. `opaque=False` skips the
    generic long-blob rule (used on document prose to avoid mangling normal text)."""
    if not text:
        return text
    out = _STRUCTURED.sub("<redacted>", text)
    if opaque:
        out = _OPAQUE.sub("<redacted>", out)
    return out
