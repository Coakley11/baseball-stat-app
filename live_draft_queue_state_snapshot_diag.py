"""Diagnostic-only dual-queue state snapshots (session + canonical).

Exposes independently, on the NORMAL UNLATCHED Live Draft Stage-1 path:

  session["draft_queue"]
  session["draft_state"]["queue"]

Requires:
  solo_component_diag=1
  AND solo_stage1_parent_boundary=1

Does NOT require stage1_francisco_callback_only.

Observability only — no queue mutation, sync, dirty, or persist side effects
on the baseline path. Post-mutation snapshot is recorded AFTER the existing
product add/sync/canonical-write sequence completes.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

IMPL_REV = "stage1_queue_state_snapshot_diag_v1"
PROBE_ID = "stage1-queue-state-snapshot"
SESSION_LEDGER_KEY = "_stage1_queue_state_snapshot_ledger"
SESSION_LAST_KEY = "_stage1_queue_state_snapshot_last"
SESSION_BASELINE_KEY = "_stage1_queue_state_snapshot_baseline"
SESSION_POST_KEY = "_stage1_queue_state_snapshot_post"
MAX_LEDGER = 32

PHASE_BASELINE = "QUEUE_STATE_BASELINE"
PHASE_POST_ADDED = "QUEUE_STATE_POST_MUTATION_ADDED"
PHASE_POST_NO_ADD = "QUEUE_STATE_POST_NO_ADD"

FRANCISCO_NAME = "Francisco Lindor"

_LOCK = threading.Lock()


def _qp_flag(st: Any, name: str) -> bool:
    try:
        from live_draft_cloud_diagnostics import _qp_flag as _flag

        return bool(_flag(st, name))
    except Exception:
        return False


def _refresh_queue_state_diag_latches(st: Any | None, session: dict[str, Any]) -> None:
    """Latch parent_boundary when solo is already on and the query flag is present.

    Sibling Stage-1 card probes (fragment exec / render-trace) enable on solo alone and
    often rely on a session latch set at bootstrap. Dual-queue snapshots require BOTH
    solo_component_diag and solo_stage1_parent_boundary. If parent_boundary was never
    latched into session (while solo was), fragment/rerun contexts that cannot re-read
    query params would skip the DOM probe entirely — scrape returns {}.

    Observe-only: does not install hooks, mutate queues, or emit canaries.
    """
    if st is None or not isinstance(session, dict):
        return
    solo_on = bool(session.get("_solo_component_diag_enabled"))
    if not solo_on:
        try:
            from live_draft_solo_component_diagnostics import solo_component_diag_enabled

            solo_on = bool(solo_component_diag_enabled(st, session))
        except ImportError:
            solo_on = _qp_flag(st, "solo_component_diag")
        if solo_on:
            session["_solo_component_diag_enabled"] = True
    if not solo_on:
        return
    if session.get("_solo_stage1_parent_boundary_probe"):
        return
    parent_qp = False
    try:
        from live_draft_stage1_parent_boundary import stage1_parent_boundary_probe_enabled

        parent_qp = bool(stage1_parent_boundary_probe_enabled(st, session))
    except ImportError:
        parent_qp = _qp_flag(st, "solo_stage1_parent_boundary")
    if not parent_qp:
        parent_qp = _qp_flag(st, "solo_stage1_parent_boundary")
    if parent_qp:
        session["_solo_stage1_parent_boundary_probe"] = True

def queue_state_snapshot_diag_enabled(st: Any | None, session: dict[str, Any]) -> bool:
    """solo_component_diag AND solo_stage1_parent_boundary. No Francisco latch."""
    if not isinstance(session, dict):
        return False
    _refresh_queue_state_diag_latches(st, session)
    # Session latches set by existing bootstraps (work in callbacks where st may be absent).
    solo_on = bool(session.get("_solo_component_diag_enabled"))
    parent_on = bool(session.get("_solo_stage1_parent_boundary_probe"))
    if st is not None:
        try:
            from live_draft_solo_component_diagnostics import solo_component_diag_enabled

            solo_on = solo_on or bool(solo_component_diag_enabled(st, session))
        except ImportError:
            solo_on = solo_on or _qp_flag(st, "solo_component_diag")
        try:
            from live_draft_stage1_parent_boundary import stage1_parent_boundary_probe_enabled

            parent_on = parent_on or bool(stage1_parent_boundary_probe_enabled(st, session))
        except ImportError:
            parent_on = parent_on or (
                solo_on and _qp_flag(st, "solo_stage1_parent_boundary")
            )
        # Direct QP fallback: keep contract (both flags) even if helper import/order fails.
        if not parent_on and solo_on and _qp_flag(st, "solo_stage1_parent_boundary"):
            parent_on = True
            session["_solo_stage1_parent_boundary_probe"] = True
    return bool(solo_on and parent_on)


def _streamlit_session_id(session: dict[str, Any] | None = None) -> str:
    if isinstance(session, dict):
        for key in (
            "_streamlit_session_id",
            "streamlit_session_id",
            "_solo_stage1_streamlit_session_id",
        ):
            val = str(session.get(key) or "").strip()
            if val:
                return val[:64]
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        return str(getattr(ctx, "session_id", "") or "")[:64]
    except Exception:
        return ""


def _diagnostic_run_id(session: dict[str, Any]) -> str:
    return str(
        session.get("_solo_stage1_run_id")
        or session.get("diagnostic_run_id")
        or session.get("application_diagnostic_run_id")
        or ""
    )[:64]


def _room_id(session: dict[str, Any]) -> str:
    try:
        from live_draft_stage1_production_ledger import _room_fields

        return str(_room_fields(session, None).get("room_id") or "").strip().upper()[:32]
    except Exception:
        live = session.get("live_draft_room")
        if isinstance(live, dict):
            return str(live.get("draft_room_id") or live.get("draft_id") or "").strip().upper()[:32]
        return ""


def _pick_index(session: dict[str, Any]) -> Any:
    live = session.get("live_draft_room")
    if isinstance(live, dict):
        for key in ("current_pick_index", "pick_index", "current_pick"):
            if live.get(key) is not None:
                try:
                    return int(live.get(key))
                except (TypeError, ValueError):
                    return live.get(key)
    return session.get("_solo_stage1_current_pick_index")


def _full_app_run_seq(session: dict[str, Any]) -> Any:
    try:
        return int(session.get("_solo_stage1_script_run_seq") or 0)
    except (TypeError, ValueError):
        return session.get("_solo_stage1_script_run_seq")


def _recommendation_fragment_run_seq(session: dict[str, Any]) -> Any:
    try:
        return int(session.get("_solo_stage1_recommendation_fragment_run_seq") or 0)
    except (TypeError, ValueError):
        return session.get("_solo_stage1_recommendation_fragment_run_seq")


def _persist_dirty(session: dict[str, Any]) -> Any:
    try:
        from live_draft_queue_persist import DRAFT_QUEUE_PERSIST_DIRTY_KEY, is_draft_queue_persist_dirty

        if DRAFT_QUEUE_PERSIST_DIRTY_KEY in session:
            return bool(session.get(DRAFT_QUEUE_PERSIST_DIRTY_KEY))
        return bool(is_draft_queue_persist_dirty(session))
    except Exception:
        return session.get("_draft_queue_persist_dirty")


def read_session_queue(session: dict[str, Any]) -> list[str]:
    """Authoritative session draft_queue — copied list."""
    try:
        from draft_state import DRAFT_QUEUE_KEY

        raw = session.get(DRAFT_QUEUE_KEY)
    except ImportError:
        raw = session.get("draft_queue")
    return [str(x).strip() for x in (raw or []) if str(x).strip()]


def read_canonical_queue(session: dict[str, Any]) -> list[str]:
    """Authoritative draft_state.queue — independent of session draft_queue / UI / mirrors."""
    try:
        from draft_state import canonical_draft_workflow

        canon = canonical_draft_workflow(session)
        if isinstance(canon, dict):
            return [str(x).strip() for x in (canon.get("queue") or []) if str(x).strip()]
    except ImportError:
        pass
    ds = session.get("draft_state") if isinstance(session.get("draft_state"), dict) else {}
    return [str(x).strip() for x in (ds.get("queue") or []) if str(x).strip()]


def francisco_count(queue: list[Any] | None) -> int:
    target = FRANCISCO_NAME.lower()
    return sum(1 for x in list(queue or []) if str(x).strip().lower() == target)


def build_queue_state_snapshot(
    session: dict[str, Any],
    *,
    phase: str,
    added: bool | None = None,
    mutation_helper_entered: bool | None = None,
    player_name: str = "",
    event_id: str = "",
) -> dict[str, Any]:
    """Build a copied dual-queue snapshot. Read-only — does not mutate session queues."""
    sess_q = read_session_queue(session)
    canon_q = read_canonical_queue(session)
    # Explicit copies (already new lists from readers; re-copy for safety).
    sess_q = list(sess_q)
    canon_q = list(canon_q)
    return {
        "impl_rev": IMPL_REV,
        "phase": str(phase or "")[:64],
        "ts": time.time(),
        "streamlit_session_id": _streamlit_session_id(session),
        "diagnostic_run_id": _diagnostic_run_id(session),
        "room_id": _room_id(session),
        "current_pick_index": _pick_index(session),
        "full_app_run_seq": _full_app_run_seq(session),
        "recommendation_fragment_run_seq": _recommendation_fragment_run_seq(session),
        "session_queue": sess_q,
        "canonical_queue": canon_q,
        "session_queue_length": len(sess_q),
        "canonical_queue_length": len(canon_q),
        "queues_equal": sess_q == canon_q,
        "francisco_count_session": francisco_count(sess_q),
        "francisco_count_canonical": francisco_count(canon_q),
        "persist_dirty": _persist_dirty(session),
        "added": added,
        "mutation_helper_entered": mutation_helper_entered,
        "player_name": str(player_name or "").strip()[:80],
        "event_id": str(event_id or "").strip()[:64],
        "latch_required": False,
        "francisco_callback_only_required": False,
        "authoritative_membership": True,
        "ui_not_authority": True,
    }


def _append_ledger(session: dict[str, Any], snap: dict[str, Any]) -> None:
    book = session.get(SESSION_LEDGER_KEY)
    if not isinstance(book, list):
        book = []
    book = list(book) + [dict(snap)]
    session[SESSION_LEDGER_KEY] = book[-MAX_LEDGER:]
    session[SESSION_LAST_KEY] = dict(snap)
    phase = str(snap.get("phase") or "")
    if phase == PHASE_BASELINE:
        session[SESSION_BASELINE_KEY] = dict(snap)
    elif phase == PHASE_POST_ADDED:
        session[SESSION_POST_KEY] = dict(snap)
    elif phase == PHASE_POST_NO_ADD:
        # Retain as last no-add observation; do not overwrite successful post.
        session["_stage1_queue_state_snapshot_post_no_add"] = dict(snap)


def snapshot_static_root() -> Path:
    module_root = Path(__file__).resolve().parent
    candidates = (
        module_root / "static" / "queue_state",
        Path("/mount/src/baseball-stat-app/static/queue_state"),
        Path.cwd() / "static" / "queue_state",
    )
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    fallback = module_root / "static" / "queue_state"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _persist_sid_snapshot(snap: dict[str, Any]) -> str:
    """Durable SID-keyed JSON (diagnostic-only; mirrors OOB atomic-write pattern)."""
    sid = str(snap.get("streamlit_session_id") or "").strip()
    if not sid:
        return ""
    safe = sid.replace("/", "_")[:64]
    path = snapshot_static_root() / f"{safe}.json"
    payload = {
        "impl_rev": IMPL_REV,
        "streamlit_session_id": sid,
        "updated_ts": time.time(),
        "latest": dict(snap),
        "baseline": None,
        "post_mutation_added": None,
    }
    # Merge prior file if present.
    try:
        if path.is_file():
            prior = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prior, dict):
                payload["baseline"] = prior.get("baseline")
                payload["post_mutation_added"] = prior.get("post_mutation_added")
    except Exception:
        pass
    phase = str(snap.get("phase") or "")
    if phase == PHASE_BASELINE:
        payload["baseline"] = dict(snap)
    elif phase == PHASE_POST_ADDED:
        payload["post_mutation_added"] = dict(snap)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
        os.replace(tmp, path)
    return str(path)


def record_queue_state_baseline_snapshot(
    st: Any | None,
    session: dict[str, Any],
) -> dict[str, Any] | None:
    """Read-only baseline. No sync, dirty, persist, or queue mutation."""
    if not queue_state_snapshot_diag_enabled(st, session):
        return None
    snap = build_queue_state_snapshot(session, phase=PHASE_BASELINE)
    _append_ledger(session, snap)
    try:
        _persist_sid_snapshot(snap)
    except Exception:
        pass
    return dict(snap)


def record_queue_state_post_mutation_snapshot(
    session: dict[str, Any],
    *,
    added: bool,
    mutation_helper_entered: bool,
    player_name: str = "",
    event_id: str = "",
    st: Any | None = None,
) -> dict[str, Any] | None:
    """Post-path snapshot AFTER product add/sync/canonical write.

    Successful new membership → PHASE_POST_ADDED.
    No-add / duplicate → PHASE_POST_NO_ADD (not labeled successful mutation).
    """
    if not queue_state_snapshot_diag_enabled(st, session):
        return None
    phase = PHASE_POST_ADDED if bool(added) else PHASE_POST_NO_ADD
    snap = build_queue_state_snapshot(
        session,
        phase=phase,
        added=bool(added),
        mutation_helper_entered=bool(mutation_helper_entered),
        player_name=player_name,
        event_id=event_id,
    )
    _append_ledger(session, snap)
    try:
        _persist_sid_snapshot(snap)
    except Exception:
        pass
    return dict(snap)


def latest_baseline_for_sid(
    session: dict[str, Any] | None,
    *,
    streamlit_session_id: str,
    room_id: str = "",
) -> dict[str, Any] | None:
    """Select latest baseline correlating to production SID (fail closed on mismatch)."""
    sid = str(streamlit_session_id or "").strip()
    if not sid:
        return None
    candidates: list[dict[str, Any]] = []
    if isinstance(session, dict):
        book = session.get(SESSION_LEDGER_KEY)
        if isinstance(book, list):
            for row in book:
                if isinstance(row, dict) and str(row.get("phase") or "") == PHASE_BASELINE:
                    candidates.append(dict(row))
        base = session.get(SESSION_BASELINE_KEY)
        if isinstance(base, dict):
            candidates.append(dict(base))
    # Also try durable file.
    try:
        path = snapshot_static_root() / f"{sid.replace('/', '_')[:64]}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            b = payload.get("baseline") if isinstance(payload, dict) else None
            if isinstance(b, dict):
                candidates.append(dict(b))
    except Exception:
        pass
    matched = [
        c
        for c in candidates
        if str(c.get("streamlit_session_id") or "").strip() == sid
    ]
    if room_id:
        room = str(room_id or "").strip().upper()
        matched = [
            c
            for c in matched
            if str(c.get("room_id") or "").strip().upper() == room
        ]
    if not matched:
        return None
    matched.sort(key=lambda r: float(r.get("ts") or 0))
    return dict(matched[-1])


def latest_post_added_for_sid(
    session: dict[str, Any] | None,
    *,
    streamlit_session_id: str,
    room_id: str = "",
    after_ts: float | None = None,
) -> dict[str, Any] | None:
    sid = str(streamlit_session_id or "").strip()
    if not sid:
        return None
    candidates: list[dict[str, Any]] = []
    if isinstance(session, dict):
        book = session.get(SESSION_LEDGER_KEY)
        if isinstance(book, list):
            for row in book:
                if isinstance(row, dict) and str(row.get("phase") or "") == PHASE_POST_ADDED:
                    candidates.append(dict(row))
        post = session.get(SESSION_POST_KEY)
        if isinstance(post, dict) and str(post.get("phase") or "") == PHASE_POST_ADDED:
            candidates.append(dict(post))
    try:
        path = snapshot_static_root() / f"{sid.replace('/', '_')[:64]}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            p = payload.get("post_mutation_added") if isinstance(payload, dict) else None
            if isinstance(p, dict):
                candidates.append(dict(p))
    except Exception:
        pass
    matched = [
        c
        for c in candidates
        if str(c.get("streamlit_session_id") or "").strip() == sid
    ]
    if room_id:
        room = str(room_id or "").strip().upper()
        matched = [
            c
            for c in matched
            if str(c.get("room_id") or "").strip().upper() == room
        ]
    if after_ts is not None:
        matched = [c for c in matched if float(c.get("ts") or 0) > float(after_ts)]
    if not matched:
        return None
    matched.sort(key=lambda r: float(r.get("ts") or 0))
    return dict(matched[-1])


def render_queue_state_snapshot_probe(st: Any, session: dict[str, Any]) -> None:
    """Hidden DOM probe for Playwright scrape (diag-gated)."""
    # Refresh latches before gate so parent_boundary is not dropped when solo
    # was latched earlier but parent was not (production 961e9378 failure mode).
    _refresh_queue_state_diag_latches(st, session)
    if not queue_state_snapshot_diag_enabled(st, session):
        return
    # Refresh baseline on render so pre-click evidence stays current.
    # Empty queues [] are valid and MUST still emit (never treat as missing).
    record_queue_state_baseline_snapshot(st, session)
    baseline = dict(session.get(SESSION_BASELINE_KEY) or {})
    post = dict(session.get(SESSION_POST_KEY) or {})
    last = dict(session.get(SESSION_LAST_KEY) or {})
    # Prefer last/baseline even when queues are empty lists.
    payload = {
        "impl_rev": IMPL_REV,
        "baseline": baseline,
        "post_mutation_added": post if str(post.get("phase") or "") == PHASE_POST_ADDED else {},
        "last": last,
    }
    raw = json.dumps(payload, default=str)[:12000]
    safe = lambda s: str(s or "").replace('"', "'")[:120]
    # queues_equal: use explicit True check so False and missing stay 0; empty==empty is True.
    queues_equal_attr = "1" if baseline.get("queues_equal") is True else "0"
    st.markdown(
        f'<div id="{PROBE_ID}" '
        f'data-impl-rev="{safe(IMPL_REV)}" '
        f'data-sid="{safe(baseline.get("streamlit_session_id") or last.get("streamlit_session_id"))}" '
        f'data-run-id="{safe(baseline.get("diagnostic_run_id") or last.get("diagnostic_run_id"))}" '
        f'data-room-id="{safe(baseline.get("room_id") or last.get("room_id"))}" '
        f'data-phase="{safe(baseline.get("phase") or PHASE_BASELINE)}" '
        f'data-baseline-ts="{safe(baseline.get("ts"))}" '
        f'data-post-ts="{safe(post.get("ts"))}" '
        f'data-queues-equal="{queues_equal_attr}" '
        f'data-session-len="{int(baseline.get("session_queue_length") or 0)}" '
        f'data-canonical-len="{int(baseline.get("canonical_queue_length") or 0)}" '
        f'data-json="{raw.replace(chr(34), chr(39))}"></div>',
        unsafe_allow_html=True,
    )


def scrape_queue_state_snapshot_from_page(page: Any) -> dict[str, Any]:
    """Playwright helper — scrape DOM probe (runner-side)."""
    try:
        raw = page.evaluate(
            f"""() => {{
            const docs = [document];
            for (const f of document.querySelectorAll('iframe')) {{
              try {{ if (f.contentDocument) docs.push(f.contentDocument); }} catch (e) {{}}
            }}
            for (const doc of docs) {{
              const el = doc.querySelector('#{PROBE_ID}');
              if (!el) continue;
              return {{
                probe_found: true,
                sid: el.getAttribute('data-sid') || '',
                run_id: el.getAttribute('data-run-id') || '',
                room_id: el.getAttribute('data-room-id') || '',
                phase: el.getAttribute('data-phase') || '',
                baseline_ts: el.getAttribute('data-baseline-ts') || '',
                post_ts: el.getAttribute('data-post-ts') || '',
                session_len: el.getAttribute('data-session-len') || '',
                canonical_len: el.getAttribute('data-canonical-len') || '',
                json: el.getAttribute('data-json') || '',
              }};
            }}
            return {{ probe_found: false }};
          }}"""
        )
    except Exception as exc:
        return {"error": str(exc)[:200], "probe_found": False}
    if not isinstance(raw, dict):
        return {"probe_found": False}
    out = dict(raw)
    if out.get("probe_found") is not True and not out.get("json") and not out.get("sid"):
        out["probe_found"] = False
    payload = out.get("json")
    if isinstance(payload, str) and payload.strip():
        try:
            out["payload"] = json.loads(payload.replace("'", '"'))
        except Exception:
            out["payload_raw"] = payload[:4000]
    return out


def wait_and_scrape_queue_state_snapshot_from_page(
    page: Any,
    *,
    timeout_s: float = 20.0,
    poll_s: float = 0.5,
) -> dict[str, Any]:
    """Poll until #stage1-queue-state-snapshot is present, then scrape.

    Empty baseline queues are valid; only absence of the probe element retries.
    """
    deadline = time.time() + max(0.5, float(timeout_s))
    last: dict[str, Any] = {"probe_found": False}
    while time.time() < deadline:
        last = scrape_queue_state_snapshot_from_page(page)
        if last.get("probe_found") is True or (
            isinstance(last.get("payload"), dict) and last.get("payload")
        ):
            last["waited_for_probe"] = True
            return last
        try:
            page.wait_for_timeout(int(max(0.05, float(poll_s)) * 1000))
        except Exception:
            time.sleep(max(0.05, float(poll_s)))
    last = scrape_queue_state_snapshot_from_page(page)
    last["waited_for_probe"] = True
    last["probe_wait_timeout"] = True
    return last
