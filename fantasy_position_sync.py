"""Draft Assistant position-needs sync for fantasy research page filters."""

from __future__ import annotations

from typing import Any, Callable

from shared_draft_context import CANONICAL_SETTINGS_KEY, read_canonical_draft_settings, write_canonical_draft_settings

SYNC_POSITION_NEEDS_KEY = "sync_draft_assistant_position_needs"
DRAFT_ASSISTANT_POSITION_NEEDS_BLOB_KEY = "draft_assistant_position_needs"
RESEARCH_POSITION_FILTERS_BLOB_KEY = "research_position_filters"
TEMP_OVERRIDE_SESSION_PREFIX = "_fantasy_position_page_override:"

# Multiselect options (empty selection = all positions).
FANTASY_POSITION_MULTI_OPTIONS: tuple[str, ...] = (
    "C",
    "1B",
    "2B",
    "3B",
    "SS",
    "OF",
    "DH/UTIL",
)

RESEARCH_PAGE_POSITION_KEYS: dict[str, str] = {
    "Trend Value": "trend_position_filter",
    "Valuation": "value_position_filter",
    "ML Predictions": "ml_position_filter",
    "Fantasy Sleepers & Busts": "fantasy_market_positions",
}

SLEEPERS_RAW_POSITION_OPTIONS: tuple[str, ...] = ("C", "1B", "2B", "3B", "SS", "OF", "DH", "P")


def _temp_override_key(page: str) -> str:
    return f"{TEMP_OVERRIDE_SESSION_PREFIX}{page}"


def is_position_sync_enabled(session: dict[str, Any]) -> bool:
    blob = session.get(CANONICAL_SETTINGS_KEY)
    if isinstance(blob, dict) and "sync_position_needs_to_research" in blob:
        return bool(blob.get("sync_position_needs_to_research"))
    return bool(session.get(SYNC_POSITION_NEEDS_KEY, False))


def read_draft_assistant_position_needs(session: dict[str, Any]) -> list[str]:
    blob = session.get(CANONICAL_SETTINGS_KEY)
    if isinstance(blob, dict) and isinstance(blob.get(DRAFT_ASSISTANT_POSITION_NEEDS_BLOB_KEY), list):
        return [str(p).strip() for p in blob[DRAFT_ASSISTANT_POSITION_NEEDS_BLOB_KEY] if str(p).strip()]
    legacy = session.get(DRAFT_ASSISTANT_POSITION_NEEDS_BLOB_KEY)
    if isinstance(legacy, list):
        return [str(p).strip() for p in legacy if str(p).strip()]
    return []


def read_research_position_filters(session: dict[str, Any]) -> dict[str, list[str]]:
    blob = session.get(CANONICAL_SETTINGS_KEY)
    if isinstance(blob, dict):
        raw = blob.get(RESEARCH_POSITION_FILTERS_BLOB_KEY)
        if isinstance(raw, dict):
            out: dict[str, list[str]] = {}
            for page, vals in raw.items():
                if isinstance(vals, list):
                    out[str(page)] = normalize_position_filter_list(vals)
            return out
    return {}


def normalize_position_filter_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        if not s or s in ("All positions", "All"):
            return []
        return [s]
    if isinstance(raw, (list, tuple, set)):
        out: list[str] = []
        for item in raw:
            s = str(item or "").strip()
            if not s or s in ("All positions", "All"):
                continue
            if s not in out:
                out.append(s)
        return out
    return []


def draft_needs_to_fantasy_slots(needs: list[str]) -> list[str]:
    out: list[str] = []
    for pos in normalize_position_filter_list(needs):
        slot = "DH/UTIL" if pos == "DH" else pos
        if slot in FANTASY_POSITION_MULTI_OPTIONS and slot not in out:
            out.append(slot)
    return out


def draft_needs_to_sleepers_raw(needs: list[str]) -> list[str]:
    out: list[str] = []
    for pos in normalize_position_filter_list(needs):
        if pos in SLEEPERS_RAW_POSITION_OPTIONS and pos not in out:
            out.append(pos)
        elif pos == "DH/UTIL" and "DH" not in out:
            out.append("DH")
    return out


def position_filter_for_page(page: str, needs: list[str]) -> list[str]:
    if page == "Fantasy Sleepers & Busts":
        return draft_needs_to_sleepers_raw(needs)
    return draft_needs_to_fantasy_slots(needs)


def write_position_sync_settings(
    session: dict[str, Any],
    *,
    sync_enabled: bool | None = None,
    draft_assistant_needs: list[str] | None = None,
    research_filters: dict[str, list[str]] | None = None,
    source_page: str = "",
    reason: str = "",
) -> dict[str, Any]:
    try:
        from shared_draft_context import hydrate_canonical_draft_settings_from_session

        hydrate_canonical_draft_settings_from_session(session)
    except ImportError:
        pass
    blob = dict(session.get(CANONICAL_SETTINGS_KEY) or {})
    if sync_enabled is not None:
        blob["sync_position_needs_to_research"] = bool(sync_enabled)
        session[SYNC_POSITION_NEEDS_KEY] = bool(sync_enabled)
    if draft_assistant_needs is not None:
        blob[DRAFT_ASSISTANT_POSITION_NEEDS_BLOB_KEY] = normalize_position_filter_list(draft_assistant_needs)
    if research_filters is not None:
        cleaned = {
            str(page): normalize_position_filter_list(vals)
            for page, vals in research_filters.items()
        }
        blob[RESEARCH_POSITION_FILTERS_BLOB_KEY] = cleaned
    session[CANONICAL_SETTINGS_KEY] = blob
    return blob


def update_draft_assistant_position_needs(session: dict[str, Any], needs: list[str], *, source_page: str = "") -> None:
    normalized = normalize_position_filter_list(needs)
    prev = read_draft_assistant_position_needs(session)
    if normalized == prev:
        return
    write_position_sync_settings(
        session,
        draft_assistant_needs=normalized,
        source_page=source_page or "Draft Assistant Simulator",
        reason="draft_assistant_needs",
    )


def clear_research_position_overrides(session: dict[str, Any]) -> None:
    for key in list(session.keys()):
        if str(key).startswith(TEMP_OVERRIDE_SESSION_PREFIX):
            session.pop(key, None)


def mark_research_position_override(session: dict[str, Any], page: str) -> None:
    session[_temp_override_key(page)] = True


def has_research_position_override(session: dict[str, Any], page: str) -> bool:
    return bool(session.get(_temp_override_key(page)))


def on_sync_position_needs_toggled(session: dict[str, Any], *, source_page: str = "") -> None:
    enabled = bool(session.get(SYNC_POSITION_NEEDS_KEY, False))
    write_position_sync_settings(session, sync_enabled=enabled, source_page=source_page, reason="sync_toggle")
    clear_research_position_overrides(session)


def on_research_position_filter_changed(
    session: dict[str, Any],
    *,
    page: str,
    widget_key: str,
) -> None:
    mark_research_position_override(session, page)
    selected = normalize_position_filter_list(session.get(widget_key))
    if is_position_sync_enabled(session):
        return
    filters = read_research_position_filters(session)
    filters[page] = selected
    write_position_sync_settings(
        session,
        research_filters=filters,
        source_page=page,
        reason="research_position_filter",
    )


def prepare_research_position_filter(
    session: dict[str, Any],
    *,
    page: str,
    widget_key: str,
) -> list[str]:
    """Set widget value from sync/defaults before render; return effective selection."""
    if is_position_sync_enabled(session):
        if not has_research_position_override(session, page):
            needs = read_draft_assistant_position_needs(session)
            session[widget_key] = position_filter_for_page(page, needs)
    else:
        if not has_research_position_override(session, page):
            saved = read_research_position_filters(session).get(page)
            if saved is not None:
                session[widget_key] = list(saved)
            elif widget_key not in session:
                session[widget_key] = []
    return normalize_position_filter_list(session.get(widget_key))


def make_research_position_on_change(page: str, widget_key: str, extra: Callable[[], None] | None = None):
    def _cb() -> None:
        try:
            import streamlit as st

            on_research_position_filter_changed(st.session_state, page=page, widget_key=widget_key)
        except Exception:
            pass
        if extra is not None:
            try:
                extra()
            except Exception:
                pass

    return _cb


def format_position_filter_caption(selected: list[str]) -> str:
    if not selected:
        return "All positions"
    return ", ".join(selected)
