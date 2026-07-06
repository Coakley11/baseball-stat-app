"""Health probes for ``suite_app_current_state`` (PostgREST reachability + write path)."""

from __future__ import annotations

import json
import time
from typing import Any

_TABLE_STATE = "suite_app_current_state"
_PROBE_METRICS_KEY = "_suite_health_probe"
_DEFAULT_SIZE_LADDER_BYTES = (1024, 32 * 1024, 128 * 1024, 512 * 1024)


def estimate_json_bytes(payload: Any) -> int:
    try:
        return len(json.dumps(payload, default=str, sort_keys=True).encode("utf-8"))
    except Exception:
        return 0


def probe_suite_app_current_state_health(
    *,
    run_write_probe: bool = True,
    run_size_ladder: bool = False,
    size_ladder_bytes: tuple[int, ...] = _DEFAULT_SIZE_LADDER_BYTES,
    scoped_app_key: str = "",
) -> dict[str, Any]:
    """
    Check PostgREST / ``suite_app_current_state`` health from this runtime.

    Returns structured diagnostics suitable for in-app panels and CLI scripts.
    """
    out: dict[str, Any] = {
        "configured": False,
        "ping_ok": False,
        "table_reachable": False,
        "minimal_write_ok": False,
        "minimal_write_mode": None,
        "size_ladder": [],
        "payload_bytes_hint": None,
        "latency_ms": {},
        "status_code": None,
        "error": None,
        "detail": "",
        "user_message": "",
        "likely_cause": "",
    }
    try:
        from suite_storage_config import cloud_storage_enabled, get_cloud_config
    except ImportError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["user_message"] = "Cloud storage config module unavailable."
        return out

    if not cloud_storage_enabled():
        out["error"] = "cloud_storage_disabled"
        out["user_message"] = "Supabase is not configured in this deployment."
        return out

    cfg = get_cloud_config()
    if cfg is None:
        out["error"] = "cloud_config_missing"
        out["user_message"] = "Supabase URL/key missing under [suite_activity]."
        return out

    out["configured"] = True
    out["supabase_host"] = str(getattr(cfg, "url", "") or "").split("//", 1)[-1].split("/", 1)[0]

    try:
        from suite_storage_supabase import ping as storage_ping

        t0 = time.perf_counter()
        out["ping_ok"] = bool(storage_ping())
        out["latency_ms"]["ping"] = int((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        out["detail"] = str(exc)[:2000]
        out["error"] = f"ping_failed:{type(exc).__name__}"
        out["user_message"] = "Supabase ping failed — project may be paused or PostgREST unreachable."
        out["likely_cause"] = _classify_supabase_error(str(exc))
        return out

    import suite_storage_supabase as storage

    t0 = time.perf_counter()
    try:
        rows = storage._request(  # noqa: SLF001 — intentional health probe
            "GET",
            _TABLE_STATE,
            params={"select": "app,updated_at", "limit": "1"},
            prefer="return=representation",
            max_attempts=1,
        )
        out["table_reachable"] = isinstance(rows, list)
        out["latency_ms"]["get_table"] = int((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        out["latency_ms"]["get_table"] = int((time.perf_counter() - t0) * 1000)
        out["detail"] = str(exc)[:2000]
        out["error"] = f"get_table_failed:{type(exc).__name__}"
        out["user_message"] = "Could not read suite_app_current_state — PostgREST or DB may be unhealthy."
        out["likely_cause"] = _classify_supabase_error(str(exc))
        return out

    if not run_write_probe:
        out["user_message"] = "Table reachable (read probe only)."
        return out

    app_key = str(scoped_app_key or "").strip()
    if not app_key:
        try:
            from suite_workspace import scoped_cloud_app_id

            app_key = scoped_cloud_app_id("baseball")
        except Exception:
            app_key = "baseball"

    minimal_body: dict[str, Any] = {
        "app": app_key,
        "page": "",
        "summary": "health_probe",
        "metrics": {_PROBE_METRICS_KEY: {"ts": time.time(), "probe": "minimal"}},
        "updated_at": storage._now_iso(),  # noqa: SLF001
    }
    uid = storage._cloud_user_id()  # noqa: SLF001
    if uid:
        minimal_body["user_id"] = uid

    t0 = time.perf_counter()
    try:
        result_fn = getattr(storage, "save_current_state_with_result", None)
        if callable(result_fn):
            result = result_fn(
                app_key,
                page="",
                summary="health_probe",
                metrics=minimal_body["metrics"],
                skip_metrics_merge=True,
            )
            out["minimal_write_ok"] = bool(isinstance(result, dict) and result.get("ok"))
            out["minimal_write_mode"] = (result or {}).get("write_mode")
            if not out["minimal_write_ok"]:
                out["detail"] = str((result or {}).get("error") or "")[:2000]
        else:
            storage.save_current_state(
                app_key,
                page="",
                summary="health_probe",
                metrics=minimal_body["metrics"],
            )
            out["minimal_write_ok"] = True
            out["minimal_write_mode"] = "post"
        out["latency_ms"]["minimal_write"] = int((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        out["latency_ms"]["minimal_write"] = int((time.perf_counter() - t0) * 1000)
        out["detail"] = str(exc)[:2000]
        out["error"] = f"minimal_write_failed:{type(exc).__name__}"
        out["user_message"] = "Minimal upsert to suite_app_current_state failed."
        out["likely_cause"] = _classify_supabase_error(str(exc))
        return out

    if run_size_ladder:
        ladder: list[dict[str, Any]] = []
        for size in size_ladder_bytes:
            pad = "x" * max(0, int(size) - 64)
            blob = {_PROBE_METRICS_KEY: {"probe": "size_ladder", "pad": pad}}
            entry: dict[str, Any] = {"target_bytes": int(size), "actual_bytes": estimate_json_bytes(blob)}
            t1 = time.perf_counter()
            try:
                res = storage.save_current_state_with_result(
                    app_key,
                    page="",
                    summary="health_probe_size",
                    metrics=blob,
                    skip_metrics_merge=True,
                )
                entry["ok"] = bool(isinstance(res, dict) and res.get("ok"))
                entry["write_mode"] = (res or {}).get("write_mode")
                if not entry["ok"]:
                    entry["error"] = str((res or {}).get("error") or "")[:500]
            except Exception as exc:
                entry["ok"] = False
                entry["error"] = str(exc)[:500]
            entry["latency_ms"] = int((time.perf_counter() - t1) * 1000)
            ladder.append(entry)
            if not entry.get("ok"):
                break
        out["size_ladder"] = ladder

    if out["minimal_write_ok"]:
        out["user_message"] = "suite_app_current_state reachable; minimal upsert succeeded."
        if run_size_ladder and out["size_ladder"]:
            failed = next((row for row in out["size_ladder"] if not row.get("ok")), None)
            if failed:
                out["likely_cause"] = "payload_size"
                out["user_message"] = (
                    f"Minimal write OK but POST failed at ~{failed.get('actual_bytes')} bytes — "
                    "large full_session payloads may be reset by the gateway."
                )
    return out


def _classify_supabase_error(message: str) -> str:
    low = str(message or "").lower()
    if "pgrst002" in low or "schema cache" in low:
        return "postgrest_schema_cache"
    if "upstream connect error" in low or "disconnect/reset" in low or "reset before headers" in low:
        return "gateway_upstream_reset"
    if "(503)" in message or " 503:" in low:
        return "service_unavailable_503"
    if "(504)" in message or "timed out" in low or "timeout" in low:
        return "timeout"
    if "connection" in low and "error" in low:
        return "connection_error"
    return "unknown"


def classify_cloud_save_failure(*, error: str, payload_bytes: int, minimal_write_ok: bool | None) -> str:
    """Suggest root cause from save error + probe context."""
    kind = _classify_supabase_error(error)
    if minimal_write_ok is False:
        return "supabase_project_unhealthy"
    if minimal_write_ok is True and payload_bytes > 256 * 1024:
        if kind in {"gateway_upstream_reset", "timeout", "service_unavailable_503"}:
            return "payload_too_large_or_slow"
    if kind == "postgrest_schema_cache":
        return "postgrest_schema_cache"
    if kind == "gateway_upstream_reset":
        return "supabase_gateway_reset"
    return kind
