"""Live diagnostic wrapper integrity + authoritative server row merge (harness + app)."""

from __future__ import annotations

from typing import Any

ABORTED_S3_SERVER_WRAPPER_INTEGRITY = "ABORTED_S3_SERVER_WRAPPER_INTEGRITY"

_WRAPPER_SPECS: tuple[tuple[str, str, str], ...] = (
    ("streamlit.runtime.runtime", "Runtime", "handle_backmsg", "_solo_runtime_backmsg_wrapped"),
    ("streamlit.runtime.app_session", "AppSession", "handle_backmsg", "_solo_appsession_backmsg_wrapped"),
    ("streamlit.runtime.app_session", "AppSession", "request_rerun", "_solo_appsession_rerun_wrapped"),
    ("streamlit.runtime.state.safe_session_state", "SafeSessionState", "on_script_will_rerun", "_solo_s3_safe_wrapped"),
    ("streamlit.runtime.state.session_state", "SessionState", "on_script_will_rerun", "_solo_s3_wrapped"),
    ("streamlit.runtime.state.session_state", "SessionState", "set_widgets_from_proto", "_solo_s3_wrapped"),
)


def _load_class(module_path: str, class_name: str) -> type | None:
    try:
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, class_name, None)
    except Exception:
        return None


def live_server_wrapper_integrity_snapshot() -> dict[str, Any]:
    wrappers: dict[str, Any] = {}
    for mod_path, cls_name, method_name, sentinel in _WRAPPER_SPECS:
        key = f"{cls_name}.{method_name}"
        cls = _load_class(mod_path, cls_name)
        entry: dict[str, Any] = {"expected_sentinel": sentinel, "wrapped": False}
        if cls is None:
            entry["error"] = "class_import_failed"
            wrappers[key] = entry
            continue
        fn = getattr(cls, method_name, None)
        entry["callable"] = getattr(fn, "__name__", str(fn))
        entry["callable_module"] = getattr(fn, "__module__", "")
        entry["wrapped"] = bool(getattr(fn, sentinel, False))
        wrappers[key] = entry
    ok = all(bool(w.get("wrapped")) for w in wrappers.values())
    return {"server_wrapper_integrity_ok": ok, "wrappers": wrappers}


def merge_authoritative_server_rows(
    *,
    module_rows: list[dict[str, Any]] | None = None,
    local_rows: list[dict[str, Any]] | None = None,
    critical_rows: list[dict[str, Any]] | None = None,
    ingress_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sources: list[tuple[str, list[dict[str, Any]]]] = [
        ("module", list(module_rows or [])),
        ("local", list(local_rows or [])),
        ("critical", list(critical_rows or [])),
        ("ingress", list(ingress_rows or [])),
    ]
    by_id: dict[str, dict[str, Any]] = {}
    source_counts: dict[str, int] = {}
    duplicate_ids: list[str] = []
    for src_name, rows in sources:
        source_counts[src_name] = len(rows)
        for r in rows:
            if not isinstance(r, dict):
                continue
            eid = str(r.get("event_id") or "")
            if not eid:
                eid = f"{src_name}:{r.get('phase')}:{r.get('ts')}"
            if eid in by_id:
                duplicate_ids.append(eid)
                continue
            row = dict(r)
            row["_merge_source"] = src_name
            by_id[eid] = row
    merged = sorted(by_id.values(), key=lambda r: float(r.get("ts") or 0))
    ts_vals = [float(r.get("ts") or 0) for r in merged if r.get("ts") is not None]
    phase_counts: dict[str, int] = {}
    for r in merged:
        ph = str(r.get("phase") or "")
        phase_counts[ph] = phase_counts.get(ph, 0) + 1
    return {
        "module_row_count": source_counts.get("module", 0),
        "local_row_count": source_counts.get("local", 0),
        "critical_row_count": source_counts.get("critical", 0),
        "ingress_row_count": source_counts.get("ingress", 0),
        "merged_row_count": len(merged),
        "duplicate_event_id_count": len(duplicate_ids),
        "oldest_ts": min(ts_vals) if ts_vals else None,
        "newest_ts": max(ts_vals) if ts_vals else None,
        "phase_counts": phase_counts,
        "merged_rows": merged,
        "event_ids": [str(r.get("event_id") or "") for r in merged][-64:],
    }
