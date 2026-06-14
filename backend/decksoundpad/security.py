from __future__ import annotations

import re
import secrets

from .paths import AppPaths, ensure_app_dirs


TOKEN_BYTES = 32
TOKEN_REDACTION = "REDACTED"


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def load_or_create_token(paths: AppPaths) -> str:
    ensure_app_dirs(paths)
    if paths.token_file.exists():
        return paths.token_file.read_text(encoding="utf-8").strip()
    return write_new_token(paths)


def write_new_token(paths: AppPaths) -> str:
    token = generate_token()
    paths.token_file.write_text(f"{token}\n", encoding="utf-8")
    paths.token_file.chmod(0o600)
    return token


def token_matches(expected: str, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return secrets.compare_digest(expected, provided)


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
