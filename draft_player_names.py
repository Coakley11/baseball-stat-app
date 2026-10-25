"""Draft Room player name resolution against the unified draft pool."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any


def _normalize_lookup_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_draft_player_name_index(pool_df: Any) -> dict[str, str]:
    """Map normalized keys → canonical fullName (first wins on collision)."""
    index: dict[str, str] = {}
    if pool_df is None or getattr(pool_df, "empty", True):
        return index
    col = "fullName" if "fullName" in pool_df.columns else "Player" if "Player" in pool_df.columns else None
    if not col:
        return index
    for raw in pool_df[col].dropna().astype(str).tolist():
        canonical = str(raw).strip()
        if not canonical:
            continue
        key = _normalize_lookup_key(canonical)
        if key and key not in index:
            index[key] = canonical
        base = canonical.split(" (")[0].strip()
        base_key = _normalize_lookup_key(base)
        if base_key and base_key not in index:
            index[base_key] = canonical
    return index


def draft_pool_display_names(pool_df: Any) -> list[str]:
    if pool_df is None or getattr(pool_df, "empty", True):
        return []
    col = "fullName" if "fullName" in pool_df.columns else "Player" if "Player" in pool_df.columns else None
    if not col:
        return []
    return sorted(dict.fromkeys(pool_df[col].dropna().astype(str).str.strip().tolist()))


def _word_prefix_matches(word: str, q: str) -> bool:
    if word.startswith(q):
        return True
    if len(q) >= 3 and len(word) >= len(q):
        prefix = word[: len(q)]
        return difflib.SequenceMatcher(None, q, prefix).ratio() >= 0.75
    return False


def _name_matches_query(key: str, q: str) -> bool:
    if not q:
        return False
    if key.startswith(q):
        return True
    return any(_word_prefix_matches(word, q) for word in key.split())


def search_draft_pool_names(query: str, names: list[str], *, limit: int = 20) -> list[str]:
    q = _normalize_lookup_key(query)
    if len(q) < 2:
        return []
    starts: list[str] = []
    contains: list[str] = []
    for name in names:
        key = _normalize_lookup_key(name)
        if _name_matches_query(key, q):
            starts.append(name)
        elif q in key:
            contains.append(name)
    out = starts + [n for n in contains if n not in starts]
    return out[:limit]


def resolve_draft_player_name(
    raw: str,
    name_index: dict[str, str],
    *,
    all_names: list[str] | None = None,
    cutoff: float = 0.82,
) -> tuple[str | None, list[str]]:
    """Return (canonical fullName, suggestions) for a typed/pasted name."""
    text = str(raw or "").strip()
    if not text:
        return None, []
    key = _normalize_lookup_key(text)
    if key in name_index:
        return name_index[key], []
    base_key = _normalize_lookup_key(text.split(" (")[0])
    if base_key in name_index:
        return name_index[base_key], []
    pool = all_names or sorted(set(name_index.values()))
    keys = [_normalize_lookup_key(n) for n in pool]
    matches = difflib.get_close_matches(key, keys, n=8, cutoff=cutoff)
    if not matches and len(key) >= 4:
        matches = difflib.get_close_matches(key, keys, n=8, cutoff=max(0.72, cutoff - 0.08))
    if len(matches) == 1:
        mk = matches[0]
        for n, nk in zip(pool, keys):
            if nk == mk:
                return n, []
    suggestions = []
    for mk in matches:
        for n, nk in zip(pool, keys):
            if nk == mk and n not in suggestions:
                suggestions.append(n)
    return None, suggestions[:5]


def _match_initial_last_name(text: str, all_names: list[str]) -> list[str]:
    """Match patterns like ``F. Lindor`` or ``A Judge`` against pool names."""
    raw = str(text or "").strip()
    m = re.match(r"^([A-Za-z])\.?\s+(.+)$", raw)
    if not m:
        return []
    initial = m.group(1).lower()
    last_key = _normalize_lookup_key(m.group(2))
    if not last_key:
        return []
    hits: list[str] = []
    for name in all_names:
        parts = str(name).split()
        if len(parts) < 2:
            continue
        first_initial = parts[0][0].lower()
        last_norm = _normalize_lookup_key(parts[-1])
        full_norm = _normalize_lookup_key(name)
        if first_initial != initial:
            continue
        if last_norm == last_key or last_key in full_norm.split()[-1:]:
            hits.append(name)
    return hits


def _close_match_candidates(
    text: str,
    name_index: dict[str, str],
    pool: list[str],
    *,
    fuzzy_cutoff: float = 0.72,
) -> list[str]:
    """Likely pool names for a non-exact import (no auto-pick)."""
    key = _normalize_lookup_key(text)
    hits: list[str] = []

    initial_hits = _match_initial_last_name(text, pool)
    if initial_hits:
        hits.extend(initial_hits)

    keys = [_normalize_lookup_key(n) for n in pool]
    match_keys = difflib.get_close_matches(key, keys, n=8, cutoff=fuzzy_cutoff)
    if not match_keys and len(key) >= 4:
        match_keys = difflib.get_close_matches(key, keys, n=8, cutoff=max(0.65, fuzzy_cutoff - 0.08))
    for mk in match_keys:
        for name, nk in zip(pool, keys):
            if nk == mk and name not in hits:
                hits.append(name)

    if not hits:
        fragment = key.split()[-1] if key.split() else key
        if len(fragment) >= 3:
            hits.extend(search_draft_pool_names(fragment, pool, limit=5))

    out: list[str] = []
    for name in hits:
        if name not in out:
            out.append(name)
    return out[:5]


def classify_draft_player_import_name(
    raw: str,
    name_index: dict[str, str],
    *,
    all_names: list[str] | None = None,
    fuzzy_cutoff: float = 0.82,
) -> dict[str, Any]:
    """Classify import row: exact, close, ambiguous, invalid, or empty."""
    text = str(raw or "").strip()
    if not text:
        return {"status": "empty", "canonical": None, "candidates": [], "input": text}

    pool = all_names or sorted(set(name_index.values()))
    key = _normalize_lookup_key(text)

    if key in name_index:
        canonical = name_index[key]
        if canonical.lower() == text.lower() or _normalize_lookup_key(canonical) == key:
            return {"status": "exact", "canonical": canonical, "candidates": [], "input": text}

    base_key = _normalize_lookup_key(text.split(" (")[0])
    if base_key in name_index:
        canonical = name_index[base_key]
        if canonical.lower() == text.lower() or _normalize_lookup_key(canonical) == base_key:
            return {"status": "exact", "canonical": canonical, "candidates": [], "input": text}

    candidates = _close_match_candidates(text, name_index, pool, fuzzy_cutoff=fuzzy_cutoff)
    if len(candidates) == 1:
        return {"status": "close", "canonical": None, "candidates": candidates, "input": text}
    if len(candidates) > 1:
        return {"status": "ambiguous", "canonical": None, "candidates": candidates, "input": text}
    return {"status": "invalid", "canonical": None, "candidates": [], "input": text}


def validate_draft_player_lines(
    lines: list[str],
    name_index: dict[str, str],
    *,
    all_names: list[str] | None = None,
) -> dict[str, Any]:
    """Classify pasted/typed lines into matched, unmatched, and auto-corrected."""
    matched: list[dict[str, str]] = []
    unmatched: list[dict[str, Any]] = []
    duplicates: list[str] = []
    seen_canonical: set[str] = set()
    for raw in lines:
        line = str(raw or "").strip()
        if not line:
            continue
        canonical, suggestions = resolve_draft_player_name(line, name_index, all_names=all_names)
        if canonical:
            if canonical in seen_canonical:
                duplicates.append(canonical)
            else:
                seen_canonical.add(canonical)
                if canonical != line:
                    matched.append({"input": line, "player": canonical, "corrected": True})
                else:
                    matched.append({"input": line, "player": canonical, "corrected": False})
        else:
            unmatched.append({"input": line, "suggestions": suggestions})
    return {
        "matched": matched,
        "unmatched": unmatched,
        "duplicates": duplicates,
        "canonical_names": [m["player"] for m in matched],
    }


def validate_draft_board_players(
    board: Any,
    name_index: dict[str, str],
    *,
    all_names: list[str] | None = None,
    player_column: str = "Player",
) -> dict[str, Any]:
    """Validate filled Player cells on the draft board."""
    invalid: list[dict[str, Any]] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    if board is None or getattr(board, "empty", True):
        return {"invalid": invalid, "duplicates": duplicates, "valid_count": 0}
    if player_column not in getattr(board, "columns", []):
        return {"invalid": invalid, "duplicates": duplicates, "valid_count": 0}
    valid_count = 0
    for raw in board[player_column].fillna("").astype(str).tolist():
        line = str(raw).strip()
        if not line:
            continue
        canonical, suggestions = resolve_draft_player_name(line, name_index, all_names=all_names)
        if canonical:
            valid_count += 1
            if canonical in seen:
                duplicates.append(canonical)
            else:
                seen.add(canonical)
        else:
            invalid.append({"input": line, "suggestions": suggestions})
    return {"invalid": invalid, "duplicates": duplicates, "valid_count": valid_count}
