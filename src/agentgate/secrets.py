from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|auth(orization)?|bearer|client[_-]?secret|"
    r"cookie|credential|password|passwd|private[_-]?key|secret|session)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"AKIA[0-9A-Z]{16}|"
    r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"Basic\s+[A-Za-z0-9+/=]{8,}|"
    r"sk-[A-Za-z0-9_-]{12,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,})",
    re.IGNORECASE,
)


def contains_likely_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and SECRET_KEY_RE.search(key):
                return True
            if contains_likely_secret(nested):
                return True
        return False

    if isinstance(value, list | tuple | set):
        return any(contains_likely_secret(item) for item in value)

    if isinstance(value, str):
        return bool(SECRET_VALUE_RE.search(value))

    return False


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            if isinstance(key, str) and SECRET_KEY_RE.search(key):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact(nested)
        return redacted

    if isinstance(value, list):
        return [redact(item) for item in value]

    if isinstance(value, str) and SECRET_VALUE_RE.search(value):
        return "[REDACTED]"

    return value

