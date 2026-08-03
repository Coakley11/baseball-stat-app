"""QUEUEUI active-page transition capture and classification (harness only)."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

QUEUEUI1 = "QUEUEUI1 — ACTIVE LIVE DRAFT PAGE NOT HYDRATED"
QUEUEUI2 = "QUEUEUI2 — ROOM CREATED, BUT ROOM ID NOT WRITTEN TO CLIENT SESSION STATE"
QUEUEUI3 = "QUEUEUI3 — CLIENT ROOM ID EXISTS, BUT ACTIVE/SELECTED ROOM IS NOT SET"
QUEUEUI4 = "QUEUEUI4 — ACTIVE ROOM IS SET, BUT PAGE/ROUTE REMAINS ON SETUP"
QUEUEUI5 = "QUEUEUI5 — ROUTE IS CORRECT, BUT ACTIVE-ROOM RENDER PREDICATE IS FALSE"
QUEUEUI6 = "QUEUEUI6 — ACTIVE-ROOM RENDER FUNCTION CALLED, BUT UI DECLARATIONS ARE ABSENT"
QUEUEUI7 = "QUEUEUI7 — ACTIVE UI DECLARED, BUT BROWSER/STREAMLIT FRONT END DID NOT MOUNT IT"
QUEUEUI8 = "QUEUEUI8 — CLIENT RERUN OR NAVIGATION DID NOT OCCUR AFTER ROOM CREATION"
QUEUEUI9 = "QUEUEUI9 — EXCEPTION OR FRONT-END ERROR INTERRUPTED ACTIVE-PAGE RENDERING"
QUEUEUI10 = "QUEUEUI10 — ROOM IDENTITY MISMATCH BETWEEN SERVER, SESSION, ROUTE, OR VISIBLE UI"
QUEUEUI11 = "QUEUEUI11 — OTHER"

STATIC_TRANSITION_PATH_REVIEW = """
Solo setup/start → active Live Draft (application path, no edits):

1. Setup lobby: Live Draft Room page; `resolve_live_draft_lifecycle(session)` → `setup` when
   `live_draft_room` is absent (live_draft_completion.py).
2. Start control: `live_draft_start_btn` → start handler writes `live_draft_room`, may set
   `active_shared_draft_room_code`, emits stage-1 ledger (handler_entered/exited, room_state_write).
3. On handler success: `protect_new_room`, `resolve_live_draft_lifecycle` → `active_draft`, then
   `st.rerun()` (streamlit_app.py ~24148–24191) — same pass must not paint active chrome.
4. Next script run: `_live_draft_lifecycle = resolve_live_draft_lifecycle(...)` with captured room;
   active branch when lifecycle ∈ {active_draft, waiting_shared_lobby} and room dict present
   (~24878+).
5. Render predicate (harness observability): lifecycle == active_draft AND room dict;
   UI hydration: visible Room ID, Pause Draft, mount/token, queue/board controls.

Session keys (CANONICAL_ROOM_KEYS / key-ownership diag): live_draft_room, live_draft_state,
active_shared_draft_room_code, active_page; page_filter Live Draft Room block mirrors room.
URL: `active_page=Live Draft Room` (production harness production_url()).
""".strip()


SCRAPE_TRANSITION_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument) r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  const text = roots().map(x => x.body ? x.body.innerText : '').join('\\n');
  let wake = {};
  for (const root of roots()) {
    const w = root.querySelector('#solo-persistent-wake-lifecycle-diag');
    if (w) {
      wake = {
        phase: w.getAttribute('data-phase')||'',
        token: w.getAttribute('data-token')||'',
        actionable: w.getAttribute('data-actionable')||'',
      };
    }
  }
  let keyOwnership = null;
  for (const root of roots()) {
    const ko = root.querySelector('#solo-key-ownership-diag');
    if (!ko) continue;
    const b64 = ko.getAttribute('data-key-ownership-b64')||'';
    if (b64) keyOwnership = { b64, present: true };
  }
  let mount = {};
  for (const root of roots()) {
    const el = root.querySelector('#solo-component-mount-diag');
    if (!el) continue;
    mount = {
      mounted: el.getAttribute('data-mounted')||'',
      draft_id: el.getAttribute('data-draft-id')||'',
      pick_index: el.getAttribute('data-pick-index')||'',
      deadline: el.getAttribute('data-deadline')||'',
      token: el.getAttribute('data-token')||'',
      diag_timer: el.getAttribute('data-diag-timer')||'',
      key: el.getAttribute('data-key')||'',
    };
  }
  let surface = {};
  for (const root of roots()) {
    const s = root.querySelector('[data-solo-surface-decision]');
    if (s) {
      surface = {
        lifecycle: s.getAttribute('data-lifecycle')||'',
        in_progress: s.getAttribute('data-in-progress')||'',
      };
    }
  }
  const roomMatch = text.match(/Room ID\\s+([A-F0-9]+)/i);
  let pause = 0, addQ = 0, draftPlayer = 0, startNew = 0;
  for (const root of roots()) {
    for (const b of root.querySelectorAll('button')) {
      const r = b.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const t = String(b.innerText||'').replace(/\\s+/g,' ').trim();
      if (/Pause Draft/i.test(t)) pause++;
      if (/Add to Queue/i.test(t)) addQ++;
      if (/Draft Player/i.test(t)) draftPlayer++;
      if (/Start New Live Draft/i.test(t)) startNew++;
    }
  }
  const href = String(location.href || '');
  let query = {};
  try {
    const u = new URL(href);
    u.searchParams.forEach((v,k) => { query[k] = v; });
  } catch(e) {}
  return {
    text_head: text.slice(0, 2000),
    text_len: text.length,
    wake,
    keyOwnership,
    mount,
    surface,
    visible_room_id: roomMatch ? roomMatch[1].toUpperCase() : '',
    pause_draft_count: pause,
    add_to_queue_count: addQ,
    draft_player_count: draftPlayer,
    start_new_live_draft_count: startNew,
    has_start_new_text: /Start New Live Draft/i.test(text),
    page_url: href,
    query,
  };
}"""


def decode_key_ownership_b64(b64: str) -> dict[str, Any]:
    raw = str(b64 or "").strip()
    if not raw:
        return {}
    try:
        pad = raw + "=" * ((4 - len(raw) % 4) % 4)
        payload = json.loads(base64.b64decode(pad.encode("ascii")).decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def key_ownership_last_row(payload: dict[str, Any]) -> dict[str, Any]:
    rows = list(payload.get("rows") or [])
    if not rows:
        return {}
    last = rows[-1]
    return dict(last) if isinstance(last, dict) else {}


def parse_room_from_url(url: str) -> str:
    try:
        q = parse_qs(urlparse(url).query, keep_blank_values=True)
        for key in ("room", "room_id", "draft_room_id", "shared_room"):
            if q.get(key):
                return str(q[key][0]).strip().upper()
    except Exception:
        pass
    return ""


def snapshot_fingerprint(snap: dict[str, Any]) -> str:
    core = {
        "v": snap.get("visible_room_id"),
        "p": snap.get("python_room_id"),
        "pause": snap.get("pause_draft_count"),
        "start": snap.get("start_new_live_draft_count"),
        "ko_seq": (snap.get("key_ownership_last") or {}).get("seq"),
        "mount": (snap.get("mount") or {}).get("draft_id"),
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()[:16]


def summarize_ledger_events(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    handler_entered = False
    handler_exited = False
    created_room_id = ""
    rerun_events = 0
    surface_decisions: list[dict[str, Any]] = []
    session_proofs: list[dict[str, Any]] = []
    for r in rows:
        ev = str(r.get("event") or "")
        if ev:
            counts[ev] = counts.get(ev, 0) + 1
        if ev == "production_stage1_start_handler_entered":
            handler_entered = True
        if ev == "production_stage1_start_handler_exited":
            handler_exited = True
            if r.get("created_room_id"):
                created_room_id = str(r.get("created_room_id")).upper()
        if ev == "production_stage1_rerun_transition":
            rerun_events += 1
        if ev == "production_stage1_surface_decision":
            surface_decisions.append(
                {
                    "lifecycle": r.get("lifecycle"),
                    "in_progress": r.get("in_progress"),
                    "room_id": r.get("room_id") or r.get("draft_room_id"),
                }
            )
        if ev == "production_stage1_handler_exit_session_state_proof":
            session_proofs.append(dict(r))
    return {
        "event_counts": counts,
        "handler_entered": handler_entered,
        "handler_exited": handler_exited,
        "created_room_id_from_ledger": created_room_id,
        "rerun_transition_count": rerun_events,
        "surface_decisions": surface_decisions[-5:],
        "session_state_proofs": session_proofs[-3:],
    }


def client_room_id_from_ledger_summary(ledger_summary: dict[str, Any]) -> str:
    proofs = list(ledger_summary.get("session_state_proofs") or [])
    for row in reversed(proofs):
        auth = row.get("authoritative_session_state") if isinstance(row.get("authoritative_session_state"), dict) else {}
        rid = str(auth.get("session_room_id") or row.get("local_created_room_id") or row.get("room_id") or "").upper()
        if rid:
            return rid
    return str(ledger_summary.get("created_room_id_from_ledger") or "").upper()


def build_room_identity_table(
    *,
    server_room_id: str,
    snap: dict[str, Any],
    ledger_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ko = dict(snap.get("key_ownership_last") or {})
    ledger_summary = dict(ledger_summary or {})
    client_session_room_id = str(
        ko.get("live_draft_room_id")
        or ko.get("live_draft_state_room_id")
        or snap.get("python_room_id")
        or client_room_id_from_ledger_summary(ledger_summary)
        or ""
    ).upper()
    selected_room_id = str(ko.get("page_filter_room_id") or ko.get("active_shared_draft_room_code") or "").upper()
    active_room_id = str(ko.get("live_draft_room_id") or client_session_room_id).upper()
    visible_room_id = str(snap.get("visible_room_id") or "").upper()
    url_room_id = parse_room_from_url(str(snap.get("page_url") or ""))
    mount_rid = str((snap.get("mount") or {}).get("draft_id") or "").upper()
    ids = {
        "server_room_id": server_room_id.upper(),
        "client_session_room_id": client_session_room_id,
        "selected_room_id": selected_room_id,
        "active_room_id": active_room_id,
        "visible_room_id": visible_room_id,
        "url_query_room_id": url_room_id,
        "mount_draft_id": mount_rid,
    }

    def pair(a: str, b: str) -> str:
        if not a and not b:
            return "both_empty"
        if not a or not b:
            return "mismatch_one_empty"
        return "equal" if a == b else "mismatch"

    pairs = {
        "server_vs_client_session": pair(ids["server_room_id"], ids["client_session_room_id"]),
        "server_vs_active": pair(ids["server_room_id"], ids["active_room_id"]),
        "server_vs_visible": pair(ids["server_room_id"], ids["visible_room_id"]),
        "client_vs_visible": pair(ids["client_session_room_id"], ids["visible_room_id"]),
        "active_vs_visible": pair(ids["active_room_id"], ids["visible_room_id"]),
        "mount_vs_server": pair(ids["mount_draft_id"], ids["server_room_id"]),
        "selected_vs_server": pair(ids["selected_room_id"], ids["server_room_id"]),
    }
    return {"ids": ids, "pairwise": pairs}


def evaluate_active_page_predicate_terms(
    snap: dict[str, Any],
    *,
    lifecycle_hint: str = "",
    ledger_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ko = dict(snap.get("key_ownership_last") or {})
    ledger_summary = dict(ledger_summary or {})
    live_present = bool(ko.get("live_draft_room_present"))
    if not live_present and client_room_id_from_ledger_summary(ledger_summary):
        live_present = True
    room_status = str(ko.get("live_draft_room_status") or ko.get("live_draft_state_status") or "").lower()
    active_page = str(ko.get("active_page") or snap.get("query_active_page") or "")
    setup_visible = bool(snap.get("has_start_new_text")) or int(snap.get("start_new_live_draft_count") or 0) >= 1
    lifecycle = lifecycle_hint or str((snap.get("surface") or {}).get("lifecycle") or "")
    mount = snap.get("mount") or {}
    mount_declared = bool(mount.get("draft_id") or mount.get("token") or str(mount.get("mounted") or "") in ("1", "true"))
    pause = int(snap.get("pause_draft_count") or 0)
    visible_ui = pause >= 1 or bool(snap.get("visible_room_id"))
    terms = {
        "live_draft_room_present_in_session_diag": live_present,
        "room_status_in_progress_or_active": room_status in ("in_progress", "active", "waiting", ""),
        "lifecycle_resolves_active_draft": lifecycle in ("active_draft", "active"),
        "route_active_page_live_draft": "live draft" in active_page.lower() or "Live%20Draft" in str(snap.get("page_url") or ""),
        "setup_start_control_visible": setup_visible,
        "active_branch_predicate": live_present and not setup_visible,
        "mount_or_token_declared_in_dom": mount_declared,
        "live_controls_visible_in_browser": visible_ui,
    }
    terms["would_render_active_live_branch"] = (
        terms["live_draft_room_present_in_session_diag"]
        and terms["route_active_page_live_draft"]
        and (terms["lifecycle_resolves_active_draft"] or terms["room_status_in_progress_or_active"])
    )
    return terms


def classify_queueui_boundary(
    *,
    server_latch: dict[str, Any],
    snap: dict[str, Any],
    ledger_summary: dict[str, Any],
    gate_eval: dict[str, Any],
    console_errors: list[str],
    page_errors: list[str],
) -> tuple[str, str, str]:
    """Return (classification, defect_side, reason)."""
    text_blob = str(snap.get("text_head") or "").lower()
    err_blob = " ".join(console_errors + page_errors).lower()
    if "traceback" in text_blob or "traceback" in err_blob or "exception" in err_blob:
        return QUEUEUI9, "application_side_or_frontend", "exception_or_traceback_on_page_or_console"

    server_id = str(server_latch.get("server_room_id") or ledger_summary.get("created_room_id_from_ledger") or "").upper()
    server_ok = bool(server_latch.get("ok")) or bool(server_id)
    identity = build_room_identity_table(server_room_id=server_id, snap=snap, ledger_summary=ledger_summary)
    pairs = identity["pairwise"]
    ids = identity["ids"]
    terms = evaluate_active_page_predicate_terms(snap, ledger_summary=ledger_summary)

    if server_ok and server_id:
        if not ids["client_session_room_id"] and not ids["visible_room_id"]:
            return QUEUEUI2, "application_side", "server_latched_room_not_in_client_session_or_visible_ui"
        if ids["client_session_room_id"] and ids["visible_room_id"] == server_id:
            if not terms.get("mount_or_token_declared_in_dom") and int(snap.get("pause_draft_count") or 0) == 0:
                if terms.get("live_controls_visible_in_browser") or snap.get("authoritative", {}).get("in_progress"):
                    return (
                        QUEUEUI6,
                        "application_side",
                        "session_and_visible_room_agree_but_production_mount_and_pause_controls_absent",
                    )
        mismatches = [k for k, v in pairs.items() if v == "mismatch"]
        if mismatches and not ids["visible_room_id"]:
            return QUEUEUI10, "application_side", "identity_mismatch:" + ",".join(mismatches)

    ko = dict(snap.get("key_ownership_last") or {})
    if ids["client_session_room_id"] and not ids["selected_room_id"] and not ko.get("page_filter_room_id"):
        if server_ok:
            return QUEUEUI3, "application_side", "client_room_without_page_filter_or_active_code"

    if ids["client_session_room_id"] and snap.get("has_start_new_text"):
        return QUEUEUI4, "application_side", "room_in_session_but_setup_start_still_visible"

    terms = evaluate_active_page_predicate_terms(snap)
    if terms["would_render_active_live_branch"] and not terms["live_controls_visible_in_browser"]:
        if terms["mount_or_token_declared_in_dom"] and not terms["live_controls_visible_in_browser"]:
            return QUEUEUI7, "harness_or_frontend", "mount_declared_but_pause_or_room_not_visible"
        if ledger_summary.get("surface_decisions") and str(
            (ledger_summary["surface_decisions"][-1] or {}).get("lifecycle") or ""
        ).lower() in ("setup", "deleting"):
            return QUEUEUI5, "application_side", "surface_decision_lifecycle_not_active_draft"
        return QUEUEUI6, "application_side", "active_predicate_true_but_live_controls_absent"

    if server_ok and ledger_summary.get("handler_exited") and ledger_summary.get("rerun_transition_count", 0) == 0:
        stable_ko = int(ko.get("seq") or 0)
        if stable_ko <= 1 and ids["client_session_room_id"]:
            return QUEUEUI8, "application_side", "handler_exited_without_observed_rerun_transition"

    if gate_eval.get("passed"):
        return "QUEUEUI_PASS — ACTIVE LIVE PAGE HYDRATED", "none", "active_live_page_gate_passed"

    if server_ok and not gate_eval.get("passed"):
        checks = gate_eval.get("checks") or {}
        if not checks.get("latched_room_visible_agrees") and not ids["visible_room_id"]:
            if ids["client_session_room_id"]:
                return QUEUEUI5, "application_side", "session_room_present_ui_not_hydrated"
            return QUEUEUI2, "application_side", "server_latch_without_client_or_visible_room"
        if checks.get("latched_room_visible_agrees") is False and ids["visible_room_id"]:
            return QUEUEUI10, "application_side", "visible_room_disagrees_with_latched_server_room"
        return QUEUEUI1, "application_side", "active_live_page_gate_failed_generic"

    return QUEUEUI11, "unresolved", "insufficient_evidence_for_narrower_boundary"


def merge_capture_snapshots(
    page,
    *,
    label: str,
    ledger_rows: list[dict[str, Any]] | None = None,
    console_errors: list[str] | None = None,
    page_errors: list[str] | None = None,
) -> dict[str, Any]:
    from production_draft_start_authoritative import scrape_authoritative_start_state

    auth = scrape_authoritative_start_state(page)
    dom = page.evaluate(SCRAPE_TRANSITION_JS) or {}
    ko_payload = decode_key_ownership_b64(((dom.get("keyOwnership") or {}).get("b64") or ""))
    ko_last = key_ownership_last_row(ko_payload)
    snap: dict[str, Any] = {
        "label": label,
        "page_url": dom.get("page_url") or auth.get("url"),
        "query": dom.get("query") or {},
        "query_active_page": str((dom.get("query") or {}).get("active_page") or ""),
        "visible_room_id": dom.get("visible_room_id") or auth.get("visible_room_id"),
        "python_room_id": auth.get("python_room_id") or ko_last.get("live_draft_room_id"),
        "pause_draft_count": dom.get("pause_draft_count", auth.get("pause_draft_count")),
        "add_to_queue_count": dom.get("add_to_queue_count"),
        "draft_player_count": dom.get("draft_player_count"),
        "start_new_live_draft_count": dom.get("start_new_live_draft_count"),
        "has_start_new_text": dom.get("has_start_new_text"),
        "wake": dom.get("wake") or {},
        "mount": {**(dom.get("mount") or {}), **(auth.get("mount") or {})},
        "surface": dom.get("surface") or {},
        "key_ownership_last": ko_last,
        "key_ownership_row_count": len(list(ko_payload.get("rows") or [])),
        "streamlit_session_id_from_ko": str(ko_payload.get("streamlit_session_id") or ""),
        "authoritative": auth,
        "text_head": dom.get("text_head"),
        "text_len": dom.get("text_len"),
        "ledger_row_count": len(ledger_rows or []),
        "console_errors": list(console_errors or [])[-20:],
        "page_errors": list(page_errors or [])[-20:],
    }
    snap["fingerprint"] = snapshot_fingerprint(snap)
    return snap
