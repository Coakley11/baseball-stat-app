"""
Supabase PostgREST backend for cross-deployment suite activity.
"""

from __future__ import annotations

import json
from activity_time import normalize_timestamp_iso, utc_now_iso
from datetime import datetime
from typing import Any

from suite_storage_config import SuiteCloudConfig, get_cloud_config

MAX_EVENTS = 2000
ACTIVE_APP_KEYS = frozenset(
    {
        "music",
        "investment",
        "baseball",
        "nba",
        "applied_intelligence",
        "future_lens",
    }
)

_TABLE_USERS = "suite_users"
_TABLE_EVENTS = "suite_activity_events"
_TABLE_STATE = "suite_app_current_state"
_TABLE_RESUME = "suite_resume_items"
_TABLE_SAVED = "suite_saved_items"
_TABLE_SETTINGS = "suite_user_settings"
_SAVED_ITEM_CONFLICT_COLS = "user_id,app,item_type,item_key"
_STATE_CONFLICT_COLS = "user_id,app"
_FULL_SESSION_KEY = "full_session"


def _full_session_draft_pick_count(blob: Any) -> int:
    if not isinstance(blob, dict):
        return 0
    try:
        from draft_room_state import draft_room_restore_stats

        return int(draft_room_restore_stats(blob).get("pick_count") or 0)
    except Exception:
        return 0


def _merge_full_session_preserve_richer_draft(
    prior: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Never let an incoming full_session wipe a richer draft-room board."""
    import copy

    prior_picks = _full_session_draft_pick_count(prior)
    incoming_picks = _full_session_draft_pick_count(incoming)
    if incoming_picks >= prior_picks:
        return copy.deepcopy(incoming)
    merged = copy.deepcopy(incoming)
    for key in ("draft_room_state", "draft_room_table"):
        if key in prior:
            merged[key] = copy.deepcopy(prior[key])
    prior_pf = prior.get("page_filter_state")
    incoming_pf = merged.get("page_filter_state")
    if isinstance(prior_pf, dict):
        prior_block = prior_pf.get("Draft Room Simulator")
        if isinstance(prior_block, dict):
            pf = incoming_pf if isinstance(incoming_pf, dict) else {}
            block = pf.get("Draft Room Simulator")
            if not isinstance(block, dict):
                block = {}
            block["draft_room_table"] = copy.deepcopy(
                prior_block.get("draft_room_table") or prior.get("draft_room_state") or {}
            )
            for setting_key in (
                "room_team_names",
                "room_your_team",
                "room_team_count",
                "room_rounds",
                "room_format",
            ):
                if setting_key in prior_block:
                    block[setting_key] = copy.deepcopy(prior_block[setting_key])
            pf["Draft Room Simulator"] = block
            merged["page_filter_state"] = pf
    return merged


def _merge_state_metrics(app_key: str, incoming: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow-merge metrics; preserve ``full_session`` when incoming omits it."""
    import copy

    new_metrics = dict(incoming or {})
    try:
        existing = load_current_states().get(app_key) or {}
        prior = existing.get("metrics")
        if not isinstance(prior, dict) or not prior:
            return new_metrics
        merged = dict(prior)
        merged.update(new_metrics)
        if _FULL_SESSION_KEY not in new_metrics and _FULL_SESSION_KEY in prior:
            merged[_FULL_SESSION_KEY] = prior[_FULL_SESSION_KEY]
        elif _FULL_SESSION_KEY in new_metrics and _FULL_SESSION_KEY in prior:
            prior_blob = prior.get(_FULL_SESSION_KEY)
            incoming_blob = new_metrics.get(_FULL_SESSION_KEY)
            if isinstance(prior_blob, dict) and isinstance(incoming_blob, dict):
                merged[_FULL_SESSION_KEY] = _merge_full_session_preserve_richer_draft(
                    prior_blob,
                    incoming_blob,
                )
        return merged
    except Exception:
        return new_metrics


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _headers(cfg: SuiteCloudConfig, *, prefer: str = "return=minimal") -> dict[str, str]:
    return {
        "apikey": cfg.key,
        "Authorization": f"Bearer {cfg.key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _request(
    method: str,
    path: str,
    *,
    cfg: SuiteCloudConfig | None = None,
    params: dict[str, str] | None = None,
    json_body: Any = None,
    prefer: str = "return=minimal",
) -> Any:
    import requests  # lazy import — available in all suite apps

    config = cfg or get_cloud_config()
    if config is None:
        raise RuntimeError("Supabase is not configured")

    url = f"{config.url}/rest/v1/{path}"
    response = requests.request(
        method,
        url,
        headers=_headers(config, prefer=prefer),
        params=params,
        json=json_body,
        timeout=15,
    )
    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(f"Supabase {method} {path} failed ({response.status_code}): {detail}")
    if not response.content:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        return None


def normalize_app_key(app: str) -> str:
    cleaned = str(app or "").strip()
    if cleaned == "math":
        return "applied_intelligence"
    return cleaned


def _scoped_user_id() -> str:
    from suite_user import get_account_user_id

    return get_account_user_id()


def _cloud_user_id() -> str | None:
    uid = _scoped_user_id()
    if not uid or uid.startswith("local:"):
        return None
    return uid


def ensure_user_row(
    external_id: str,
    *,
    email: str = "",
    display_name: str = "",
) -> str:
    """Create or fetch suite_users row; returns Supabase UUID."""
    ext = str(external_id or "default").strip() or "default"
    existing = _request(
        "GET",
        _TABLE_USERS,
        params={
            "select": "id",
            "external_id": f"eq.{ext}",
            "limit": "1",
        },
        prefer="return=representation",
    )
    if isinstance(existing, list) and existing and isinstance(existing[0], dict):
        row_id = str(existing[0].get("id") or "").strip()
        if row_id:
            return row_id
    created = _request(
        "POST",
        _TABLE_USERS,
        json_body={
            "external_id": ext,
            "email": email or "",
            "display_name": display_name or ext.replace("_", " ").title(),
        },
        prefer="return=representation",
    )
    if isinstance(created, list) and created and isinstance(created[0], dict):
        row_id = str(created[0].get("id") or "").strip()
        if row_id:
            return row_id
    if isinstance(created, dict):
        row_id = str(created.get("id") or "").strip()
        if row_id:
            return row_id
    raise RuntimeError(f"Could not resolve suite_users row for external_id={ext!r}")


def ping() -> bool:
    cfg = get_cloud_config()
    if cfg is None:
        return False
    try:
        _request("GET", _TABLE_EVENTS, cfg=cfg, params={"select": "id", "limit": "1"})
        return True
    except Exception:
        return False


def append_event(
    app: str,
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
) -> None:
    app_key = normalize_app_key(app)
    if not app_key:
        return
    body: dict[str, Any] = {
        "app": app_key,
        "event": event,
        "page": page or "",
        "timestamp": _now_iso(),
        "metrics": metrics or {},
    }
    uid = _cloud_user_id()
    if uid:
        body["user_id"] = uid
    _request("POST", _TABLE_EVENTS, json_body=body)


def save_current_state(
    app: str,
    *,
    page: str = "",
    summary: str = "",
    metrics: dict[str, Any] | None = None,
) -> None:
    save_current_state_with_result(app, page=page, summary=summary, metrics=metrics)


def save_current_state_with_result(
    app: str,
    *,
    page: str = "",
    summary: str = "",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write app state to Supabase; returns write mode + target ids for diagnostics."""
    app_key = normalize_app_key(app)
    uid = _cloud_user_id() or ""
    result: dict[str, Any] = {
        "ok": False,
        "write_mode": "skipped",
        "cloud_target_user_id": uid[:32] if uid else "",
        "cloud_target_app_id": app_key,
        "cloud_write_error": "",
        "rows_written": 0,
        "updated_at": "",
    }
    if app_key not in ACTIVE_APP_KEYS:
        result["cloud_write_error"] = f"inactive_app:{app_key}"
        return result
    if not uid:
        result["cloud_write_error"] = "local_account_no_cloud_user"
        return result

    merged_metrics = _merge_state_metrics(app_key, metrics)
    updated_at = _now_iso()
    patch_body = {
        "page": page or "",
        "summary": summary or "",
        "metrics": merged_metrics,
        "updated_at": updated_at,
    }
    patch_params = {"user_id": f"eq.{uid}", "app": f"eq.{app_key}"}
    body: dict[str, Any] = {
        "user_id": uid,
        "app": app_key,
        "page": patch_body["page"],
        "summary": patch_body["summary"],
        "metrics": merged_metrics,
        "updated_at": updated_at,
    }

    try:
        existing_rows = load_current_state_rows(app_key)
        if existing_rows:
            rows = _request(
                "PATCH",
                _TABLE_STATE,
                params=patch_params,
                json_body=patch_body,
                prefer="return=representation",
            )
            if isinstance(rows, list) and rows:
                result["ok"] = True
                result["write_mode"] = "patch"
                result["rows_written"] = len(rows)
                result["updated_at"] = updated_at
                return result

        post_params = {"on_conflict": _STATE_CONFLICT_COLS}
        try:
            rows = _request(
                "POST",
                _TABLE_STATE,
                params=post_params,
                json_body=body,
                prefer="resolution=merge-duplicates,return=representation",
            )
            if isinstance(rows, list) and rows:
                result["ok"] = True
                result["write_mode"] = "upsert"
                result["rows_written"] = len(rows)
                result["updated_at"] = updated_at
                return result
            result["ok"] = True
            result["write_mode"] = "upsert"
            result["rows_written"] = 0
            result["updated_at"] = updated_at
            return result
        except RuntimeError as exc:
            if not _is_duplicate_key_error(exc):
                raise
            rows = _request(
                "PATCH",
                _TABLE_STATE,
                params=patch_params,
                json_body=patch_body,
                prefer="return=representation",
            )
            if isinstance(rows, list) and rows:
                result["ok"] = True
                result["write_mode"] = "patch_after_conflict"
                result["rows_written"] = len(rows)
                result["updated_at"] = updated_at
                return result
            raise
    except RuntimeError as exc:
        result["cloud_write_error"] = str(exc)
    except Exception as exc:
        result["cloud_write_error"] = f"{type(exc).__name__}:{exc}"
    return result


def upsert_resume_item(
    app: str,
    item_key: str,
    *,
    title: str,
    subtitle: str = "",
    action_url: str = "",
) -> None:
    app_key = normalize_app_key(app)
    key = str(item_key or "").strip()
    title_clean = str(title or "").strip()
    if not app_key or not key or not title_clean:
        return
    if app_key not in ACTIVE_APP_KEYS:
        return
    body: dict[str, Any] = {
        "app": app_key,
        "item_key": key,
        "title": title_clean,
        "subtitle": subtitle or "",
        "action_url": action_url or "",
        "valid": True,
        "updated_at": _now_iso(),
    }
    uid = _cloud_user_id()
    if uid:
        body["user_id"] = uid
    _request(
        "POST",
        _TABLE_RESUME,
        json_body=body,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def invalidate_resume_item(app: str, item_key: str) -> None:
    app_key = normalize_app_key(app)
    key = str(item_key or "").strip()
    if not app_key or not key:
        return
    params: dict[str, str] = {"app": f"eq.{app_key}", "item_key": f"eq.{key}"}
    uid = _cloud_user_id()
    if uid:
        params["user_id"] = f"eq.{uid}"
    _request(
        "PATCH",
        _TABLE_RESUME,
        params=params,
        json_body={"valid": False, "updated_at": _now_iso()},
    )


def invalidate_app_resume_items(app: str) -> None:
    app_key = normalize_app_key(app)
    if not app_key:
        return
    params: dict[str, str] = {"app": f"eq.{app_key}"}
    uid = _cloud_user_id()
    if uid:
        params["user_id"] = f"eq.{uid}"
    _request(
        "PATCH",
        _TABLE_RESUME,
        params=params,
        json_body={"valid": False, "updated_at": _now_iso()},
    )


def load_events(limit: int = MAX_EVENTS) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "select": "app,event,page,timestamp,metrics",
        "order": "timestamp.desc",
        "limit": str(limit),
    }
    uid = _cloud_user_id()
    if uid:
        params["user_id"] = f"eq.{uid}"
    else:
        params["user_id"] = "is.null"
    rows = _request(
        "GET",
        _TABLE_EVENTS,
        params=params,
        prefer="return=representation",
    )
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        raw_ts = str(row.get("timestamp") or "")
        out.append(
            {
                "app": str(row.get("app") or ""),
                "event": str(row.get("event") or ""),
                "page": str(row.get("page") or ""),
                "timestamp": normalize_timestamp_iso(raw_ts) or raw_ts,
                "metrics": metrics,
            }
        )
    return out


def _state_row_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    app = str(row.get("app") or "")
    if app not in ACTIVE_APP_KEYS:
        return None
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    full_session = metrics.get(_FULL_SESSION_KEY)
    draft_picks = _full_session_draft_pick_count(full_session)
    return {
        "page": str(row.get("page") or ""),
        "summary": str(row.get("summary") or ""),
        "metrics": metrics,
        "updated_at": str(row.get("updated_at") or "")[:19],
        "_draft_pick_count": draft_picks,
        "_has_full_session": isinstance(full_session, dict) and bool(full_session),
    }


def _pick_best_state_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = _state_row_candidate(row)
        if candidate is None:
            continue
        if best is None:
            best = candidate
            continue
        cand_picks = int(candidate.get("_draft_pick_count") or 0)
        best_picks = int(best.get("_draft_pick_count") or 0)
        cand_ts = str(candidate.get("updated_at") or "")
        best_ts = str(best.get("updated_at") or "")
        if cand_picks > best_picks:
            best = candidate
            continue
        if cand_picks < best_picks:
            continue
        if cand_ts > best_ts:
            best = candidate
            continue
        if cand_ts == best_ts and candidate.get("_has_full_session") and not best.get("_has_full_session"):
            best = candidate
    return best


def load_current_state_rows(app: str | None = None) -> list[dict[str, Any]]:
    """Return raw ``suite_app_current_state`` rows for diagnostics."""
    params: dict[str, str] = {
        "select": "app,page,summary,metrics,updated_at,user_id",
        "order": "updated_at.desc",
    }
    uid = _cloud_user_id()
    if uid:
        params["user_id"] = f"eq.{uid}"
    if app:
        params["app"] = f"eq.{normalize_app_key(app)}"
    rows = _request(
        "GET",
        _TABLE_STATE,
        params=params,
        prefer="return=representation",
    )
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def load_cloud_row_diagnostics(app: str) -> dict[str, Any]:
    """Read-back diagnostics for the persistence boundary (save + refresh)."""
    app_key = normalize_app_key(app)
    uid = _cloud_user_id() or ""
    diag: dict[str, Any] = {
        "cloud_target_user_id": uid[:32] if uid else "",
        "cloud_target_app_id": app_key,
        "cloud_fetch_user_id": uid[:32] if uid else "",
        "cloud_fetch_app_id": app_key,
        "cloud_fetch_attempted": bool(uid),
        "cloud_fetch_success": False,
        "cloud_fetch_updated_at": None,
        "cloud_fetch_pick_count": 0,
        "supabase_row_pick_count_after_write": 0,
        "supabase_row_updated_at_after_write": None,
        "cloud_row_count": 0,
        "cloud_row_pick_counts": [],
        "cloud_load_error": None,
    }
    if not uid:
        diag["cloud_load_error"] = "local_account_no_cloud_user"
        return diag
    try:
        rows = load_current_state_rows(app_key)
        diag["cloud_row_count"] = len(rows)
        pick_counts: list[int] = []
        for row in rows:
            metrics = row.get("metrics")
            if not isinstance(metrics, dict):
                metrics = {}
            full_session = metrics.get(_FULL_SESSION_KEY)
            picks = _full_session_draft_pick_count(full_session)
            pick_counts.append(picks)
        diag["cloud_row_pick_counts"] = pick_counts
        best = _pick_best_state_row(rows)
        if best:
            diag["cloud_fetch_success"] = bool(best.get("_has_full_session"))
            diag["cloud_fetch_updated_at"] = best.get("updated_at")
            diag["supabase_row_updated_at_after_write"] = best.get("updated_at")
            picks = int(best.get("_draft_pick_count") or 0)
            diag["cloud_fetch_pick_count"] = picks
            diag["supabase_row_pick_count_after_write"] = picks
        elif rows:
            diag["cloud_fetch_success"] = True
            diag["cloud_fetch_updated_at"] = str(rows[0].get("updated_at") or "")[:19] or None
            diag["supabase_row_updated_at_after_write"] = diag["cloud_fetch_updated_at"]
    except Exception as exc:
        diag["cloud_load_error"] = f"{type(exc).__name__}:{exc}"
    return diag


def load_current_states() -> dict[str, dict[str, Any]]:
    rows = load_current_state_rows()
    if not rows:
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        app = str(row.get("app") or "")
        if app not in ACTIVE_APP_KEYS:
            continue
        grouped.setdefault(app, []).append(row)
    out: dict[str, dict[str, Any]] = {}
    for app, app_rows in grouped.items():
        best = _pick_best_state_row(app_rows)
        if best is None:
            continue
        out[app] = {
            "page": best.get("page") or "",
            "summary": best.get("summary") or "",
            "metrics": best.get("metrics") or {},
            "updated_at": best.get("updated_at"),
        }
    return out


def load_active_resume_items(limit: int = 8) -> list[dict[str, Any]]:
    rows = _request(
        "GET",
        _TABLE_RESUME,
        params={
            "select": "app,item_key,title,subtitle,action_url,updated_at",
            "user_id": f"eq.{_scoped_user_id()}",
            "valid": "eq.true",
            "order": "updated_at.desc",
            "limit": str(limit),
        },
        prefer="return=representation",
    )
    if not isinstance(rows, list):
        return []
    return [
        {
            "app": str(row.get("app") or ""),
            "item_key": str(row.get("item_key") or ""),
            "title": str(row.get("title") or ""),
            "subtitle": str(row.get("subtitle") or ""),
            "action_url": str(row.get("action_url") or ""),
            "updated_at": str(row.get("updated_at") or "")[:19],
        }
        for row in rows
        if isinstance(row, dict)
    ]


def _is_duplicate_key_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "409" in str(exc) or "duplicate key" in msg or "unique constraint" in msg


def upsert_saved_item(
    app: str,
    item_type: str,
    item_key: str,
    *,
    title: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Idempotent write for ``suite_saved_items``.

    Uses PostgREST upsert on ``(user_id, app, item_type, item_key)``; falls back to
  PATCH when a duplicate-key 409 still occurs (older PostgREST / missing on_conflict).
    """
    app_key = normalize_app_key(app)
    key = str(item_key or "").strip()
    title_clean = str(title or "").strip()
    itype = str(item_type or "item").strip() or "item"
    if not app_key or not key or not title_clean:
        return {"write_mode": "skipped", "duplicate_handled": False}
    uid = _scoped_user_id()
    row_body = {
        "user_id": uid,
        "app": app_key,
        "item_type": itype,
        "item_key": key,
        "title": title_clean,
        "payload": payload or {},
        "valid": True,
        "updated_at": _now_iso(),
    }
    patch_body = {
        "title": title_clean,
        "payload": payload or {},
        "valid": True,
        "updated_at": _now_iso(),
    }
    patch_params = {
        "user_id": f"eq.{uid}",
        "app": f"eq.{app_key}",
        "item_type": f"eq.{itype}",
        "item_key": f"eq.{key}",
    }
    try:
        _request(
            "POST",
            _TABLE_SAVED,
            params={"on_conflict": _SAVED_ITEM_CONFLICT_COLS},
            json_body=row_body,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        return {"write_mode": "upsert", "duplicate_handled": False}
    except RuntimeError as exc:
        if not _is_duplicate_key_error(exc):
            raise
        _request(
            "PATCH",
            _TABLE_SAVED,
            params=patch_params,
            json_body=patch_body,
            prefer="return=minimal",
        )
        return {"write_mode": "update", "duplicate_handled": True}


def invalidate_saved_item(app: str, item_type: str, item_key: str) -> None:
    app_key = normalize_app_key(app)
    key = str(item_key or "").strip()
    itype = str(item_type or "item").strip() or "item"
    if not app_key or not key:
        return
    _request(
        "PATCH",
        _TABLE_SAVED,
        params={
            "user_id": f"eq.{_scoped_user_id()}",
            "app": f"eq.{app_key}",
            "item_type": f"eq.{itype}",
            "item_key": f"eq.{key}",
        },
        json_body={"valid": False, "updated_at": _now_iso()},
    )


def load_saved_items(
    *,
    app: str | None = None,
    item_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "select": "app,item_type,item_key,title,payload,updated_at",
        "user_id": f"eq.{_scoped_user_id()}",
        "valid": "eq.true",
        "order": "updated_at.desc",
        "limit": str(limit),
    }
    if app:
        params["app"] = f"eq.{normalize_app_key(app)}"
    if item_type:
        params["item_type"] = f"eq.{item_type}"
    rows = _request("GET", _TABLE_SAVED, params=params, prefer="return=representation")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        out.append(
            {
                "app": str(row.get("app") or ""),
                "item_type": str(row.get("item_type") or ""),
                "item_key": str(row.get("item_key") or ""),
                "title": str(row.get("title") or ""),
                "payload": payload,
                "updated_at": str(row.get("updated_at") or "")[:19],
            }
        )
    return out


def save_user_settings(app: str, settings: dict[str, Any]) -> None:
    app_key = str(app or "_global").strip() or "_global"
    _request(
        "POST",
        _TABLE_SETTINGS,
        json_body={
            "user_id": _scoped_user_id(),
            "app": app_key,
            "settings": settings or {},
            "updated_at": _now_iso(),
        },
        prefer="resolution=merge-duplicates,return=minimal",
    )


def load_user_settings(app: str = "_global") -> dict[str, Any]:
    app_key = str(app or "_global").strip() or "_global"
    rows = _request(
        "GET",
        _TABLE_SETTINGS,
        params={
            "select": "settings,updated_at",
            "user_id": f"eq.{_scoped_user_id()}",
            "app": f"eq.{app_key}",
            "limit": "1",
        },
        prefer="return=representation",
    )
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        settings = rows[0].get("settings")
        if isinstance(settings, dict):
            return settings
    return {}


_FAST_CC_EVENTS = frozenset({"analytical_question"})


def _defer_append_event(
    app: str,
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget activity event so Command Center resume card is not blocked."""
    import threading

    def _run() -> None:
        try:
            append_event(app, event, page=page, metrics=metrics)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def record_activity(
    app: str,
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
    summary: str = "",
    resume_key: str = "",
    resume_title: str = "",
    resume_subtitle: str = "",
    action_url: str = "",
    timing_out: dict[str, Any] | None = None,
) -> None:
    import time

    event_key = str(event or "").strip()

    # AMI question sends: resume card first; defer non-critical event logging.
    if event_key in _FAST_CC_EVENTS:
        if resume_key and resume_title:
            t_resume = time.perf_counter()
            upsert_resume_item(
                app,
                resume_key,
                title=resume_title,
                subtitle=resume_subtitle,
                action_url=action_url,
            )
            if timing_out is not None:
                timing_out["saved_item_link_ms"] = round((time.perf_counter() - t_resume) * 1000, 1)
                timing_out["command_center_index_ms"] = timing_out["saved_item_link_ms"]
        _defer_append_event(app, event, page=page, metrics=metrics)
        if timing_out is not None:
            timing_out["append_event_ms"] = 0.0
            timing_out["append_event_deferred"] = True
        return

    t_evt = time.perf_counter()
    append_event(app, event, page=page, metrics=metrics)
    if timing_out is not None:
        timing_out["append_event_ms"] = round((time.perf_counter() - t_evt) * 1000, 1)

    # Applied-math insight events must not replace metrics.full_session (Test D portfolio).
    if event_key == "applied_math_insight":
        if resume_key and resume_title:
            t_resume = time.perf_counter()
            upsert_resume_item(
                app,
                resume_key,
                title=resume_title,
                subtitle=resume_subtitle,
                action_url=action_url,
            )
            if timing_out is not None:
                timing_out["saved_item_link_ms"] = round((time.perf_counter() - t_resume) * 1000, 1)
                timing_out["command_center_index_ms"] = timing_out["saved_item_link_ms"]
        return

    if summary or page or metrics:
        t_state = time.perf_counter()
        save_current_state(app, page=page, summary=summary, metrics=metrics)
        if timing_out is not None:
            timing_out["activity_storage_ms"] = round((time.perf_counter() - t_state) * 1000, 1)
    if resume_key and resume_title:
        t_resume = time.perf_counter()
        upsert_resume_item(
            app,
            resume_key,
            title=resume_title,
            subtitle=resume_subtitle,
            action_url=action_url,
        )
        if timing_out is not None:
            timing_out["saved_item_link_ms"] = round((time.perf_counter() - t_resume) * 1000, 1)
            timing_out["command_center_index_ms"] = timing_out["saved_item_link_ms"]
