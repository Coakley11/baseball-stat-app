"""Out-of-band S3 diagnostic JSON snapshots via Streamlit static serving (diagnostic-only)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

S3_OOB_IMPL_REV = "stage1_s3_oob_snapshot_v2"
S3_OOB_TOKEN_SESSION_KEY = "_stage1_s3_oob_diagnostic_token"
S3_OOB_CHANNEL_SESSION_KEY = "_stage1_s3_oob_channel"

_OOB_LOCK = threading.Lock()
_OOB_GENERATION_BY_TOKEN: dict[str, int] = {}
_STREAMLIT_SESSION_TO_TOKEN: dict[str, str] = {}
_MAX_MODULE_ROWS = 48
_MAX_UNROUTED_ROWS = 32


def oob_snapshot_root() -> Path:
    module_root = Path(__file__).resolve().parent
    candidates = (
        module_root / "static" / "s3_oob",
        Path("/mount/src/baseball-stat-app/static/s3_oob"),
        Path.cwd() / "static" / "s3_oob",
    )
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    fallback = module_root / "static" / "s3_oob"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def static_url_path_for_token(token: str) -> str:
    safe = str(token or "").strip()[:32]
    return f"/app/static/s3_oob/{safe}.json"


def snapshot_path_for_token(token: str) -> Path:
    safe = str(token or "").strip()[:32]
    return oob_snapshot_root() / f"{safe}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _next_generation(token: str) -> int:
    with _OOB_LOCK:
        gen = int(_OOB_GENERATION_BY_TOKEN.get(token) or 0) + 1
        _OOB_GENERATION_BY_TOKEN[token] = gen
        return gen


def current_generation(token: str) -> int:
    with _OOB_LOCK:
        return int(_OOB_GENERATION_BY_TOKEN.get(str(token or "").strip()[:32], 0) or 0)


def _session_mapping(session: Any) -> MutableMapping[str, Any] | None:
    """Narrow helper: dict or SessionStateProxy (MutableMapping), not arbitrary objects."""
    if isinstance(session, MutableMapping):
        return session
    return None


def register_oob_channel(streamlit_session_id: str, session: dict[str, Any] | None = None) -> dict[str, Any]:
    sid = str(streamlit_session_id or "").strip()[:64]
    if not sid:
        return {"registered": False}
    mapping = _session_mapping(session)
    token = ""
    if mapping is not None:
        token = str(mapping.get(S3_OOB_TOKEN_SESSION_KEY) or "").strip()[:32]
    if not token:
        token = uuid.uuid4().hex[:16]
    with _OOB_LOCK:
        _STREAMLIT_SESSION_TO_TOKEN[sid] = token
    if mapping is not None:
        mapping[S3_OOB_TOKEN_SESSION_KEY] = token
    channel = {
        "registered": True,
        "streamlit_session_id": sid,
        "diagnostic_token": token,
        "static_url_path": static_url_path_for_token(token),
        "snapshot_filename": f"{token}.json",
        "impl_rev": S3_OOB_IMPL_REV,
    }
    if mapping is not None:
        mapping[S3_OOB_CHANNEL_SESSION_KEY] = dict(channel)
    return channel


def resolve_token_for_streamlit_session(streamlit_session_id: str) -> str:
    sid = str(streamlit_session_id or "").strip()[:64]
    with _OOB_LOCK:
        return str(_STREAMLIT_SESSION_TO_TOKEN.get(sid) or "")[:32]


def build_oob_snapshot_payload(
    streamlit_session_id: str,
    *,
    diagnostic_token: str,
    snapshot_generation: int,
    publish_source: str,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from live_draft_stage1_s3_process_global_diag import (
        build_latest_ingress_summaries,
        critical_ledger_by_phase,
        critical_ledger_rows,
        ledger_totals_for_session,
        module_ledger_rows,
        unrouted_ledger_export,
    )
    from live_draft_stage1_server_evidence import live_server_wrapper_integrity_snapshot

    sid = str(streamlit_session_id or "").strip()[:64]
    token = str(diagnostic_token or "").strip()[:32]
    module_rows = list(module_ledger_rows(sid))[-_MAX_MODULE_ROWS:]
    # Per-phase critical tails are already memory-bounded. Do not re-truncate with a
    # mixed 48-row window that request_rerun floods can evict downstream phases from.
    by_phase = critical_ledger_by_phase(sid)
    critical_rows = list(critical_ledger_rows(sid))
    unrouted = unrouted_ledger_export()
    unrouted_rows = list(unrouted.get("rows") or [])[-_MAX_UNROUTED_ROWS:]
    totals = ledger_totals_for_session(sid)
    summaries = build_latest_ingress_summaries(sid)
    integrity = live_server_wrapper_integrity_snapshot()
    routing_rows = [
        {
            "event_id": r.get("event_id"),
            "phase": r.get("phase"),
            "routing_sid": r.get("routing_sid"),
            "routing_source": r.get("routing_source"),
            "runtime_sid": r.get("runtime_sid"),
            "appsession_sid": r.get("appsession_sid"),
            "ctx_streamlit_session_id": r.get("ctx_streamlit_session_id"),
            "lookup_object_id": r.get("lookup_object_id"),
            "routing_ids_agree": r.get("routing_ids_agree"),
        }
        for r in module_rows
        if r.get("routing_source") or r.get("routing_sid")
    ][-16:]
    diagnostic_run_id = ""
    script_run_seq = None
    mapping = _session_mapping(session)
    if mapping is not None:
        diagnostic_run_id = str(
            mapping.get("diagnostic_run_id") or mapping.get("application_diagnostic_run_id") or ""
        )[:64]
        try:
            from live_draft_stage1_pause_sibling_probe import _full_app_run_seq

            script_run_seq = int(_full_app_run_seq(mapping))
        except Exception:
            script_run_seq = mapping.get("_full_app_run_seq")
    return {
        "impl_rev": S3_OOB_IMPL_REV,
        "snapshot_generation": int(snapshot_generation),
        "snapshot_server_ts": time.time(),
        "streamlit_session_id": sid,
        "diagnostic_token": token,
        "publish_source": str(publish_source or "")[:64],
        "diagnostic_run_id": diagnostic_run_id,
        "script_run_seq": script_run_seq,
        "static_url_path": static_url_path_for_token(token),
        "module_ledger_total_count": totals.get("module_ledger_total_count"),
        "critical_ledger_total_count": totals.get("critical_ledger_total_count"),
        "unrouted_ledger_total_count": totals.get("unrouted_ledger_total_count"),
        "module_ledger_rows": module_rows,
        "critical_ledger_rows": critical_rows,
        "critical_ledger_by_phase": by_phase,
        "unrouted_event_count": len(list(unrouted.get("rows") or [])),
        "unrouted_rows": unrouted_rows,
        "latest_ingress_summaries": summaries,
        "routing_provenance_rows": routing_rows,
        "wrapper_integrity": integrity,
        "server_wrapper_integrity_ok": bool(integrity.get("server_wrapper_integrity_ok")),
    }


def publish_oob_snapshot(
    streamlit_session_id: str,
    *,
    publish_source: str,
    session: dict[str, Any] | None = None,
    diagnostic_token: str = "",
) -> dict[str, Any]:
    sid = str(streamlit_session_id or "").strip()[:64]
    token = str(diagnostic_token or resolve_token_for_streamlit_session(sid) or "").strip()[:32]
    if not sid or not token:
        return {"published": False, "reason": "missing_sid_or_token"}
    generation = _next_generation(token)
    payload = build_oob_snapshot_payload(
        sid,
        diagnostic_token=token,
        snapshot_generation=generation,
        publish_source=publish_source,
        session=session,
    )
    path = snapshot_path_for_token(token)
    with _OOB_LOCK:
        _atomic_write_json(path, payload)
    out = {
        "published": True,
        "streamlit_session_id": sid,
        "diagnostic_token": token,
        "snapshot_generation": generation,
        "static_url_path": payload.get("static_url_path"),
        "publish_source": publish_source,
        "snapshot_path": str(path),
    }
    mapping = _session_mapping(session)
    if mapping is not None:
        channel = dict(mapping.get(S3_OOB_CHANNEL_SESSION_KEY) or {})
        channel.update(out)
        mapping[S3_OOB_CHANNEL_SESSION_KEY] = channel
    return out


def publish_initial_oob_snapshot(streamlit_session_id: str, session: dict[str, Any] | None = None) -> dict[str, Any]:
    channel = register_oob_channel(streamlit_session_id, session)
    if not channel.get("registered"):
        return {"published": False, "reason": "channel_not_registered"}
    pub = publish_oob_snapshot(
        streamlit_session_id,
        publish_source="initial_pre_click",
        session=session,
        diagnostic_token=str(channel.get("diagnostic_token") or ""),
    )
    return {**channel, **pub}


def read_oob_snapshot_file(token: str) -> dict[str, Any] | None:
    path = snapshot_path_for_token(token)
    if not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return dict(parsed) if isinstance(parsed, dict) else None


def oob_channel_export(session: dict[str, Any] | None = None) -> dict[str, Any]:
    mapping = _session_mapping(session)
    if mapping is not None:
        channel = dict(mapping.get(S3_OOB_CHANNEL_SESSION_KEY) or {})
        if channel:
            token = str(channel.get("diagnostic_token") or "")
            channel["snapshot_generation"] = current_generation(token)
            return channel
    return {"registered": False, "impl_rev": S3_OOB_IMPL_REV}
