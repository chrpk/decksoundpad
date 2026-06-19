from __future__ import annotations

import re


TOKEN_REDACTION = "REDACTED"


def redact_token(value: str, token: str | None = None) -> str:
    redacted = value
    if token:
        redacted = redacted.replace(token, TOKEN_REDACTION)
    redacted = re.sub(r"([?&]token=)[^&\s]+", rf"\1{TOKEN_REDACTION}", redacted)
    redacted = re.sub(
        r"(Authorization:\s*Bearer\s+)[^\s]+",
        rf"\1{TOKEN_REDACTION}",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"(Bearer\s+)[A-Za-z0-9_.~+/=-]{16,}",
        rf"\1{TOKEN_REDACTION}",
        redacted,
    )
    return redacted
