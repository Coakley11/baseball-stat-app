"""Saved Draft Library — coherent active archive / context selection."""

from __future__ import annotations

from typing import Any

ACTIVE_PAIR_DIAG_KEY = "_saved_draft_library_active_pair_diag"


def _archive_draft_id(archive: dict[str, Any] | None) -> str:
    return str((archive or {}).get("draft_id") or "").strip()


def _context_source_draft_id(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    meta = dict(context.get("metadata") or {})
    return str(meta.get("source_draft_id") or context.get("source_draft_id") or "").strip()


def _context_id(context: dict[str, Any] | None) -> str:
    return str((context or {}).get("league_context_id") or "").strip()


def active_pair_is_coherent(
    active_archive: dict[str, Any] | None,
    active_context: dict[str, Any] | None,
) -> tuple[bool, str]:
    """Return (coherent, reason). Never allow hybrid archive/context pairing."""
    if not active_archive:
        if active_context:
            return False, "context_without_archive"
        return True, "none_active"
    if not active_context:
        return False, "archive_without_persisted_context"
    aid = _archive_draft_id(active_archive)
    sid = _context_source_draft_id(active_context)
    linked = str(active_archive.get("league_context_id") or "").strip()
    cid = _context_id(active_context)
    if sid and aid and sid != aid:
        return False, "source_draft_id_mismatch"
    if linked and cid and linked != cid:
        return False, "league_context_id_mismatch"
    return True, "coherent"


def resolve_coherent_active_library_selection(session: dict[str, Any]) -> dict[str, Any]:
    """Resolve persisted library active archive + context without source-priority override."""
    from draft_archive_state import get_active_draft_archive
    from fantasy_league_context import (
        context_id_for_archive,
        ensure_fantasy_league_context_state,
        get_active_league_context,
        get_league_context,
    )

    active_archive = get_active_draft_archive(session)
    active_context = get_active_league_context(session, respect_source_priority=False)
    store = ensure_fantasy_league_context_state(session)
    persisted_context_id = str(store.get("active_league_context_id") or "").strip()

    effective_context_id = ""
    effective_context_source = ""
    try:
        from fantasy_context_source import get_effective_fantasy_context, resolve_fantasy_context_source

        effective = get_effective_fantasy_context(session, respect_source_priority=True)
        effective_context_id = _context_id(effective if isinstance(effective, dict) else None)
        effective_context_source = str(resolve_fantasy_context_source(session).kind or "")
    except ImportError:
        pass

    linked_context: dict[str, Any] | None = None
    if active_archive:
        linked_id = str(active_archive.get("league_context_id") or "").strip()
        if not linked_id:
            linked_id = context_id_for_archive(_archive_draft_id(active_archive))
        linked_context = get_league_context(session, linked_id)

    coherent, reason = active_pair_is_coherent(active_archive, active_context)
    linked_active_context = active_context if isinstance(active_context, dict) else linked_context

    diag: dict[str, Any] = {
        "active_archive": active_archive,
        "active_context": active_context,
        "linked_active_context": linked_active_context,
        "coherent": coherent,
        "repair_reason": "" if coherent else reason,
        "active_draft_archive_id": _archive_draft_id(active_archive),
        "persisted_active_context_id": persisted_context_id,
        "effective_context_id": effective_context_id,
        "effective_context_source": effective_context_source,
        "active_archive_linked_context_id": str((active_archive or {}).get("league_context_id") or "").strip(),
        "active_context_source_draft_id": _context_source_draft_id(active_context),
        "active_pair_coherent": coherent,
        "active_pair_repair_reason": "" if coherent else reason,
        "repair_applied": "",
    }
    session[ACTIVE_PAIR_DIAG_KEY] = diag
    return diag


def repair_incoherent_active_library_selection(session: dict[str, Any]) -> dict[str, Any]:
    """Atomically align archive + context pointers when mismatched."""
    sel = resolve_coherent_active_library_selection(session)
    if sel.get("coherent"):
        return sel

    repair_applied = ""
    active_context = sel.get("active_context")
    active_archive = sel.get("active_archive")

    try:
        from fantasy_league_context import activate_archive_league_context

        if isinstance(active_context, dict) and _context_source_draft_id(active_context):
            draft_id = _context_source_draft_id(active_context)
            activate_archive_league_context(session, draft_id, defer_activation=False)
            repair_applied = "aligned_archive_to_persisted_context"
        elif isinstance(active_archive, dict) and _archive_draft_id(active_archive):
            activate_archive_league_context(session, _archive_draft_id(active_archive), defer_activation=False)
            repair_applied = "aligned_context_to_archive"
    except ImportError:
        pass

    out = resolve_coherent_active_library_selection(session)
    out["repair_applied"] = repair_applied
    session[ACTIVE_PAIR_DIAG_KEY] = out
    return out


def prepare_saved_draft_library_active_selection(session: dict[str, Any]) -> dict[str, Any]:
    """Repair incoherent pointers, then return persisted library selection."""
    fp_parts = []
    try:
        from draft_archive_state import get_active_draft_archive

        active = get_active_draft_archive(session)
        fp_parts.append(str((active or {}).get("draft_id") or ""))
    except ImportError:
        pass
    try:
        from fantasy_league_context import ensure_fantasy_league_context_state

        store = ensure_fantasy_league_context_state(session)
        fp_parts.append(str(store.get("active_league_context_id") or ""))
    except ImportError:
        pass
    fp_parts.append(str(session.get("_suite_auth_user_id") or ""))
    try:
        from account_fantasy_preferences import preference_revision_fingerprint

        fp_parts.append(preference_revision_fingerprint(session))
    except ImportError:
        pass
    fp = "|".join(fp_parts)
    if session.get("_library_selection_fp") == fp:
        cached = session.get("_library_selection_cached")
        if isinstance(cached, dict):
            return dict(cached)

    if not session.get("_creation_origin_repair_done"):
        try:
            from fantasy_league_context import backfill_immutable_creation_origins

            backfill_immutable_creation_origins(session)
            session["_creation_origin_repair_done"] = True
        except ImportError:
            pass
    try:
        from library_repair_scheduler import run_gated_library_repairs

        run_gated_library_repairs(session, user_mutated=False)
    except ImportError:
        pass
    sel = resolve_coherent_active_library_selection(session)
    if not sel.get("coherent"):
        sel = repair_incoherent_active_library_selection(session)
    session["_library_selection_fp"] = fp
    session["_library_selection_cached"] = dict(sel)
    return sel


def saved_draft_card_is_active(
    session: dict[str, Any],
    *,
    draft_id: str,
    league_context_id: str = "",
    selection: dict[str, Any] | None = None,
) -> bool:
    """True when card matches the coherent persisted active pair."""
    sel = selection or resolve_coherent_active_library_selection(session)
    if not sel.get("coherent"):
        return False
    active_id = str(sel.get("active_draft_archive_id") or "").strip()
    active_ctx_id = str(sel.get("persisted_active_context_id") or "").strip()
    draft_id = str(draft_id or "").strip()
    league_context_id = str(league_context_id or "").strip()
    if not active_id or draft_id != active_id:
        return False
    if active_ctx_id and league_context_id and league_context_id != active_ctx_id:
        return False
    return True


def render_active_library_pair_diagnostics(st: Any, session: dict[str, Any], *, developer_mode: bool = False) -> None:
    try:
        from page_diagnostics import inline_diagnostics_enabled
    except ImportError:
        inline_diagnostics_enabled = lambda dm: dm  # type: ignore[assignment,misc]
    if not developer_mode or not inline_diagnostics_enabled(developer_mode):
        return
    sel = session.get(ACTIVE_PAIR_DIAG_KEY) or resolve_coherent_active_library_selection(session)
    with st.expander("Active library pair diagnostics (Dev)", expanded=False):
        for key in (
            "active_draft_archive_id",
            "persisted_active_context_id",
            "effective_context_id",
            "effective_context_source",
            "active_archive_linked_context_id",
            "active_context_source_draft_id",
            "active_pair_coherent",
            "active_pair_repair_reason",
            "repair_applied",
        ):
            st.text(f"{key}: {sel.get(key)!r}")


def render_draft_assistant_progress_diagnostics(
    st: Any,
    session: dict[str, Any],
    progress: dict[str, Any],
    *,
    developer_mode: bool = False,
) -> None:
    try:
        from page_diagnostics import inline_diagnostics_enabled
    except ImportError:
        inline_diagnostics_enabled = lambda dm: dm  # type: ignore[assignment,misc]
    if not developer_mode or not inline_diagnostics_enabled(developer_mode):
        if developer_mode and progress:
            session["_draft_assistant_progress_diag"] = dict(progress)
        return
    with st.expander("Draft Assistant progress diagnostics (Dev)", expanded=False):
        for key, val in progress.items():
            st.text(f"{key}: {val!r}")
