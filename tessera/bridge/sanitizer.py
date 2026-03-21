"""Metadata Sanitization Filter — ts-spec-009 §7.

Mandatory preprocessing before any metadata reaches an LLM prompt.
Applies five transformations in order:
  1. Length truncation
  2. Control character removal
  3. Newline normalization
  4. Injection pattern stripping
  5. Unicode normalization and bidi override removal
"""

from __future__ import annotations

import re
import unicodedata

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\bignore\s+(all\s+)?(previous\s+)?instructions?\b"),
    re.compile(r"(?i)^(system|assistant|human)\s*:", re.MULTILINE),
    re.compile(r"\{\{.*?\}\}", re.DOTALL),
]

_BIDI_OVERRIDES = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_MULTI_NEWLINE = re.compile(r"\n{2,}")

MAX_FIELD_LENGTH = 500


class SanitizationFilter:
    """Apply the five-rule sanitization pipeline to a single metadata value."""

    def __init__(self, max_length: int = MAX_FIELD_LENGTH) -> None:
        self._max_length = max_length

    def sanitize(self, value: str) -> str:
        """Return a sanitized copy of *value*."""
        # 1. Truncate.
        value = value[: self._max_length]

        # 2. Remove control characters (keep \n and \t).
        value = "".join(
            c
            for c in value
            if c in "\n\t" or (0x20 <= ord(c) < 0x7F) or ord(c) > 0x9F
        )

        # 3. Newline normalization.
        value = _MULTI_NEWLINE.sub("\n", value)

        # 4. Injection pattern stripping.
        for pattern in _INJECTION_PATTERNS:
            value = pattern.sub("[filtered]", value)

        # 5. Unicode normalization + bidi override removal.
        value = unicodedata.normalize("NFC", value)
        value = _BIDI_OVERRIDES.sub("", value)

        return value

    def sanitize_dict(self, meta: dict[str, str]) -> dict[str, str]:
        """Return a sanitized copy of a metadata dict."""
        return {k: self.sanitize(v) for k, v in meta.items()}
