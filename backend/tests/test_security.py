from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decksoundpad.security import TOKEN_REDACTION, redact_token


class SecurityTests(unittest.TestCase):
    def test_token_redaction(self) -> None:
        token = "abc123SECRETtoken456789"
        value = (
            f"http://deck:8787/?token={token} "
            f"Authorization: Bearer {token} Bearer {token}"
        )
        redacted = redact_token(value, token)
        self.assertNotIn(token, redacted)
        self.assertIn(TOKEN_REDACTION, redacted)


if __name__ == "__main__":
    unittest.main()
