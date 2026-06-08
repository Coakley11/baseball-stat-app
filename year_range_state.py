"""Sanitize persisted year-range tuples for Streamlit range sliders."""

from __future__ import annotations

from typing import Any


def _normalize_default(
    default: tuple[int, int],
    min_year: int,
    max_year: int,
) -> tuple[int, int]:
    start = max(min_year, min(int(default[0]), max_year))
    end = max(start, min(int(default[1]), max_year))
    return (start, end)


def _parse_year_pair(raw: Any) -> tuple[int, int] | None:
    if not isinstance(raw, (tuple, list)) or len(raw) != 2:
        return None
    try:
        return (int(raw[0]), int(raw[1]))
    except (TypeError, ValueError):
        return None


def sanitize_year_range(
    raw: Any,
    min_year: int,
    max_year: int,
    default: tuple[int, int] | None = None,
) -> tuple[int, int] | None:
    """
    Return a 2-item int tuple clamped to [min_year, max_year], or None when the
    slider bounds are invalid (min_year >= max_year).

    Missing, empty, non-numeric, or reversed saved values fall back to default
    (full range when default is omitted).
    """
    min_year = int(min_year)
    max_year = int(max_year)
    if min_year >= max_year:
        return None

    if default is None:
        default_pair = (min_year, max_year)
    else:
        default_pair = _normalize_default((int(default[0]), int(default[1])), min_year, max_year)

    parsed = _parse_year_pair(raw)
    if parsed is None:
        return default_pair

    start, end = parsed
    if start > end:
        return default_pair

    start = max(min_year, min(start, max_year))
    end = max(min_year, min(end, max_year))
    if start > end:
        return default_pair
    return (start, end)
