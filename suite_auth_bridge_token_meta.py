"""Sanitized token-generation metadata for browser auth bridge (no raw secrets in logs)."""

from __future__ import annotations

import hashlib
from typing import Any

GENERATION_KEY = "token_generation"
REFRESH_FP_KEY = "refresh_fp"
ACCESS_FP_KEY = "access_fp"
HANDOFF_PHASE_KEY = "handoff_phase"


def token_fingerprint(token: str, *, nbytes: int = 8) -> str:
    raw = str(token or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[: nbytes * 2]


def bridge_payload_meta(payload: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(payload or {})
    try:
        gen = int(p.get(GENERATION_KEY) or 0)
    except (TypeError, ValueError):
        gen = 0
    access = str(p.get("access_token") or "").strip()
    refresh = str(p.get("refresh_token") or "").strip()
    return {
        "token_generation": gen,
        "refresh_fp": str(p.get(REFRESH_FP_KEY) or token_fingerprint(refresh)),
        "access_fp": str(p.get(ACCESS_FP_KEY) or token_fingerprint(access)),
        "handoff_phase": str(p.get(HANDOFF_PHASE_KEY) or "")[:32],
    }


def enrich_bridge_payload(
    tokens: dict[str, Any],
    *,
    token_generation: int,
    handoff_phase: str = "",
) -> dict[str, Any]:
    access = str(tokens.get("access_token") or "").strip()
    refresh = str(tokens.get("refresh_token") or "").strip()
    phase = str(handoff_phase or tokens.get(HANDOFF_PHASE_KEY) or "").strip()[:32]
    out = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(tokens.get("expires_at") or 0),
        GENERATION_KEY: int(token_generation),
        REFRESH_FP_KEY: token_fingerprint(refresh),
        ACCESS_FP_KEY: token_fingerprint(access),
    }
    if phase:
        out[HANDOFF_PHASE_KEY] = phase
    return out
