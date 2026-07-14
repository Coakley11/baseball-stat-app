"""Gate Saved Draft Library repairs and migrations — read-only renders skip heavy work."""

from __future__ import annotations

from typing import Any

LIBRARY_REPAIR_VERSION = 3

LIBRARY_REPAIR_DONE_KEY = "_library_repair_scheduler_done_v"
LIBRARY_DIRTY_KEY = "_library_repair_dirty"
LIBRARY_MANIFEST_REV_KEY = "_library_manifest_revision"


def mark_library_dirty(session: dict[str, Any], *, reason: str = "") -> None:
    session[LIBRARY_DIRTY_KEY] = True
    session.pop(f"{LIBRARY_REPAIR_DONE_KEY}{LIBRARY_REPAIR_VERSION}", None)
    trace = session.get("_library_repair_dirty_trace")
    if not isinstance(trace, list):
        trace = []
    trace.append(str(reason or "unknown"))
    session["_library_repair_dirty_trace"] = trace[-16:]


def library_repairs_required(session: dict[str, Any], *, user_mutated: bool = False) -> bool:
    if user_mutated or session.get(LIBRARY_DIRTY_KEY):
        return True
    done_key = f"{LIBRARY_REPAIR_DONE_KEY}{LIBRARY_REPAIR_VERSION}"
    if session.get(done_key):
        return False
    try:
        from draft_archive_state import DRAFT_ARCHIVE_KEY

        raw = session.get(DRAFT_ARCHIVE_KEY)
        if not isinstance(raw, list) or not raw:
            return False
    except ImportError:
        return False
    return True


def mark_library_repairs_complete(session: dict[str, Any]) -> None:
    session[f"{LIBRARY_REPAIR_DONE_KEY}{LIBRARY_REPAIR_VERSION}"] = True
    session[LIBRARY_DIRTY_KEY] = False


def run_gated_library_repairs(session: dict[str, Any], *, user_mutated: bool = False) -> dict[str, Any]:
    """Run migration/repair stack only when dirty, version bump, or user action."""
    trace: dict[str, Any] = {"ran": False, "steps": []}
    if not library_repairs_required(session, user_mutated=user_mutated):
        trace["skipped"] = "read_only_render"
        return trace
    trace["ran"] = True

    if not session.get("_creation_origin_repair_done"):
        try:
            from fantasy_league_context import backfill_immutable_creation_origins

            backfill_immutable_creation_origins(session)
            session["_creation_origin_repair_done"] = True
            trace["steps"].append("creation_origin_backfill")
        except ImportError:
            pass

    try:
        from live_draft_lineup_config import repair_known_live_draft_lineup_configs

        repair_known_live_draft_lineup_configs(session)
        trace["steps"].append("live_draft_lineup_repair")
    except ImportError:
        pass

    for fn_name, mod, attr in (
        ("migrate_legacy", "fantasy_league_context", "migrate_legacy_archives_to_contexts"),
        ("repair_imported", "fantasy_league_context", "repair_misclassified_imported_league_archives"),
        ("repair_draft_types", "fantasy_league_context", "repair_archive_draft_types_from_contexts"),
        ("repair_missing_archives", "fantasy_league_context", "repair_missing_draft_archives_from_contexts"),
    ):
        try:
            mod_obj = __import__(mod, fromlist=[attr])
            fn = getattr(mod_obj, attr, None)
            if callable(fn):
                fn(session)
                trace["steps"].append(fn_name)
        except ImportError:
            pass
        except Exception:
            pass

    mark_library_repairs_complete(session)
    return trace
