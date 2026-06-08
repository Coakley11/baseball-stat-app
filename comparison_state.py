"""Canonical Comparison Tool player state — one source of truth for multiselect + sig tests."""

from __future__ import annotations

import re
from typing import Any, Callable

_TEAM_SUFFIX = re.compile(r"^(.+?)\s+\(([A-Z]{2,4})\)$")

ResolveFn = Callable[[str, dict[str, Any]], str | None]


def normalize_compare_label(
    raw: Any,
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> str | None:
    """Map stored / legacy labels to a canonical Lahman dropdown label."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s in label_map:
        return s
    resolved = resolve_fn(s, label_map)
    if resolved and resolved in label_map:
        return resolved
    m = _TEAM_SUFFIX.match(s)
    if m:
        base = m.group(1).strip()
        resolved = resolve_fn(base, label_map)
        if resolved and resolved in label_map:
            return resolved
    return None


def reconcile_compare_player_list(
    raw_list: Any,
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> list[str]:
    if not isinstance(raw_list, list):
        return []
    out: list[str] = []
    for item in raw_list:
        lbl = normalize_compare_label(item, label_map, resolve_fn)
        if lbl and lbl not in out:
            out.append(lbl)
        if len(out) >= 3:
            break
    return out


def _sig_slot_players(session: dict[str, Any], label_map: dict[str, Any], resolve_fn: ResolveFn) -> list[str]:
    out: list[str] = []
    for key in (
        "pending_sig_player_a",
        "pending_sig_player_b",
        "sig_player_a_clean",
        "sig_player_b_clean",
    ):
        lbl = normalize_compare_label(session.get(key), label_map, resolve_fn)
        if lbl and lbl not in out:
            out.append(lbl)
        if len(out) >= 3:
            break
    return out


def gather_comparison_players(
    session: dict[str, Any],
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> list[str]:
    """Merge players from all known keys (most specific lists first)."""
    candidates: list[list[str]] = []

    for key in ("compare_players", "compare_players_saved", "pending_compare_players"):
        val = session.get(key)
        if isinstance(val, list) and val:
            reconciled = reconcile_compare_player_list(val, label_map, resolve_fn)
            if reconciled:
                candidates.append(reconciled)

    sig_players = _sig_slot_players(session, label_map, resolve_fn)
    if sig_players:
        candidates.append(sig_players)

    meta = session.get("comparison_state")
    if isinstance(meta, dict):
        meta_players = meta.get("players")
        if isinstance(meta_players, list) and meta_players:
            reconciled = reconcile_compare_player_list(meta_players, label_map, resolve_fn)
            if reconciled:
                candidates.append(reconciled)

    pf = session.get("page_filter_state")
    if isinstance(pf, dict):
        block = pf.get("Comparison Tool")
        if isinstance(block, dict):
            cp = block.get("compare_players")
            if isinstance(cp, list) and cp:
                reconciled = reconcile_compare_player_list(cp, label_map, resolve_fn)
                if reconciled:
                    candidates.append(reconciled)
            block_sig = _sig_slot_players(block, label_map, resolve_fn)
            if block_sig:
                candidates.append(block_sig)

    for src in candidates:
        if src:
            return src[:3]
    return []


def write_canonical_comparison_state(
    session: dict[str, Any],
    players: list[str],
    *,
    reason: str = "",
) -> list[str]:
    """Write one canonical player list to every comparison session key."""
    clean = [str(p).strip() for p in players if p][:3]
    session["compare_players"] = list(clean)
    session["compare_players_saved"] = list(clean)
    session["comparison_state"] = {
        "player_a": clean[0] if len(clean) > 0 else None,
        "player_b": clean[1] if len(clean) > 1 else None,
        "players": list(clean),
        "last_write_reason": reason or None,
    }
    if len(clean) >= 1:
        session["sig_player_a_clean"] = clean[0]
    else:
        session.pop("sig_player_a_clean", None)
    if len(clean) >= 2:
        session["sig_player_b_clean"] = clean[1]
    else:
        session.pop("sig_player_b_clean", None)
    session.pop("pending_compare_players", None)
    session.pop("pending_sig_player_a", None)
    session.pop("pending_sig_player_b", None)
    session.pop("pending_compare_clear_player_b", None)
    return clean


def prepare_comparison_tool_page(
    session: dict[str, Any],
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> list[str]:
    """Reconcile all comparison keys before widgets render."""
    pending = session.get("pending_compare_players")
    if isinstance(pending, list) and pending:
        merged = reconcile_compare_player_list(pending, label_map, resolve_fn)
        if merged:
            return write_canonical_comparison_state(session, merged, reason="pending_compare")

    gathered = gather_comparison_players(session, label_map, resolve_fn)
    return write_canonical_comparison_state(
        session,
        gathered,
        reason="reconcile_on_load" if gathered else "empty",
    )


def sync_compare_from_multiselect(
    session: dict[str, Any],
    selected: Any,
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> list[str]:
    players = reconcile_compare_player_list(selected, label_map, resolve_fn)
    return write_canonical_comparison_state(session, players, reason="multiselect_change")


def sync_compare_from_sig_ab(
    session: dict[str, Any],
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
) -> list[str]:
    a = normalize_compare_label(session.get("sig_player_a_clean"), label_map, resolve_fn)
    b = normalize_compare_label(session.get("sig_player_b_clean"), label_map, resolve_fn)
    players: list[str] = []
    if a:
        players.append(a)
    if b and b not in players:
        players.append(b)
    for p in reconcile_compare_player_list(session.get("compare_players") or [], label_map, resolve_fn):
        if p not in players and len(players) < 3:
            players.append(p)
    return write_canonical_comparison_state(session, players, reason="sig_ab_change")


def ensure_compare_multiselect(
    session: dict[str, Any],
    label_map: dict[str, Any],
    resolve_fn: ResolveFn,
    options: list[str],
) -> list[str]:
    """Ensure multiselect session value uses canonical labels present in options."""
    opts_set = set(options)
    players = reconcile_compare_player_list(session.get("compare_players") or [], label_map, resolve_fn)
    if not players:
        players = reconcile_compare_player_list(
            session.get("compare_players_saved") or [], label_map, resolve_fn
        )
    players = [p for p in players if p in opts_set][:3]
    write_canonical_comparison_state(session, players, reason="ensure_multiselect")
    return session.get("compare_players") or []


def record_comparison_sync_trace(session: dict[str, Any], *, winner: str, reason: str) -> None:
    session["_comparison_sync_winner"] = winner
    session["_comparison_sync_reason"] = reason


def render_comparison_state_debug(
    st: Any,
    session: dict[str, Any],
    label_map: dict[str, Any],
    *,
    selected_labels: list[str] | None = None,
) -> None:
    """Developer panel: show every comparison player key and canonical state."""
    try:
        from suite_user_persistence import state_file_path

        app_id = "baseball"
    except ImportError:
        state_file_path = None  # type: ignore[assignment]
        app_id = "baseball"

    meta = session.get("comparison_state")
    if not isinstance(meta, dict):
        meta = {}

    pf = session.get("page_filter_state")
    pf_cmp: dict[str, Any] = {}
    if isinstance(pf, dict):
        block = pf.get("Comparison Tool")
        if isinstance(block, dict):
            pf_cmp = block

    cloud_players = session.get("_suite_workspace_applied_comparison_players")
    restored_players = meta.get("players") or session.get("compare_players_saved")

    top_rows = {
        "widget compare_players": session.get("compare_players"),
        "compare_players_saved": session.get("compare_players_saved"),
        "pending_compare_players": session.get("pending_compare_players"),
    }
    canonical_rows = {
        "comparison_state.player_a": meta.get("player_a"),
        "comparison_state.player_b": meta.get("player_b"),
        "comparison_state.players": meta.get("players"),
        "last_write_reason": meta.get("last_write_reason"),
    }
    sig_rows = {
        "sig_player_a_clean": session.get("sig_player_a_clean"),
        "sig_player_b_clean": session.get("sig_player_b_clean"),
        "pending_sig_player_a": session.get("pending_sig_player_a"),
        "pending_sig_player_b": session.get("pending_sig_player_b"),
    }
    persist_rows = {
        "page_filter_state.compare_players": pf_cmp.get("compare_players"),
        "page_filter_state.sig_a": pf_cmp.get("sig_player_a_clean"),
        "page_filter_state.sig_b": pf_cmp.get("sig_player_b_clean"),
        "cloud_applied_comparison_players": cloud_players,
        "last_restored_players": restored_players,
        "last_saved_reason": session.get("_suite_persist_last_save_reason"),
    }
    decision_rows = {
        "sync_winner": session.get("_comparison_sync_winner"),
        "sync_reason": session.get("_comparison_sync_reason"),
        "chart_players_used": selected_labels or session.get("compare_players"),
    }

    with st.sidebar.expander("Comparison Tool state", expanded=True):
        st.caption("Canonical comparison_state drives top multiselect + bottom sig tests.")
        st.markdown("**Top UI**")
        for k, v in top_rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
        st.markdown("**Canonical**")
        for k, v in canonical_rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
        st.markdown("**Stat test (sig A/B)**")
        for k, v in sig_rows.items():
            if v is not None and v != "":
                st.text(f"{k}: {v}")
        st.markdown("**Persistence**")
        for k, v in persist_rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
        st.markdown("**Decision**")
        for k, v in decision_rows.items():
            if v is not None and v != "" and v != []:
                st.text(f"{k}: {v}")
