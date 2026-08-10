"""Poll sibling setup until DOM/ledger evidence is coherent (harness-only)."""

from __future__ import annotations

import time
from typing import Any

from stage1_pause_sibling_scrape import scrape_pause_sibling_probe
from stage1_s3_server_registry_scrape import evaluate_post_registration_from_ledger, scrape_s3_server_diag_ledger
from stage1_s3_setup_localize import (
    build_setup_readiness_table,
    classify_setup_early_exception,
    classify_setup_failure,
    setup_ready_for_sibling_click,
)
from stage1_sibling_setup_scrape import SIBLING_BUTTON_LABEL, finalize_sibling_import_evidence, scrape_sibling_setup_layers
from streamlit_app_frame import resolve_streamlit_app_frame

DEFAULT_MAX_WAIT_S = 45.0
DEFAULT_POLL_INTERVAL_MS = 600

DECL_PRE_EVENT = "SIBLING_BUTTON_DECLARATION_ENTRY"
DECL_POST_EVENT = "SIBLING_BUTTON_DECLARATION_RESULT"

_ATOMIC_PRESENCE_JS = """() => {
  const DECL_SEL = '#solo-stage1-pause-sibling-declaration, .solo-stage1-pause-sibling-declaration';
  const SIBLING_LEDGER_SEL = '#solo-stage1-pause-sibling-ledger';
  const S3_LEDGER_SEL = '#solo-stage1-s3-server-diag-ledger';
  const CHECKPOINT_SEL = '#solo-stage1-pause-sibling-setup-checkpoint, .solo-stage1-pause-sibling-setup-checkpoint';
  const siblingLabel = 'Stage1 Pause-Sibling Return Probe';
  function normText(s) {
    return String(s || '').replace(/\\s+/g, ' ').trim();
  }
  function parseJson(el) {
    if (!el) return null;
    const raw = el.getAttribute('data-json') || '';
    if (!raw) return null;
    try { return JSON.parse(raw.replace(/'/g, '"')); } catch (e) { return null; }
  }
  const declNodes = document.querySelectorAll(DECL_SEL);
  let prePresent = false;
  let postPresent = false;
  let preCount = 0;
  let postCount = 0;
  let roomId = '';
  let streamlitSessionId = '';
  let fullAppRunSeq = null;
  declNodes.forEach((el) => {
    const j = parseJson(el) || {};
    const ev = el.getAttribute('data-event') || j.event || '';
    if (ev === 'SIBLING_BUTTON_DECLARATION_ENTRY') {
      preCount += 1;
      prePresent = true;
    }
    if (ev === 'SIBLING_BUTTON_DECLARATION_RESULT') {
      postCount += 1;
      postPresent = true;
    }
    if (j.room_id && !roomId) roomId = String(j.room_id);
    if (j.streamlit_session_id && !streamlitSessionId) streamlitSessionId = String(j.streamlit_session_id);
    if (j.full_app_run_seq != null && fullAppRunSeq == null) fullAppRunSeq = j.full_app_run_seq;
  });
  let siblingButtonPresent = false;
  for (const b of document.querySelectorAll('button')) {
    if (normText(b.innerText || b.textContent || '') === siblingLabel) {
      siblingButtonPresent = true;
      break;
    }
  }
  const siblingLedgerPresent = !!document.querySelector(SIBLING_LEDGER_SEL);
  const s3LedgerPresent = !!document.querySelector(S3_LEDGER_SEL);
  const checkpointEvents = [];
  document.querySelectorAll(CHECKPOINT_SEL).forEach((el) => {
    const j = parseJson(el) || {};
    const ev = el.getAttribute('data-event') || j.event || '';
    if (ev) checkpointEvents.push(ev);
    if (j.room_id && !roomId) roomId = String(j.room_id);
    if (j.streamlit_session_id && !streamlitSessionId) streamlitSessionId = String(j.streamlit_session_id);
    if (j.full_app_run_seq != null && fullAppRunSeq == null) fullAppRunSeq = j.full_app_run_seq;
  });
  const callsite = document.querySelector('#solo-stage1-pause-sibling-callsite');
  const entry = document.querySelector('#solo-stage1-pause-sibling-entry');
  return {
    pre_declaration_present: prePresent,
    post_declaration_present: postPresent,
    pre_declaration_count: preCount,
    post_declaration_count: postCount,
    sibling_button_present: siblingButtonPresent,
    sibling_ledger_present: siblingLedgerPresent,
    s3_ledger_present: s3LedgerPresent,
    setup_checkpoint_event_count: checkpointEvents.length,
    setup_checkpoint_events: checkpointEvents,
    sibling_callsite_present: !!callsite,
    sibling_entry_present: !!entry,
    room_id: roomId,
    streamlit_session_id: streamlitSessionId,
    full_app_run_seq: fullAppRunSeq,
  };
}"""


def scrape_atomic_setup_presence(frame) -> dict[str, Any]:
    try:
        raw = frame.evaluate(_ATOMIC_PRESENCE_JS)
    except Exception as exc:
        return {"error": str(exc)[:200]}
    return dict(raw) if isinstance(raw, dict) else {}


def _run_seq_from_layers(layers: dict[str, Any]) -> int | None:
    for key in ("declaration_post_json", "declaration_pre_json", "callsite_json"):
        blob = layers.get(key)
        if isinstance(blob, dict) and blob.get("full_app_run_seq") is not None:
            try:
                return int(blob.get("full_app_run_seq"))
            except (TypeError, ValueError):
                pass
    for ck_key in (
        "checkpoint_sibling_setup_export_complete",
        "checkpoint_sibling_post_registration_returned",
        "checkpoint_sibling_button_call_returned",
    ):
        ck = layers.get(ck_key)
        if isinstance(ck, dict) and ck.get("full_app_run_seq") is not None:
            try:
                return int(ck.get("full_app_run_seq"))
            except (TypeError, ValueError):
                pass
    return None


def _room_aligned(expected_room: str, layers: dict[str, Any], atomic: dict[str, Any]) -> bool:
    exp = str(expected_room or "").strip().upper()
    if not exp:
        return False
    for blob in (
        layers.get("declaration_post_json"),
        layers.get("declaration_pre_json"),
        layers.get("callsite_json"),
    ):
        if isinstance(blob, dict):
            rid = str(blob.get("room_id") or "").strip().upper()
            if rid and rid != exp:
                return False
    ar = str(atomic.get("room_id") or "").strip().upper()
    if ar and ar != exp:
        return False
    return True


def _compact_poll_row(
    *,
    ts: float,
    run_seq: int | None,
    atomic: dict[str, Any],
    layers: dict[str, Any],
    s3_found: bool,
    post_reg_ready: bool,
    binding_ok: bool,
    wrapper_ok: bool | None,
) -> dict[str, Any]:
    return {
        "ts": ts,
        "full_app_run_seq": run_seq,
        "pre": bool(layers.get("sibling_pre_button_reached") or atomic.get("pre_declaration_present")),
        "post": bool(layers.get("sibling_post_button_return_reached") or atomic.get("post_declaration_present")),
        "button": bool(layers.get("sibling_button_found") or atomic.get("sibling_button_present")),
        "sibling_ledger": bool(layers.get("sibling_ledger_found") or atomic.get("sibling_ledger_present")),
        "s3_ledger": bool(s3_found or atomic.get("s3_ledger_present")),
        "post_registration_ready": post_reg_ready,
        "binding": binding_ok,
        "wrapper_integrity": wrapper_ok,
        "atomic_sibling_ledger": bool(atomic.get("sibling_ledger_present")),
        "atomic_s3_ledger": bool(atomic.get("s3_ledger_present")),
    }


def _poll_setup_once(
    page,
    *,
    frame,
    room_id: str,
) -> dict[str, Any]:
    atomic = scrape_atomic_setup_presence(frame)
    sibling_layers = scrape_sibling_setup_layers(page, frame=frame)
    sibling_scrape = scrape_pause_sibling_probe(page, frame=frame)
    s3_ledger_scrape = scrape_s3_server_diag_ledger(page, frame=frame)
    post_reg, binding, pre_decl = evaluate_post_registration_from_ledger(s3_ledger_scrape)
    post_reg_ready = str(post_reg.get("registered_widget_id") or "").startswith("$$ID-")
    binding_ok = bool(binding.get("sessionstate_binding_ok"))
    sibling_layers = finalize_sibling_import_evidence(
        sibling_layers,
        s3_ledger_found=bool(s3_ledger_scrape.get("found")),
        post_registration_ready=post_reg_ready,
        binding_ok=binding_ok,
    )
    run_seq = _run_seq_from_layers(sibling_layers)
    if run_seq is None and atomic.get("full_app_run_seq") is not None:
        try:
            run_seq = int(atomic.get("full_app_run_seq"))
        except (TypeError, ValueError):
            run_seq = None
    streamlit_sid = str(
        sibling_scrape.get("streamlit_session_id")
        or atomic.get("streamlit_session_id")
        or s3_ledger_scrape.get("payload", {}).get("ledger", {}).get("streamlit_session_id")
        or ""
    )[:64]
    return {
        "atomic_presence": atomic,
        "sibling_setup_layers": sibling_layers,
        "sibling_probe_scrape": sibling_scrape,
        "s3_ledger_scrape": s3_ledger_scrape,
        "post_registration": post_reg,
        "s3_diag_binding": binding,
        "pre_declaration": pre_decl,
        "post_registration_ready": post_reg_ready,
        "binding_ok": binding_ok,
        "streamlit_session_id": streamlit_sid,
        "full_app_run_seq": run_seq,
        "room_aligned": _room_aligned(room_id, sibling_layers, atomic),
    }


def wait_for_sibling_setup_stable(
    page,
    *,
    room_id: str,
    pause_ready: dict[str, Any],
    runtime_sha: str,
    auth_restored: bool,
    start_latch_pass: bool,
    max_wait_s: float = DEFAULT_MAX_WAIT_S,
    poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS,
) -> dict[str, Any]:
    """Poll setup layers without clicking until coherent or timeout."""
    deadline = time.time() + max_wait_s
    poll_history: list[dict[str, Any]] = []
    last_poll: dict[str, Any] = {}

    while time.time() < deadline:
        frame = resolve_streamlit_app_frame(page)
        snap = _poll_setup_once(page, frame=frame, room_id=room_id)
        last_poll = snap
        layers = dict(snap.get("sibling_setup_layers") or {})
        early, early_note = classify_setup_early_exception(layers)
        if early:
            row = _compact_poll_row(
                ts=time.time(),
                run_seq=snap.get("full_app_run_seq"),
                atomic=dict(snap.get("atomic_presence") or {}),
                layers=layers,
                s3_found=bool((snap.get("s3_ledger_scrape") or {}).get("found")),
                post_reg_ready=bool(snap.get("post_registration_ready")),
                binding_ok=bool(snap.get("binding_ok")),
                wrapper_ok=(snap.get("s3_diag_binding") or {}).get("server_wrapper_integrity_ok"),
            )
            poll_history.append(row)
            return {
                "ok": False,
                "stable": False,
                "early_abort": True,
                "timed_out": False,
                "poll_count": len(poll_history),
                "poll_history": poll_history,
                "setup_abort": early,
                "setup_note": early_note,
                "last_poll": snap,
                "atomic_presence_final": snap.get("atomic_presence"),
            }

        binding = dict(snap.get("s3_diag_binding") or {})
        s3_scrape = dict(snap.get("s3_ledger_scrape") or {})
        post_reg = dict(snap.get("post_registration") or {})
        wrapper_ok = binding.get("server_wrapper_integrity_ok")

        row = _compact_poll_row(
            ts=time.time(),
            run_seq=snap.get("full_app_run_seq"),
            atomic=dict(snap.get("atomic_presence") or {}),
            layers=layers,
            s3_found=bool(s3_scrape.get("found")),
            post_reg_ready=bool(snap.get("post_registration_ready")),
            binding_ok=bool(snap.get("binding_ok")),
            wrapper_ok=wrapper_ok if wrapper_ok in (True, False) else None,
        )
        poll_history.append(row)

        if not snap.get("room_aligned"):
            page.wait_for_timeout(poll_interval_ms)
            continue

        setup_table = build_setup_readiness_table(
            runtime_sha=runtime_sha,
            auth_restored=auth_restored,
            start_latch_pass=start_latch_pass,
            room_id=room_id,
            streamlit_session_id=str(snap.get("streamlit_session_id") or ""),
            pause_control_ready=bool(pause_ready.get("ready")),
            sibling_layers=layers,
            s3_ledger_found=bool(s3_scrape.get("found")),
            post_registration_ready=bool(snap.get("post_registration_ready")),
            binding_ok=bool(snap.get("binding_ok")),
            server_wrapper_integrity_ok=wrapper_ok if wrapper_ok in (True, False) else None,
        )
        if setup_ready_for_sibling_click(setup_table):
            return {
                "ok": True,
                "stable": True,
                "early_abort": False,
                "timed_out": False,
                "poll_count": len(poll_history),
                "poll_history": poll_history,
                "setup_abort": None,
                "setup_note": "setup_pass",
                "last_poll": snap,
                "atomic_presence_final": snap.get("atomic_presence"),
                "setup_readiness_table": setup_table,
            }

        page.wait_for_timeout(poll_interval_ms)

    snap = last_poll or {}
    layers = dict(snap.get("sibling_setup_layers") or {})
    s3_scrape = dict(snap.get("s3_ledger_scrape") or {})
    post_reg = dict(snap.get("post_registration") or {})
    binding = dict(snap.get("s3_diag_binding") or {})
    setup_abort, setup_note = classify_setup_failure(
        pause_ready=pause_ready,
        sibling_layers=layers,
        s3_ledger_scrape=s3_scrape,
        post_registration=post_reg,
        binding=binding,
        after_stabilization=True,
    )
    setup_table = build_setup_readiness_table(
        runtime_sha=runtime_sha,
        auth_restored=auth_restored,
        start_latch_pass=start_latch_pass,
        room_id=room_id,
        streamlit_session_id=str(snap.get("streamlit_session_id") or ""),
        pause_control_ready=bool(pause_ready.get("ready")),
        sibling_layers=layers,
        s3_ledger_found=bool(s3_scrape.get("found")),
        post_registration_ready=bool(snap.get("post_registration_ready")),
        binding_ok=bool(snap.get("binding_ok")),
        server_wrapper_integrity_ok=binding.get("server_wrapper_integrity_ok"),
    )
    return {
        "ok": False,
        "stable": False,
        "early_abort": False,
        "timed_out": True,
        "poll_count": len(poll_history),
        "poll_history": poll_history,
        "setup_abort": setup_abort or "ABORTED_S3_POST_REGISTRATION_NOT_READY",
        "setup_note": setup_note or "setup_table_incomplete",
        "last_poll": snap,
        "atomic_presence_final": snap.get("atomic_presence"),
        "setup_readiness_table": setup_table,
    }


__all__ = [
    "DEFAULT_MAX_WAIT_S",
    "DEFAULT_POLL_INTERVAL_MS",
    "SIBLING_BUTTON_LABEL",
    "scrape_atomic_setup_presence",
    "wait_for_sibling_setup_stable",
]
