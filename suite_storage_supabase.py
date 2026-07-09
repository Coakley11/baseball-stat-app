"""
Supabase PostgREST backend for cross-deployment suite activity.
"""

from __future__ import annotations

import copy
import json
import time
from activity_time import normalize_timestamp_iso, utc_now_iso
from datetime import datetime
from typing import Any

from suite_storage_config import SuiteCloudConfig, get_auth_api_key, get_cloud_config, reset_cloud_config_cache

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
_FULL_SESSION_KEY = "full_session"
_READ_CACHE_KEY = "_suite_supabase_get_cache"
# Shared draft rooms must never be GET-cached — remote PATCHes on other devices
# do not invalidate this client's session cache.
_NO_GET_CACHE_TABLES = frozenset({"baseball_shared_draft_rooms", "baseball_shared_leagues"})


def _read_cache_bucket() -> dict[tuple[str, str, tuple[tuple[str, str], ...]], tuple[int, Any]]:
    try:
        import streamlit as st  # noqa: WPS433

        raw = st.session_state.get(_READ_CACHE_KEY)
        if isinstance(raw, dict):
            return raw
        bucket: dict[tuple[str, str, tuple[tuple[str, str], ...]], tuple[int, Any]] = {}
        st.session_state[_READ_CACHE_KEY] = bucket
        return bucket
    except Exception:
        return {}


def _cache_key(method: str, path: str, params: dict[str, str] | None) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    items = tuple(sorted((params or {}).items()))
    return (method.upper(), path, items)


def _invalidate_read_cache_for_table(table: str) -> None:
    bucket = _read_cache_bucket()
    if not bucket:
        return
    drop = [k for k in bucket if k[1] == table or k[1].startswith(f"{table}/")]
    for key in drop:
        bucket.pop(key, None)


def _row_to_state_dict(row: dict[str, Any], *, logical: str) -> dict[str, Any]:
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    page = str(row.get("page") or "")
    if not page.strip():
        full_session = metrics.get(_FULL_SESSION_KEY)
        if isinstance(full_session, dict):
            page = str(full_session.get("view_mode") or full_session.get("page") or "")
    return {
        "page": page,
        "summary": str(row.get("summary") or ""),
        "metrics": metrics,
        "updated_at": str(row.get("updated_at") or "")[:19],
    }


def _query_params_for_storage_app(
    storage_app: str,
    *,
    select: str,
    limit: str = "20",
    include_legacy_null: bool = False,
) -> dict[str, str]:
    """Scoped GET params: match signed-in user row OR legacy null row (diagnostics only)."""
    params: dict[str, str] = {
        "select": select,
        "app": f"eq.{storage_app}",
        "order": "updated_at.desc",
        "limit": limit,
    }
    _apply_user_scope_params(params, include_legacy_null=include_legacy_null)
    return params


def _fetch_state_rows_for_storage_app(
    storage_app: str,
    *,
    select: str,
    egress_label: str,
    limit: str = "20",
    include_legacy_null: bool = False,
) -> list[dict[str, Any]]:
    params = _query_params_for_storage_app(
        storage_app,
        select=select,
        limit=limit,
        include_legacy_null=include_legacy_null,
    )
    with _egress(egress_label):
        rows = _request("GET", _TABLE_STATE, params=params, prefer="return=representation")
    return rows if isinstance(rows, list) else []


def _full_session_workflow_score(full_session: dict[str, Any] | None) -> int:
    """Richness score for row selection — saved draft library dominates draft-room picks."""
    if not isinstance(full_session, dict):
        return 0
    pick_score = _draft_pick_count_from_session_blob(full_session)
    try:
        from workflow_persist_guard import DRAFT_ARCHIVE_KEY, LEAGUE_CONTEXT_STATE_KEY
        from workflow_persist_guard import count_draft_archives, count_league_contexts

        archive_score = count_draft_archives(full_session.get(DRAFT_ARCHIVE_KEY))
        context_score = count_league_contexts(full_session.get(LEAGUE_CONTEXT_STATE_KEY))
        active = 1 if str(full_session.get("active_draft_archive_id") or "").strip() else 0
        return archive_score * 100_000 + context_score * 1_000 + pick_score * 10 + active
    except ImportError:
        return pick_score


def load_current_state_meta_for_app(app: str) -> dict[str, Any]:
    """Lightweight row metadata for one app (no metrics / full_session download)."""
    from suite_workspace import logical_storage_app_key

    storage_app = _scoped_storage_app(app)
    logical = logical_storage_app_key(storage_app)
    if logical not in ACTIVE_APP_KEYS:
        return {}
    rows = _fetch_state_rows_for_storage_app(
        storage_app,
        select="app,page,summary,updated_at",
        egress_label="load_current_state_meta_for_app",
        limit="5",
    )
    if not rows:
        return {}
    row = _pick_best_state_row([r for r in rows if isinstance(r, dict)])
    if not isinstance(row, dict):
        row = rows[0] if rows else {}
    if not isinstance(row, dict):
        return {}
    return {
        "app": logical,
        "page": str(row.get("page") or ""),
        "summary": str(row.get("summary") or ""),
        "updated_at": str(row.get("updated_at") or "")[:19],
    }


def load_current_state_for_app(app: str) -> dict[str, Any]:
    """Fetch one app's state row including metrics/full_session (not all apps)."""
    from suite_workspace import logical_storage_app_key

    storage_app = _scoped_storage_app(app)
    logical = logical_storage_app_key(storage_app)
    if logical not in ACTIVE_APP_KEYS:
        return {}
    rows = _fetch_state_rows_for_storage_app(
        storage_app,
        select="app,page,summary,metrics,updated_at,user_id",
        egress_label="load_current_state_for_app",
    )
    best = _pick_best_state_row(rows)
    if not isinstance(best, dict):
        return {}
    return _row_to_state_dict(best, logical=logical)


def load_legacy_null_full_session_for_app(app: str) -> dict[str, Any]:
    """
    Pre-auth cloud blob (``user_id IS NULL``) for authenticated migration.

    Before Real Accounts, saved drafts often lived on legacy null-user rows for the
    unscoped Daniel ``baseball`` cloud key. Signed-in restore merges these when richer.
    """
    from suite_workspace import DEFAULT_WORKSPACE_ID, logical_storage_app_key, scoped_cloud_app_id

    storage_app = scoped_cloud_app_id(normalize_app_key(app), DEFAULT_WORKSPACE_ID)
    logical = logical_storage_app_key(storage_app)
    if logical not in ACTIVE_APP_KEYS:
        return {}
    rows = _fetch_state_rows_for_storage_app(
        storage_app,
        select="app,page,summary,metrics,updated_at,user_id",
        egress_label="load_legacy_null_full_session_for_app",
        limit="20",
        include_legacy_null=True,
    )
    null_rows = [
        r
        for r in rows
        if isinstance(r, dict) and not str(r.get("user_id") or "").strip()
    ]
    best = _pick_best_state_row(null_rows)
    if not isinstance(best, dict):
        return {}
    metrics = best.get("metrics") if isinstance(best.get("metrics"), dict) else {}
    blob = metrics.get(_FULL_SESSION_KEY)
    return copy.deepcopy(blob) if isinstance(blob, dict) else {}


def load_current_states_summary() -> dict[str, dict[str, Any]]:
    """All workspace apps — page/summary/updated_at only (no metrics blobs)."""
    from suite_workspace import logical_storage_app_key, workspace_storage_app_keys

    allowed = workspace_storage_app_keys()
    params: dict[str, str] = {"select": "app,page,summary,updated_at"}
    if allowed:
        params["app"] = f"in.({','.join(sorted(allowed))})"
    _apply_user_scope_params(params)
    with _egress("load_current_states_summary"):
        rows = _request("GET", _TABLE_STATE, params=params, prefer="return=representation")
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        storage_app = str(row.get("app") or "")
        if storage_app not in allowed:
            continue
        logical = logical_storage_app_key(storage_app)
        if logical not in ACTIVE_APP_KEYS:
            continue
        out[logical] = {
            "page": str(row.get("page") or ""),
            "summary": str(row.get("summary") or ""),
            "metrics": {},
            "updated_at": str(row.get("updated_at") or "")[:19],
        }
    return out


def _merge_state_metrics(scoped_app_key: str, incoming: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow-merge metrics; preserve ``full_session`` when incoming omits it."""
    new_metrics = dict(incoming or {})
    try:
        rows = _fetch_state_rows_for_storage_app(
            scoped_app_key,
            select="metrics,updated_at",
            egress_label="merge_state_metrics",
        )
        best = _pick_best_state_row(rows) if rows else None
        prior: dict[str, Any] = {}
        if isinstance(best, dict):
            raw = best.get("metrics")
            if isinstance(raw, dict):
                prior = raw
        if not prior:
            return new_metrics
        merged = dict(prior)
        merged.update(new_metrics)
        if _FULL_SESSION_KEY not in new_metrics and _FULL_SESSION_KEY in prior:
            merged[_FULL_SESSION_KEY] = prior[_FULL_SESSION_KEY]
        elif _FULL_SESSION_KEY in new_metrics and _FULL_SESSION_KEY in prior:
            merged[_FULL_SESSION_KEY] = _merge_full_session_preserve_richer_draft(
                prior[_FULL_SESSION_KEY],
                new_metrics[_FULL_SESSION_KEY],
            )
        return merged
    except Exception:
        return new_metrics


def _draft_pick_count_from_session_blob(full_session: dict[str, Any] | None) -> int:
    """Filled player picks only — not empty board row slots."""
    if not isinstance(full_session, dict):
        return 0
    try:
        from draft_room_state import draft_room_restore_stats

        return int(draft_room_restore_stats(full_session).get("pick_count") or 0)
    except ImportError:
        pass
    for key in ("draft_room_state", "draft_room_table"):
        blob = full_session.get(key)
        if not isinstance(blob, dict):
            continue
        try:
            if blob.get("pick_count") is not None:
                return int(blob.get("pick_count") or 0)
        except (TypeError, ValueError):
            pass
        records = blob.get("table_records")
        if isinstance(records, list):
            filled = 0
            for row in records:
                if not isinstance(row, dict):
                    continue
                player = str(row.get("Player") or row.get("player") or "").strip()
                if player and player.lower() not in {"none", "nan", "<na>"}:
                    filled += 1
            return filled
    return 0


def _pick_best_state_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = -1
    best_ts = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        full = metrics.get(_FULL_SESSION_KEY)
        score = _full_session_workflow_score(full if isinstance(full, dict) else None)
        ts = str(row.get("updated_at") or "")
        if score > best_score or (score == best_score and ts > best_ts):
            best = dict(row)
            best["_workflow_score"] = score
            best_score = score
            best_ts = ts
    return best


def _merge_full_session_preserve_richer_draft(
    prior: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(incoming or {})
    try:
        from draft_archive_state import DELETED_DRAFT_ARCHIVE_IDS_KEY
    except ImportError:
        DELETED_DRAFT_ARCHIVE_IDS_KEY = "_deleted_draft_archive_ids"
    try:
        from workflow_persist_guard import (
            DRAFT_ARCHIVE_KEY,
            LEAGUE_CONTEXT_STATE_KEY,
            PROTECTED_WORKFLOW_PERSIST_KEYS,
            _deleted_context_ids_from_store,
            _merge_deleted_draft_archive_ids,
            count_draft_archives,
            count_league_contexts,
            workflow_richness,
        )

        tombstones = _merge_deleted_draft_archive_ids(prior, incoming)
        if tombstones:
            merged[DELETED_DRAFT_ARCHIVE_IDS_KEY] = tombstones

        prior_archives = prior.get(DRAFT_ARCHIVE_KEY)
        incoming_archives = merged.get(DRAFT_ARCHIVE_KEY)
        if isinstance(prior_archives, list) and isinstance(incoming_archives, list):
            if len(incoming_archives) < len(prior_archives):
                if tombstones:
                    merged[DRAFT_ARCHIVE_KEY] = incoming_archives
                else:
                    merged[DRAFT_ARCHIVE_KEY] = prior_archives
            elif workflow_richness(DRAFT_ARCHIVE_KEY, prior_archives) > workflow_richness(
                DRAFT_ARCHIVE_KEY, incoming_archives
            ):
                merged[DRAFT_ARCHIVE_KEY] = prior_archives
        elif isinstance(prior_archives, list) and incoming_archives is None:
            if workflow_richness(DRAFT_ARCHIVE_KEY, prior_archives) > 0 and not tombstones:
                merged[DRAFT_ARCHIVE_KEY] = prior_archives

        if tombstones and isinstance(merged.get(DRAFT_ARCHIVE_KEY), list):
            excluded = set(tombstones)
            merged[DRAFT_ARCHIVE_KEY] = [
                entry
                for entry in merged[DRAFT_ARCHIVE_KEY]
                if isinstance(entry, dict)
                and str(entry.get("draft_id") or "").strip() not in excluded
            ]

        prior_contexts = prior.get(LEAGUE_CONTEXT_STATE_KEY)
        incoming_contexts = merged.get(LEAGUE_CONTEXT_STATE_KEY)
        if isinstance(prior_contexts, dict) and isinstance(incoming_contexts, dict):
            deleted_context_ids = _deleted_context_ids_from_store(prior_contexts) | _deleted_context_ids_from_store(
                incoming_contexts
            )
            if count_league_contexts(incoming_contexts) < count_league_contexts(prior_contexts):
                if deleted_context_ids:
                    merged[LEAGUE_CONTEXT_STATE_KEY] = incoming_contexts
                else:
                    merged[LEAGUE_CONTEXT_STATE_KEY] = prior_contexts
            elif workflow_richness(LEAGUE_CONTEXT_STATE_KEY, prior_contexts) > workflow_richness(
                LEAGUE_CONTEXT_STATE_KEY, incoming_contexts
            ):
                merged[LEAGUE_CONTEXT_STATE_KEY] = prior_contexts
        elif isinstance(prior_contexts, dict) and incoming_contexts is None:
            if workflow_richness(LEAGUE_CONTEXT_STATE_KEY, prior_contexts) > 0:
                merged[LEAGUE_CONTEXT_STATE_KEY] = prior_contexts

        for key in PROTECTED_WORKFLOW_PERSIST_KEYS:
            if key in (DRAFT_ARCHIVE_KEY, LEAGUE_CONTEXT_STATE_KEY):
                continue
            prior_val = prior.get(key)
            incoming_val = merged.get(key)
            if workflow_richness(key, prior_val) > workflow_richness(key, incoming_val):
                merged[key] = prior_val
    except ImportError:
        pass
    prior_count = _draft_pick_count_from_session_blob(prior)
    incoming_count = _draft_pick_count_from_session_blob(incoming)
    if prior_count > incoming_count:
        for key in ("draft_room_state", "draft_room_table"):
            if isinstance(prior.get(key), dict):
                merged[key] = prior[key]
    return merged


def load_current_state_rows(**kwargs: Any) -> list[dict[str, Any]]:
    """Back-compat alias for tests and legacy callers."""
    params: dict[str, str] = {"select": "app,page,summary,metrics,updated_at", "order": "updated_at.desc", "limit": "20"}
    _apply_user_scope_params(params)
    rows = _request("GET", _TABLE_STATE, params=params, prefer="return=representation")
    return rows if isinstance(rows, list) else []


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _headers(cfg: SuiteCloudConfig, *, prefer: str = "return=minimal") -> dict[str, str]:
    return {
        "apikey": cfg.key,
        "Authorization": f"Bearer {cfg.key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def _egress(source: str):
    try:
        from suite_egress_trace import egress_source

        return egress_source(source)
    except ImportError:
        from contextlib import nullcontext

        return nullcontext()


_NO_GET_CACHE_TABLES = frozenset({"baseball_shared_draft_rooms", "baseball_shared_leagues"})
_TRANSIENT_SUPABASE_HTTP = frozenset({502, 503, 504})
_TRANSIENT_SUPABASE_MARKERS = (
    "PGRST002",
    "schema cache",
    "Could not query the database",
    "upstream connect error",
    "disconnect/reset",
    "reset before headers",
    "connection termination",
    "delayed connect error",
)
_DEFAULT_REQUEST_ATTEMPTS = 3
_DEFAULT_WRITE_REQUEST_ATTEMPTS = 5
_DEFAULT_REQUEST_BACKOFF_SEC = 0.5
_DEFAULT_REQUEST_TIMEOUT_SEC = 15
_MAX_REQUEST_TIMEOUT_SEC = 120
_DRAFT_LIBRARY_WRITE_TIMEOUT_SEC = 25.0


def estimate_metrics_payload_bytes(metrics: dict[str, Any] | None) -> int:
    try:
        return len(json.dumps(metrics or {}, default=str, sort_keys=True).encode("utf-8"))
    except Exception:
        return 0


def _request_timeout_sec(json_body: Any) -> float:
    if json_body is None:
        return float(_DEFAULT_REQUEST_TIMEOUT_SEC)
    try:
        body_bytes = len(json.dumps(json_body, default=str).encode("utf-8"))
    except Exception:
        body_bytes = 0
    # Large full_session uploads need more time on Streamlit Cloud → Supabase paths.
    extra = max(0, (body_bytes - 64 * 1024) // (64 * 1024)) * 15
    return float(min(_MAX_REQUEST_TIMEOUT_SEC, _DEFAULT_REQUEST_TIMEOUT_SEC + extra))


def is_transient_supabase_error(exc: BaseException) -> bool:
    """True for PostgREST schema-cache blips and other short-lived Supabase outages."""
    msg = str(exc or "")
    low = msg.lower()
    for code in _TRANSIENT_SUPABASE_HTTP:
        if f"({code})" in msg or f" {code}:" in msg:
            return True
    return any(marker.lower() in low for marker in _TRANSIENT_SUPABASE_MARKERS)


def _request(
    method: str,
    path: str,
    *,
    cfg: SuiteCloudConfig | None = None,
    params: dict[str, str] | None = None,
    json_body: Any = None,
    prefer: str = "return=minimal",
    max_attempts: int = _DEFAULT_REQUEST_ATTEMPTS,
    timeout_sec: float | None = None,
) -> Any:
    last_exc: RuntimeError | None = None
    attempts = max(1, int(max_attempts or 1))
    for attempt in range(attempts):
        try:
            return _request_once(
                method,
                path,
                cfg=cfg,
                params=params,
                json_body=json_body,
                prefer=prefer,
                timeout_sec=timeout_sec,
            )
        except RuntimeError as exc:
            last_exc = exc
            if attempt + 1 >= attempts or not is_transient_supabase_error(exc):
                raise
            time.sleep(_DEFAULT_REQUEST_BACKOFF_SEC * (2**attempt))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Supabase request failed")


def _request_once(
    method: str,
    path: str,
    *,
    cfg: SuiteCloudConfig | None = None,
    params: dict[str, str] | None = None,
    json_body: Any = None,
    prefer: str = "return=minimal",
    timeout_sec: float | None = None,
) -> Any:
    import requests  # lazy import — available in all suite apps

    config = cfg or get_cloud_config()
    if config is None:
        raise RuntimeError("Supabase is not configured")

    table = str(path or "").split("/", 1)[0]
    method_u = method.upper()
    cache_key = _cache_key(method_u, table, params)
    cached = False
    if method_u == "GET":
        bucket = _read_cache_bucket()
        hit = bucket.get(cache_key)
        if hit is not None:
            cached = True
            try:
                from suite_egress_trace import record_egress

                record_egress(
                    method=method_u,
                    path=table,
                    bytes_in=hit[0],
                    cached=True,
                )
            except ImportError:
                pass
            return hit[1]

    url = f"{config.url}/rest/v1/{path}"
    effective_timeout = (
        float(timeout_sec)
        if timeout_sec is not None
        else _request_timeout_sec(json_body)
    )
    try:
        response = requests.request(
            method,
            url,
            headers=_headers(config, prefer=prefer),
            params=params,
            json=json_body,
            timeout=effective_timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            f"Supabase {method} {path} timed out after {effective_timeout:.0f}s"
        ) from exc
    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(f"Supabase {method} {path} failed ({response.status_code}): {detail}")
    bytes_in = len(response.content or b"")
    bytes_out = 0
    if json_body is not None:
        try:
            bytes_out = len(json.dumps(json_body, default=str).encode("utf-8"))
        except Exception:
            bytes_out = 0
    try:
        from suite_egress_trace import record_egress

        record_egress(method=method_u, path=table, bytes_in=bytes_in, bytes_out=bytes_out, cached=False)
    except ImportError:
        pass
    if method_u != "GET":
        _invalidate_read_cache_for_table(table)
    if not response.content:
        return None
    try:
        parsed = response.json()
    except json.JSONDecodeError:
        parsed = None
    if method_u == "GET" and parsed is not None and table not in _NO_GET_CACHE_TABLES:
        _read_cache_bucket()[cache_key] = (bytes_in, parsed)
    return parsed


def normalize_app_key(app: str) -> str:
    cleaned = str(app or "").strip()
    if cleaned == "math":
        return "applied_intelligence"
    return cleaned


def _scoped_storage_app(app: str) -> str:
    """Workspace-scoped cloud key (Daniel keeps legacy unscoped)."""
    app_key = normalize_app_key(app)
    if "__" in app_key:
        return app_key
    try:
        from suite_workspace import scoped_cloud_app_id

        return scoped_cloud_app_id(app_key)
    except Exception:
        return app_key


def _workspace_storage_app_keys() -> list[str]:
    try:
        from suite_workspace import workspace_storage_app_keys

        return sorted(workspace_storage_app_keys())
    except Exception:
        return [normalize_app_key(app) for app in sorted(ACTIVE_APP_KEYS)]


def _scoped_user_id() -> str:
    from suite_user import get_account_user_id

    return get_account_user_id()


def _cloud_user_id() -> str | None:
    uid = _scoped_user_id()
    if not uid or uid.startswith("local:"):
        return None
    return uid


def _apply_user_scope_params(params: dict[str, str], *, include_legacy_null: bool = False) -> None:
    """
    Scope Supabase state rows to the current auth mode.

    Signed-in users read/write ONLY their ``user_id`` row so save, readback, and
    restore target the same blob. Legacy ``user_id=null`` rows are excluded from
    default loads (they caused false-positive readbacks on stale demo drafts).

    Set ``include_legacy_null=True`` only for explicit migration/diagnostic probes.
    """
    uid = _cloud_user_id()
    if uid:
        if include_legacy_null:
            params["or"] = f"(user_id.eq.{uid},user_id.is.null)"
        else:
            params["user_id"] = f"eq.{uid}"
    else:
        params["user_id"] = "is.null"


def _draft_count_from_row(row: dict[str, Any]) -> int:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    blob = metrics.get(_FULL_SESSION_KEY)
    if not isinstance(blob, dict):
        return 0
    try:
        from workflow_persist_guard import count_draft_archives

        return int(count_draft_archives(blob.get("draft_archive_teams")))
    except Exception:
        return 0


def inspect_cloud_state_rows(
    app: str,
    *,
    include_legacy_null: bool = False,
) -> dict[str, Any]:
    """Diagnostic: all scoped rows for one cloud app key + which row load would pick."""
    from suite_workspace import logical_storage_app_key

    storage_app = _scoped_storage_app(app)
    logical = logical_storage_app_key(storage_app)
    uid = _cloud_user_id() or ""
    out: dict[str, Any] = {
        "cloud_app_key": storage_app,
        "logical_app": logical,
        "scope_user_id": uid or None,
        "scope_mode": "signed_in_strict" if uid and not include_legacy_null else ("signed_in_or_legacy" if uid else "legacy_null_only"),
        "rows": [],
        "row_count": 0,
        "selected_row_user_id": None,
        "selected_row_updated_at": None,
        "selected_draft_count": 0,
    }
    if logical not in ACTIVE_APP_KEYS:
        out["error"] = "inactive_app"
        return out
    rows = _fetch_state_rows_for_storage_app(
        storage_app,
        select="app,user_id,page,summary,metrics,updated_at",
        egress_label="inspect_cloud_state_rows",
        limit="20",
        include_legacy_null=include_legacy_null,
    )
    row_summaries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        summary = {
            "user_id": row.get("user_id"),
            "updated_at": str(row.get("updated_at") or "")[:19],
            "page": str(row.get("page") or ""),
            "draft_count": _draft_count_from_row(row),
        }
        try:
            from workflow_persist_guard import summarize_cloud_workflow_blob

            metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
            blob = metrics.get(_FULL_SESSION_KEY)
            wf = summarize_cloud_workflow_blob(blob if isinstance(blob, dict) else None)
            summary["draft_ids"] = list(wf.get("draft_ids") or [])
            summary["league_context_count"] = int(wf.get("league_context_count") or 0)
        except Exception:
            summary["draft_ids"] = []
            summary["league_context_count"] = 0
        row_summaries.append(summary)
    out["rows"] = row_summaries
    out["row_count"] = len(row_summaries)
    best = _pick_best_state_row([r for r in rows if isinstance(r, dict)])
    if isinstance(best, dict):
        out["selected_row_user_id"] = best.get("user_id")
        out["selected_row_updated_at"] = str(best.get("updated_at") or "")[:19]
        out["selected_draft_count"] = _draft_count_from_row(best)
    return out


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


_supabase_client: Any | None = None


def get_supabase_client() -> Any:
    """
    Lazy Supabase Python client for Auth API (``client.auth``).

    Requires ``supabase`` package and ``supabase_url`` + auth API key in secrets.
    """
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    cfg = get_cloud_config()
    if cfg is None:
        raise RuntimeError(
            "Supabase is not configured — set supabase_url and supabase_key under [suite_activity]."
        )
    auth_key = get_auth_api_key()
    if not auth_key:
        raise RuntimeError(
            "Supabase Auth key missing — set supabase_anon_key under [suite_activity] "
            "(or SUITE_SUPABASE_ANON_KEY env)."
        )
    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError(
            "Python package 'supabase' is not installed — add supabase>=2.0.0 to requirements.txt."
        ) from exc
    _supabase_client = create_client(cfg.url, auth_key)
    return _supabase_client


def reset_supabase_client_cache() -> None:
    global _supabase_client
    _supabase_client = None


def append_event(
    app: str,
    event: str,
    *,
    page: str = "",
    metrics: dict[str, Any] | None = None,
) -> str:
    app_key = _scoped_storage_app(app)
    if not app_key:
        return ""
    try:
        from suite_activity_namespace import stamp_activity_metrics

        stamped = stamp_activity_metrics(metrics)
    except ImportError:
        stamped = dict(metrics or {})
    body: dict[str, Any] = {
        "app": app_key,
        "event": event,
        "page": page or "",
        "timestamp": _now_iso(),
        "metrics": stamped,
    }
    uid = _cloud_user_id()
    if uid:
        body["user_id"] = uid
    rows = _request(
        "POST",
        _TABLE_EVENTS,
        json_body=body,
        prefer="return=representation",
    )
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return str(rows[0].get("id") or "")
    if isinstance(rows, dict):
        return str(rows.get("id") or "")
    return ""


def save_current_state(
    app: str,
    *,
    page: str = "",
    summary: str = "",
    metrics: dict[str, Any] | None = None,
) -> None:
    logical_app = normalize_app_key(app)
    app_key = _scoped_storage_app(app)
    if logical_app not in ACTIVE_APP_KEYS:
        return
    body: dict[str, Any] = {
        "app": app_key,
        "page": page or "",
        "summary": summary or "",
        "metrics": _merge_state_metrics(app_key, metrics),
        "updated_at": _now_iso(),
    }
    uid = _cloud_user_id()
    if uid:
        body["user_id"] = uid
    _request(
        "POST",
        _TABLE_STATE,
        json_body=body,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def save_current_state_with_result(
    app: str,
    *,
    page: str = "",
    summary: str = "",
    metrics: dict[str, Any] | None = None,
    skip_metrics_merge: bool = False,
    direct_upsert: bool = False,
    request_timeout_sec: float | None = None,
    write_attempts: int | None = None,
) -> dict[str, Any]:
    """Persist app state and report write mode (PATCH when a row already exists)."""
    logical_app = normalize_app_key(app)
    app_key = _scoped_storage_app(app)
    if logical_app not in ACTIVE_APP_KEYS:
        return {"ok": False, "write_mode": "skipped", "error": "inactive_app"}
    if skip_metrics_merge or direct_upsert:
        merged_metrics = dict(metrics or {})
    else:
        merged_metrics = _merge_state_metrics(app_key, metrics)
    body: dict[str, Any] = {
        "app": app_key,
        "page": page or "",
        "summary": summary or "",
        "metrics": merged_metrics,
        "updated_at": _now_iso(),
    }
    uid = _cloud_user_id()
    if uid:
        body["user_id"] = uid
    payload_bytes = estimate_metrics_payload_bytes(merged_metrics)
    write_mode = "post"
    attempts = max(1, int(write_attempts or _DEFAULT_WRITE_REQUEST_ATTEMPTS))
    timeout_sec = request_timeout_sec

    def _write_post() -> None:
        _request(
            "POST",
            _TABLE_STATE,
            json_body=body,
            prefer="resolution=merge-duplicates,return=minimal",
            max_attempts=attempts,
            timeout_sec=timeout_sec,
        )

    def _write_patch(patch_params: dict[str, str]) -> None:
        _request(
            "PATCH",
            _TABLE_STATE,
            params=patch_params,
            json_body=body,
            prefer="return=minimal",
            max_attempts=attempts,
            timeout_sec=timeout_sec,
        )

    try:
        if direct_upsert:
            write_mode = "direct_upsert"
            _write_post()
            return {
                "ok": True,
                "write_mode": write_mode,
                "payload_bytes": payload_bytes,
            }
        params: dict[str, str] = _query_params_for_storage_app(app_key, select="app,user_id", limit="20")
        try:
            rows = _request("GET", _TABLE_STATE, params=params, prefer="return=representation")
        except Exception as exc:
            if not is_transient_supabase_error(exc):
                raise
            # PostgREST schema-cache blips can fail read-before-write while an
            # upsert succeeds. Avoid letting the diagnostic GET block durable saves.
            write_mode = "direct_upsert_after_get_retry"
            _write_post()
            return {
                "ok": True,
                "write_mode": write_mode,
                "payload_bytes": payload_bytes,
                "warning": f"prewrite_get_transient:{exc}",
            }
        if isinstance(rows, list) and rows:
            patch_params = {"app": f"eq.{app_key}"}
            if uid:
                scoped = [r for r in rows if isinstance(r, dict) and str(r.get("user_id") or "") == uid]
                if scoped:
                    patch_params["user_id"] = f"eq.{uid}"
                else:
                    patch_params["user_id"] = "is.null"
            else:
                patch_params["user_id"] = "is.null"
            _write_patch(patch_params)
            write_mode = "patch"
        else:
            _write_post()
        return {"ok": True, "write_mode": write_mode, "payload_bytes": payload_bytes}
    except Exception as exc:
        return {
            "ok": False,
            "write_mode": write_mode,
            "payload_bytes": payload_bytes,
            "error": str(exc),
        }


def upsert_resume_item(
    app: str,
    item_key: str,
    *,
    title: str,
    subtitle: str = "",
    action_url: str = "",
) -> None:
    logical_app = normalize_app_key(app)
    app_key = _scoped_storage_app(app)
    key = str(item_key or "").strip()
    title_clean = str(title or "").strip()
    if not app_key or not key or not title_clean:
        return
    if logical_app not in ACTIVE_APP_KEYS:
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
    app_key = _scoped_storage_app(app)
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
    app_key = _scoped_storage_app(app)
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
    from suite_workspace import logical_storage_app_key, workspace_storage_app_keys

    allowed = workspace_storage_app_keys()
    params: dict[str, str] = {
        "select": "app,event,page,timestamp,metrics",
        "order": "timestamp.desc",
        "limit": str(limit),
    }
    _apply_user_scope_params(params)
    if allowed:
        params["app"] = f"in.({','.join(sorted(allowed))})"
    with _egress("load_events"):
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
        storage_app = str(row.get("app") or "")
        if storage_app not in allowed:
            continue
        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        raw_ts = str(row.get("timestamp") or "")
        out.append(
            {
                "app": logical_storage_app_key(storage_app),
                "event": str(row.get("event") or ""),
                "page": str(row.get("page") or ""),
                "timestamp": normalize_timestamp_iso(raw_ts) or raw_ts,
                "metrics": metrics,
            }
        )
    return out


def load_current_states(*, include_metrics: bool = False) -> dict[str, dict[str, Any]]:
    """
    Load current app states for active workspace.

    Default is summary-only (no metrics/full_session) to limit Supabase egress.
    Pass ``include_metrics=True`` only when shallow resume hints inside metrics are required.
    """
    if not include_metrics:
        return load_current_states_summary()
    from suite_workspace import logical_storage_app_key, workspace_storage_app_keys

    allowed = workspace_storage_app_keys()
    params: dict[str, str] = {"select": "app,page,summary,metrics,updated_at"}
    if allowed:
        params["app"] = f"in.({','.join(sorted(allowed))})"
    _apply_user_scope_params(params)
    with _egress("load_current_states"):
        rows = _request(
            "GET",
            _TABLE_STATE,
            params=params,
            prefer="return=representation",
        )
    if not isinstance(rows, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        storage_app = str(row.get("app") or "")
        if storage_app not in allowed:
            continue
        logical = logical_storage_app_key(storage_app)
        if logical not in ACTIVE_APP_KEYS:
            continue
        grouped.setdefault(logical, []).append(row)
    for logical, app_rows in grouped.items():
        best_row = _pick_best_state_row(app_rows) or app_rows[-1]
        out[logical] = _row_to_state_dict(best_row, logical=logical)
    return out


def load_active_resume_items(
    limit: int = 8,
    *,
    app: str | None = None,
    exclude_hof_from_recent_ami: bool = False,
) -> list[dict[str, Any]]:
    from suite_workspace import logical_storage_app_key

    app_keys = [_scoped_storage_app(app)] if app else _workspace_storage_app_keys()
    if not app_keys:
        return []
    params: dict[str, str] = {"select": "app,item_key,title,subtitle,action_url,updated_at"}
    _apply_user_scope_params(params)
    with _egress("load_active_resume_items"):
        rows = _request(
            "GET",
            _TABLE_RESUME,
            params={
                **params,
                "valid": "eq.true",
                "order": "updated_at.desc",
                "limit": str(limit),
                "app": f"in.({','.join(app_keys)})",
            },
            prefer="return=representation",
        )
    if not isinstance(rows, list):
        return []
    items = [
        {
            "app": logical_storage_app_key(str(row.get("app") or "")),
            "item_key": str(row.get("item_key") or ""),
            "title": str(row.get("title") or ""),
            "subtitle": str(row.get("subtitle") or ""),
            "action_url": str(row.get("action_url") or ""),
            "updated_at": str(row.get("updated_at") or "")[:19],
        }
        for row in rows
        if isinstance(row, dict)
    ]
    if exclude_hof_from_recent_ami:
        try:
            from suite_analytical_question import filter_resume_items_for_recent_ami

            return filter_resume_items_for_recent_ami(items)[:limit]
        except ImportError:
            pass
    return items


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
    app_key = _scoped_storage_app(app)
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


_AUTH_BROWSER_APP = "_auth_browser"
_AUTH_SESSION_ITEM_TYPE = "browser_session"


def save_browser_auth_session(
    session_id: str,
    *,
    user_id: str,
    tokens: dict[str, Any],
) -> None:
    """Persist refreshable auth tokens server-side; URL holds opaque session id only."""
    sid = str(session_id or "").strip()
    uid = str(user_id or "").strip()
    access = str((tokens or {}).get("access_token") or "").strip()
    refresh = str((tokens or {}).get("refresh_token") or "").strip()
    if not sid or not uid or not access or not refresh:
        return
    payload = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int((tokens or {}).get("expires_at") or 0),
    }
    row_body = {
        "user_id": uid,
        "app": _AUTH_BROWSER_APP,
        "item_type": _AUTH_SESSION_ITEM_TYPE,
        "item_key": sid,
        "title": "Browser auth session",
        "payload": payload,
        "valid": True,
        "updated_at": _now_iso(),
    }
    patch_body = {
        "title": "Browser auth session",
        "payload": payload,
        "valid": True,
        "updated_at": _now_iso(),
    }
    patch_params = {
        "user_id": f"eq.{uid}",
        "app": f"eq.{_AUTH_BROWSER_APP}",
        "item_type": f"eq.{_AUTH_SESSION_ITEM_TYPE}",
        "item_key": f"eq.{sid}",
    }
    try:
        _request(
            "POST",
            _TABLE_SAVED,
            params={"on_conflict": _SAVED_ITEM_CONFLICT_COLS},
            json_body=row_body,
            prefer="resolution=merge-duplicates,return=minimal",
        )
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


def load_browser_auth_session(session_id: str) -> dict[str, Any] | None:
    """Load token bundle by opaque browser session id (capability URL)."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with _egress("load_browser_auth_session"):
        rows = _request(
            "GET",
            _TABLE_SAVED,
            params={
                "select": "payload,updated_at",
                "app": f"eq.{_AUTH_BROWSER_APP}",
                "item_type": f"eq.{_AUTH_SESSION_ITEM_TYPE}",
                "item_key": f"eq.{sid}",
                "valid": "eq.true",
                "limit": "1",
            },
            prefer="return=representation",
        )
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    payload = rows[0].get("payload")
    if not isinstance(payload, dict):
        return None
    access = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or "").strip()
    if not access or not refresh:
        return None
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(payload.get("expires_at") or 0),
    }


def invalidate_browser_auth_session(session_id: str) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    _request(
        "PATCH",
        _TABLE_SAVED,
        params={
            "app": f"eq.{_AUTH_BROWSER_APP}",
            "item_type": f"eq.{_AUTH_SESSION_ITEM_TYPE}",
            "item_key": f"eq.{sid}",
        },
        json_body={"valid": False, "updated_at": _now_iso()},
        prefer="return=minimal",
    )


def invalidate_saved_item(app: str, item_type: str, item_key: str) -> None:
    app_key = _scoped_storage_app(app)
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
    from suite_workspace import logical_storage_app_key

    allowed = set(_workspace_storage_app_keys())
    params: dict[str, str] = {
        "select": "app,item_type,item_key,title,payload,updated_at",
        "user_id": f"eq.{_scoped_user_id()}",
        "valid": "eq.true",
        "order": "updated_at.desc",
        "limit": str(limit),
    }
    if app:
        params["app"] = f"eq.{_scoped_storage_app(app)}"
    elif allowed:
        params["app"] = f"in.({','.join(sorted(allowed))})"
    if item_type:
        params["item_type"] = f"eq.{item_type}"
    rows = _request("GET", _TABLE_SAVED, params=params, prefer="return=representation")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        storage_app = str(row.get("app") or "")
        if not app and storage_app not in allowed:
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        out.append(
            {
                "app": logical_storage_app_key(storage_app),
                "item_type": str(row.get("item_type") or ""),
                "item_key": str(row.get("item_key") or ""),
                "title": str(row.get("title") or ""),
                "payload": payload,
                "updated_at": str(row.get("updated_at") or "")[:19],
            }
        )
    return out


def load_saved_item_by_key(
    item_type: str,
    item_key: str,
    *,
    app: str | None = None,
) -> dict[str, Any] | None:
    """
    Fetch one saved item by exact ``item_key`` (not a recent-items scan).

    When ``app`` is omitted, searches all workspace-scoped app keys for the user,
    then falls back to an app-agnostic query so cross-app blobs still resolve.
    """
    from suite_workspace import logical_storage_app_key

    key = str(item_key or "").strip()
    itype = str(item_type or "").strip()
    if not key or not itype:
        return None
    uid = _scoped_user_id()
    if not uid:
        return None

    def _fetch(*, app_filter: str | None) -> dict[str, Any] | None:
        params: dict[str, str] = {
            "select": "app,item_type,item_key,title,payload,updated_at",
            "user_id": f"eq.{uid}",
            "item_type": f"eq.{itype}",
            "item_key": f"eq.{key}",
            "valid": "eq.true",
            "limit": "1",
        }
        if app_filter:
            params["app"] = f"eq.{app_filter}"
        rows = _request("GET", _TABLE_SAVED, params=params, prefer="return=representation")
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        if not isinstance(row, dict):
            return None
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        storage_app = str(row.get("app") or "")
        return {
            "app": logical_storage_app_key(storage_app),
            "storage_app": storage_app,
            "item_type": str(row.get("item_type") or ""),
            "item_key": str(row.get("item_key") or ""),
            "title": str(row.get("title") or ""),
            "payload": payload,
            "updated_at": str(row.get("updated_at") or "")[:19],
        }

    if app:
        scoped = _scoped_storage_app(app)
        hit = _fetch(app_filter=scoped)
        if hit:
            return hit
        base = str(app or "").strip()
        if base and scoped != base:
            hit = _fetch(app_filter=base)
            if hit:
                return hit
        return None

    for storage_app in sorted(_workspace_storage_app_keys()):
        hit = _fetch(app_filter=storage_app)
        if hit:
            return hit
    return _fetch(app_filter=None)


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
) -> str:
    # Applied-math insight events must not replace metrics.full_session (Test D portfolio).
    if str(event or "").strip() == "applied_math_insight":
        event_id = append_event(app, event, page=page, metrics=metrics)
        if resume_key and resume_title:
            upsert_resume_item(
                app,
                resume_key,
                title=resume_title,
                subtitle=resume_subtitle,
                action_url=action_url,
            )
        return event_id
    if summary or page or metrics:
        save_current_state(app, page=page, summary=summary, metrics=metrics)
    if resume_key and resume_title:
        upsert_resume_item(
            app,
            resume_key,
            title=resume_title,
            subtitle=resume_subtitle,
            action_url=action_url,
        )
    return append_event(app, event, page=page, metrics=metrics)
