"""
Keep secrets out of anything a user (or a log line) can see (SCRUM-27:
"Stack traces and secrets are not exposed").

`redact_secrets` masks bearer tokens, JWTs, API keys, passwords and the
credentials inside connection URLs. `RedactingFilter` applies it to every
log record so a secret that slips into an exception message is masked in
the logs too.
"""

from __future__ import annotations

import logging
import re

MASK = "[REDACTED]"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # scheme://user:password@host  -> scheme://[REDACTED]@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@"), rf"\1{MASK}@"),
    # Authorization: Bearer xxx
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}"), rf"\1 {MASK}"),
    # JSON Web Tokens
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"), MASK),
    # Common API key formats (OpenAI/Anthropic sk-, GitHub ghp_, Slack xox*, AWS AKIA)
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16})\b"), MASK),
    # key=value / key: value for secret-looking names
    (re.compile(
        r"(?i)\b([A-Z0-9_]*(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key)[A-Z0-9_]*)"
        r"([\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&}]+)"
    ), rf"\1\2{MASK}"),
)


def redact_secrets(text: str | None) -> str:
    if not text:
        return text or ""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Masks secrets in log messages and their arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # malformed record; leave it alone
            return True
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


def install_log_redaction() -> None:
    """Attach the filter to the root and uvicorn handlers (idempotent)."""
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        targets = list(logger.handlers) or [logger]
        for target in targets:
            if not any(isinstance(f, RedactingFilter) for f in target.filters):
                target.addFilter(RedactingFilter())
