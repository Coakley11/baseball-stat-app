"""Guards for anything that could reach a model or the screen.

Defense in depth: AMI's context is built from an allowlist (``context.PAGE_KEYS``) and tools
only read the dataset and named page snapshots, so secrets shouldn't get near it. These
checks make sure that if one ever does, it is dropped rather than shown or sent.
"""

from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = (
    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{8,}"),            # Stripe secret keys
    re.compile(r"rk_(?:live|test)_[A-Za-z0-9]{8,}"),            # Stripe restricted keys
    re.compile(r"whsec_[A-Za-z0-9]{8,}"),                       # Stripe webhook secrets
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{16,}"),              # Anthropic / OpenAI keys
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWTs (Supabase anon/service/user tokens)
    re.compile(r"sb_(?:secret|publishable)_[A-Za-z0-9_\-]{8,}"),  # Supabase API keys
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|service[_-]?role|access[_-]?token|refresh[_-]?token)\b\s*[:=]"),
    re.compile(r"(?i)postgres(?:ql)?://\S+"),
    re.compile(r"(?i)\b(?:cus|sub|pi|cs|price)_[A-Za-z0-9]{10,}\b"),  # Stripe customer/subscription/billing ids
)
_FILESYSTEM = re.compile(r"(?i)(?:[a-z]:\\|/home/|/users/|/mount/src|\\appdata\\)")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
REDACTED = "[redacted]"


def looks_secret(text: Any) -> bool:
    s = str(text or "")
    return any(p.search(s) for p in SECRET_PATTERNS) or bool(_FILESYSTEM.search(s))


def clean_text(value: Any, limit: int = 200) -> str:
    """Short single-line plain text; secrets and file paths become empty."""
    if value is None or not isinstance(value, (str, int, float)):
        return ""
    s = _CONTROL.sub(" ", str(value)).strip()
    if looks_secret(s):
        return ""
    return s[:limit]


def scrub(obj: Any, *, depth: int = 0) -> Any:
    """Copy of a JSON-like value with secret-looking strings redacted."""
    if depth > 12:
        return None
    if isinstance(obj, dict):
        return {str(k): scrub(v, depth=depth + 1) for k, v in obj.items() if not looks_secret(k)}
    if isinstance(obj, (list, tuple)):
        return [scrub(v, depth=depth + 1) for v in obj]
    if isinstance(obj, str):
        return REDACTED if looks_secret(obj) else obj
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    return str(obj)


def find_secrets(obj: Any) -> list[str]:
    """Every secret-looking string inside a JSON-like value (tests / assertions)."""
    hits: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                walk(k)
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, str) and looks_secret(v):
            hits.append(v[:40])

    walk(obj)
    return hits
