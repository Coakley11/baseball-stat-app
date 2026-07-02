"""Sleepers page widget defaults (no Streamlit dependency)."""

from __future__ import annotations

from typing import Any


def read_sleepers_canonical_filters(session: dict[str, Any]) -> dict[str, Any]:
    """Canonical Sleepers filter blob for position/age widget defaults."""
    block = session.get("fantasy_state") or {}
    sleepers = block.get("sleepers") if isinstance(block, dict) else {}
    filters = sleepers.get("filters") if isinstance(sleepers, dict) else {}
    return dict(filters) if isinstance(filters, dict) else {}


def default_sleepers_age_range(session: dict[str, Any], *, age_hi: int) -> tuple[int, int]:
    """Default age slider range for the Sleepers position/age expander."""
    hi_cap = max(45, int(age_hi))
    raw = read_sleepers_canonical_filters(session).get("fantasy_market_age_range")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            lo = int(raw[0])
            hi_val = min(int(raw[1]), hi_cap)
            return (lo, hi_val)
        except (TypeError, ValueError):
            pass
    return (18, hi_cap)


def resolve_sleepers_position_age_defaults(session: dict[str, Any], *, age_hi: int = 45) -> dict[str, Any]:
    """Resolve Sleepers expander defaults without Streamlit (smoke/regression helper)."""
    canon = read_sleepers_canonical_filters(session)
    positions = canon.get("fantasy_market_positions")
    return {
        "canonical_filters": canon,
        "default_positions": list(positions) if isinstance(positions, list) else None,
        "default_age_range": default_sleepers_age_range(session, age_hi=age_hi),
    }
