"""Reconcile lifecycle script_run_seq vs current app-generation vs historical ledger observers.

Diagnosis: harness historically queried ``#solo-production-ledger-diag``, which the app never
rendered. Current generation lives on ``#solo-stage1-current-run-diag`` and
``#solo-stage1-production-ledger`` (``data-script-run-seq``). Append-only ledger row max/last
may lag when no event row was appended for later script runs.
"""

from __future__ import annotations

import time
from typing import Any

QUEUE1C3A2O1 = "QUEUE1C3A2O1"
QUEUE1C3A2O1A = "QUEUE1C3A2O1A"
QUEUE1C3A2O1B = "QUEUE1C3A2O1B"
QUEUE1C3A2O2 = "QUEUE1C3A2O2"

BINDING_MODE_CONTROL_ONLY = "control_only"
BINDING_MODE_RECOMMENDATION_WIDGET = "recommendation_widget"

_CURRENT_APP_RUN_DIAG_JS = """() => {
  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
  function rowFromEl(el, root, href, probeId, domIndex) {
    const r = el.getBoundingClientRect();
    return {
      probe_id: probeId,
      dom_index: domIndex,
      frame_href: href,
      script_run_seq: el.getAttribute('data-script-run-seq') || el.getAttribute('data-run-seq') || '',
      run_id: el.getAttribute('data-run-id') || el.getAttribute('data-diagnostic-run-id') || '',
      streamlit_session_id: el.getAttribute('data-streamlit-session-id') || '',
      room_id: el.getAttribute('data-room-id') || '',
      deployment_sha: el.getAttribute('data-deployment-sha') || '',
      active_page: el.getAttribute('data-active-page') || '',
      fragment_run_hint: el.getAttribute('data-fragment-run-hint') || '',
      impl_rev: el.getAttribute('data-impl-rev') || '',
      probe_ts: el.getAttribute('data-probe-ts') || '',
      probe_checkpoint: el.getAttribute('data-probe-checkpoint') || '',
      attached: !!el.isConnected,
      visible: !!(r && r.width > 0 && r.height > 0),
    };
  }
  const out = [];
  for (const root of roots()) {
    const href = (root.defaultView && root.defaultView.location && root.defaultView.location.href) || '';
    let idx = 0;
    for (const el of root.querySelectorAll('#solo-stage1-current-run-diag')) {
      out.push(rowFromEl(el, root, href, 'solo-stage1-current-run-diag', idx++));
    }
    for (const el of root.querySelectorAll('#solo-stage1-production-ledger')) {
      out.push(rowFromEl(el, root, href, 'solo-stage1-production-ledger', idx++));
    }
  }
  return out;
}"""


def _parse_int_seq(value: Any) -> int | None:
    try:
        s = str(value or "").strip()
        if not s:
            return None
        return int(s)
    except (TypeError, ValueError):
        return None


def scrape_current_app_run_diag_probes(page) -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(_CURRENT_APP_RUN_DIAG_JS) or []
        return [r for r in raw if isinstance(r, dict)]
    except Exception:
        return []


def _frame_matches_hint(href: str, hint: str) -> bool:
    if not hint:
        return "/~/" in href or "~/+" in href
    return bool(href and (hint in href or href in hint))


def _parse_probe_ts(value: Any) -> float:
    try:
        return float(str(value or "").strip())
    except (TypeError, ValueError):
        return 0.0


def select_current_app_diag_probe(
    probes: list[dict[str, Any]],
    *,
    frame_url_hint: str = "",
    expected_room_id: str = "",
    expected_session_id: str = "",
    expected_deployment_sha: str = "",
    require_live_draft_page: bool = True,
) -> dict[str, Any]:
    """Filter bound candidates in authoritative frame; pick highest script_run_seq (then newest ts)."""
    hint = str(frame_url_hint or "").strip()
    exp_room = str(expected_room_id or "").strip().upper()[:32]
    exp_session = str(expected_session_id or "").strip()
    exp_deploy = str(expected_deployment_sha or "").strip().lower()[:7]

    candidates: list[dict[str, Any]] = []
    for p in probes:
        if not isinstance(p, dict):
            continue
        href = str(p.get("frame_href") or "")
        if not _frame_matches_hint(href, hint):
            continue
        seq = _parse_int_seq(p.get("script_run_seq"))
        if seq is None:
            continue
        session = str(p.get("streamlit_session_id") or "").strip()
        room = str(p.get("room_id") or "").strip().upper()[:32]
        deploy = str(p.get("deployment_sha") or "").strip().lower()[:7]
        active = str(p.get("active_page") or "").strip()
        if exp_session and session and session != exp_session:
            continue
        if exp_room and room and room != exp_room:
            continue
        if exp_deploy and deploy and deploy != exp_deploy:
            continue
        if require_live_draft_page and active and "live draft" not in active.lower():
            continue
        row = dict(p)
        row["script_run_seq_int"] = seq
        row["probe_ts_float"] = _parse_probe_ts(p.get("probe_ts"))
        candidates.append(row)

    selection: dict[str, Any] = {
        "current_app_diag_candidates": [
            {
                "probe_id": c.get("probe_id"),
                "dom_index": c.get("dom_index"),
                "script_run_seq": c.get("script_run_seq_int"),
                "streamlit_session_id": c.get("streamlit_session_id"),
                "room_id": c.get("room_id"),
                "active_page": c.get("active_page"),
                "probe_ts": c.get("probe_ts"),
                "deployment_sha": c.get("deployment_sha"),
                "fragment_run_hint": c.get("fragment_run_hint"),
                "impl_rev": c.get("impl_rev"),
                "frame_href": str(c.get("frame_href") or "")[:120],
                "attached": c.get("attached"),
                "visible": c.get("visible"),
            }
            for c in candidates
        ],
        "current_app_diag_candidate_count": len(candidates),
        "current_diag_selection_reason": "",
        "stale_current_diag_probe_seqs": [],
    }

    if not candidates:
        selection["current_diag_selection_reason"] = "no_bound_candidates_after_filter"
        return {"selected": {}, "selection": selection}

    ranked = sorted(
        candidates,
        key=lambda c: (int(c["script_run_seq_int"]), float(c["probe_ts_float"]), int(c.get("dom_index") or 0)),
        reverse=True,
    )
    selected = ranked[0]
    selected_seq = int(selected["script_run_seq_int"])
    max_seq = max(int(c["script_run_seq_int"]) for c in candidates)
    selection["current_app_diag_max_candidate_seq"] = max_seq
    selection["current_app_diag_selected_seq"] = selected_seq
    selection["current_app_diag_selected_ts"] = selected.get("probe_ts")
    selection["current_diag_selection_reason"] = (
        "highest_script_run_seq_among_session_room_frame_bound_candidates"
    )
    selection["stale_current_diag_probe_seqs"] = sorted(
        {
            int(c["script_run_seq_int"])
            for c in candidates
            if int(c["script_run_seq_int"]) < selected_seq
        }
    )
    return {"selected": selected, "selection": selection}


def pick_authoritative_current_app_probe(
    probes: list[dict[str, Any]], *, frame_url_hint: str = "", expected_room_id: str = ""
) -> dict[str, Any]:
    return select_current_app_diag_probe(
        probes, frame_url_hint=frame_url_hint, expected_room_id=expected_room_id
    )["selected"]


def scrape_ledger_row_seq_stats(page) -> dict[str, Any]:
    try:
        from p8_production_start_harness import scrape_stage1_ledger_rows

        rows = scrape_stage1_ledger_rows(page) or []
    except Exception:
        rows = []
    seqs: list[int] = []
    last_row_seq: int | None = None
    if rows:
        last_row_seq = _parse_int_seq(rows[-1].get("script_run_seq"))
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = _parse_int_seq(r.get("script_run_seq"))
        if v is not None:
            seqs.append(v)
    return {
        "ledger_row_count": len(rows),
        "ledger_last_row_script_run_seq": last_row_seq,
        "ledger_max_script_run_seq": max(seqs) if seqs else None,
        "ledger_min_script_run_seq": min(seqs) if seqs else None,
        "ledger_last_row_seq_source": "scrape_stage1_ledger_rows[-1].script_run_seq (historical, not authoritative)",
        "ledger_max_seq_source": "max(scrape_stage1_ledger_rows[*].script_run_seq) (historical, not authoritative)",
    }


def lifecycle_seq_from_render_trace(trace: dict[str, Any] | None) -> dict[str, Any]:
    tr = trace if isinstance(trace, dict) else {}
    return {
        "lifecycle_current_script_run_seq": _parse_int_seq(tr.get("current_script_run_seq")),
        "lifecycle_actual_card_render_run_seq": _parse_int_seq(tr.get("actual_card_render_run_seq")),
        "lifecycle_widget_last_rendered_run_seq": _parse_int_seq(tr.get("widget_last_rendered_run_seq")),
        "lifecycle_room_id": str(tr.get("room_id") or "").strip().upper()[:32],
        "lifecycle_source": "rec_card_render_trace_dom",
        "lifecycle_probe_source": str(tr.get("probe_source") or ""),
        "lifecycle_widget_liveness": str(tr.get("widget_liveness") or ""),
    }


def compute_recommendation_widget_binding(
    *,
    lifecycle_seq: int | None,
    lifecycle_room_id: str,
    current_diag: dict[str, Any],
    ledger_max: int | None,
    ledger_last: int | None,
    expected_room_id: str = "",
) -> tuple[bool, list[str], dict[str, Any]]:
    """Francisco: lifecycle (A) must match current app-generation probe (B); ledger (C) is historical."""
    notes: list[str] = []
    current_seq = _parse_int_seq(current_diag.get("script_run_seq"))
    diag_session = str(current_diag.get("streamlit_session_id") or "").strip()
    diag_room = str(current_diag.get("room_id") or "").strip().upper()[:32]
    probe_id = str(current_diag.get("probe_id") or "")

    meta: dict[str, Any] = {
        "binding_mode": BINDING_MODE_RECOMMENDATION_WIDGET,
        "lifecycle_not_applicable": False,
        "lifecycle_seq": lifecycle_seq,
        "current_app_diag_seq": current_seq,
        "current_app_diag_probe_id": probe_id,
        "current_app_diag_streamlit_session_id": diag_session,
        "current_app_diag_room_id": diag_room,
        "current_app_diag_frame_href": str(current_diag.get("frame_href") or "")[:280],
        "current_app_diag_impl_rev": str(current_diag.get("impl_rev") or ""),
        "ledger_max_seq": ledger_max,
        "ledger_last_row_seq": ledger_last,
        "lifecycle_vs_current_diag_match": False,
        "ledger_history_lag": False,
        "binding_authorities": [],
    }

    if lifecycle_seq is None:
        notes.append("lifecycle_seq_missing")
    if current_seq is None or not probe_id:
        notes.append("current_app_diag_missing")

    if lifecycle_seq is not None and current_seq is not None:
        meta["lifecycle_vs_current_diag_match"] = lifecycle_seq == current_seq
        if lifecycle_seq != current_seq:
            notes.append(f"lifecycle_{lifecycle_seq}_vs_current_app_diag_{current_seq}")

    if current_seq is not None and not diag_session:
        notes.append("current_app_diag_session_missing")

    exp_room = str(expected_room_id or lifecycle_room_id or "").strip().upper()[:32]
    if exp_room and diag_room and exp_room != diag_room:
        notes.append(f"room_mismatch_expected_{exp_room}_diag_{diag_room}")
    if lifecycle_room_id and diag_room and lifecycle_room_id.upper() != diag_room:
        notes.append(f"lifecycle_room_{lifecycle_room_id}_vs_diag_room_{diag_room}")

    if ledger_max is not None and lifecycle_seq is not None and ledger_max < lifecycle_seq:
        meta["ledger_history_lag"] = True
        notes.append(f"ledger_history_lag_max_{ledger_max}_behind_lifecycle_{lifecycle_seq}")

    if ledger_last is not None and ledger_max is not None and ledger_last != ledger_max:
        meta["ledger_last_row_stale"] = True
        notes.append(f"ledger_last_row_stale_historical_{ledger_last}_vs_max_{ledger_max}")
    else:
        meta["ledger_last_row_stale"] = False

    informational = ("ledger_history_lag_", "ledger_last_row_stale_")
    blocking = [n for n in notes if not any(n.startswith(p) for p in informational)]

    consistent = False
    if (
        not blocking
        and lifecycle_seq is not None
        and current_seq is not None
        and lifecycle_seq == current_seq
        and bool(diag_session)
    ):
        consistent = True
        meta["binding_authorities"] = ["rec_lifecycle", "current_app_diag"]

    return consistent, notes, meta


def compute_control_only_binding(
    *,
    current_diag: dict[str, Any],
    ledger_max: int | None,
    ledger_last: int | None,
) -> tuple[bool, list[str], dict[str, Any]]:
    notes: list[str] = []
    current_seq = _parse_int_seq(current_diag.get("script_run_seq"))
    transport_grade = current_seq if current_seq is not None else ledger_max
    meta: dict[str, Any] = {
        "binding_mode": BINDING_MODE_CONTROL_ONLY,
        "lifecycle_not_applicable": True,
        "current_app_diag_seq": current_seq,
        "ledger_last_row_stale": False,
        "ledger_transport_grade_precedence": [],
    }
    if current_seq is not None:
        meta["ledger_transport_grade_precedence"].append("current_app_run_diag")
    elif ledger_max is not None:
        meta["ledger_transport_grade_precedence"].append("ledger_max_script_run_seq")
    if ledger_last is not None and transport_grade is not None and ledger_last != transport_grade:
        meta["ledger_last_row_stale"] = True
        notes.append(f"last_row_stale_historical_{ledger_last}_vs_grade_{transport_grade}")
    if transport_grade is None:
        notes.append("current_generation_seq_missing")
        return False, notes, meta
    return True, notes, meta


def capture_run_binding_snapshot(
    page,
    *,
    frame_url_hint: str = "",
    lifecycle_render_trace: dict[str, Any] | None = None,
    phase: str = "pre_click",
    binding_mode: str = BINDING_MODE_RECOMMENDATION_WIDGET,
    expected_room_id: str = "",
) -> dict[str, Any]:
    """Snapshot lifecycle vs current app-generation probe vs historical ledger rows."""
    ts = time.time()
    mode = binding_mode or BINDING_MODE_RECOMMENDATION_WIDGET
    lifecycle = lifecycle_seq_from_render_trace(lifecycle_render_trace)
    if mode == BINDING_MODE_RECOMMENDATION_WIDGET and lifecycle_render_trace is None:
        try:
            from stage1_rec_queue_click_trace_scrape import scrape_rec_queue_render_trace

            scraped = scrape_rec_queue_render_trace(page, player_name="")
            lifecycle = lifecycle_seq_from_render_trace(scraped)
        except ImportError:
            pass
    elif mode == BINDING_MODE_CONTROL_ONLY:
        lifecycle = {
            "lifecycle_current_script_run_seq": None,
            "lifecycle_actual_card_render_run_seq": None,
            "lifecycle_widget_last_rendered_run_seq": None,
            "lifecycle_room_id": "",
            "lifecycle_source": "not_applicable_control_only",
            "lifecycle_probe_source": "",
            "lifecycle_widget_liveness": "",
        }

    current_probes = scrape_current_app_run_diag_probes(page)
    lifecycle_room = str(lifecycle.get("lifecycle_room_id") or expected_room_id or "")
    pick = select_current_app_diag_probe(
        current_probes,
        frame_url_hint=frame_url_hint,
        expected_room_id=lifecycle_room or expected_room_id,
    )
    current_app = pick["selected"]
    selection_meta = pick["selection"]
    row_stats = scrape_ledger_row_seq_stats(page)

    lifecycle_seq = lifecycle.get("lifecycle_current_script_run_seq")
    if lifecycle_seq is None:
        lifecycle_seq = lifecycle.get("lifecycle_actual_card_render_run_seq")

    ledger_max = row_stats.get("ledger_max_script_run_seq")
    ledger_last = row_stats.get("ledger_last_row_script_run_seq")
    current_seq = _parse_int_seq(current_app.get("script_run_seq"))

    if mode == BINDING_MODE_CONTROL_ONLY:
        consistent, mismatch_reasons, binding_meta = compute_control_only_binding(
            current_diag=current_app,
            ledger_max=ledger_max,
            ledger_last=ledger_last,
        )
        transport_grade_seq = current_seq if current_seq is not None else ledger_max
    else:
        consistent, mismatch_reasons, binding_meta = compute_recommendation_widget_binding(
            lifecycle_seq=lifecycle_seq,
            lifecycle_room_id=str(lifecycle.get("lifecycle_room_id") or ""),
            current_diag=current_app,
            ledger_max=ledger_max,
            ledger_last=ledger_last,
            expected_room_id=expected_room_id,
        )
        transport_grade_seq = current_seq if current_seq is not None else None

    binding_meta = {**binding_meta, **selection_meta}

    return {
        "phase": phase,
        "wall_ts": ts,
        "frame_url_hint": str(frame_url_hint or "")[:280],
        "streamlit_session_id": str(current_app.get("streamlit_session_id") or ""),
        "ledger_diag_frame_href": str(current_app.get("frame_href") or "")[:280],
        **lifecycle,
        **row_stats,
        **binding_meta,
        "ledger_diag_script_run_seq": current_seq,
        "ledger_transport_grade_script_run_seq": transport_grade_seq,
        "run_binding_consistent": consistent,
        "run_binding_mismatch_reasons": mismatch_reasons,
        "current_app_diag_probe_count": len(current_probes),
        "ledger_diag_probe_count": len(current_probes),
        "current_run_diag_ids_seen": [
            int(_parse_int_seq(p.get("script_run_seq")))
            for p in current_probes
            if str(p.get("probe_id") or "") == "solo-stage1-current-run-diag"
            and _parse_int_seq(p.get("script_run_seq")) is not None
        ],
    }


def classify_recommendation_o1_subcode(binding: dict[str, Any]) -> str:
    """Distinguish selector stale pick (O1A) vs true lifecycle/diag disagreement (O1/O1B)."""
    if binding.get("run_binding_consistent"):
        return ""
    lifecycle_seq = binding.get("lifecycle_seq") or binding.get("lifecycle_current_script_run_seq")
    selected = binding.get("current_app_diag_selected_seq") or binding.get("current_app_diag_seq")
    max_cand = binding.get("current_app_diag_max_candidate_seq")
    try:
        life_i = int(lifecycle_seq) if lifecycle_seq is not None else None
        sel_i = int(selected) if selected is not None else None
        max_i = int(max_cand) if max_cand is not None else None
    except (TypeError, ValueError):
        life_i = sel_i = max_i = None
    if life_i is not None and max_i is not None and sel_i is not None:
        if life_i == max_i and sel_i < max_i:
            return QUEUE1C3A2O1A
        if life_i != max_i and max_i == sel_i:
            return QUEUE1C3A2O1B
    reasons = list(binding.get("run_binding_mismatch_reasons") or [])
    if "current_app_diag_missing" in reasons:
        return QUEUE1C3A2O1B
    return QUEUE1C3A2O1


def control_only_pause_binding_passes(
    pre_binding: dict[str, Any],
    *,
    pause_delivery_resolved: bool,
    dom_events_non_empty: bool,
    dom_install_ok: bool,
) -> bool:
    """Known-good Pause control observability gate (does not require rec-card lifecycle)."""
    if not pause_delivery_resolved:
        return False
    if not dom_install_ok or not dom_events_non_empty:
        return False
    if str(pre_binding.get("binding_mode") or "") != BINDING_MODE_CONTROL_ONLY:
        return False
    return bool(pre_binding.get("run_binding_consistent"))


def merge_run_binding_into_transport(transport: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    out = dict(transport)
    mode = str(binding.get("binding_mode") or BINDING_MODE_RECOMMENDATION_WIDGET)
    pre = binding.get("current_app_diag_seq")
    if pre is None:
        pre = binding.get("ledger_transport_grade_script_run_seq")
    post_binding = binding if binding.get("phase") == "post_click" else {}
    post_seq = post_binding.get("current_app_diag_seq")
    if post_seq is None:
        post_seq = post_binding.get("ledger_transport_grade_script_run_seq", pre)
    pre_s = str(pre) if pre is not None else ""
    post_s = str(post_seq) if post_seq is not None else ""
    out["run_binding"] = binding
    out["binding_mode"] = mode
    out["lifecycle_script_run_seq_before"] = binding.get("lifecycle_current_script_run_seq")
    out["ledger_transport_grade_seq_before"] = pre
    out["ledger_last_row_seq_before"] = binding.get("ledger_last_row_script_run_seq")
    out["run_binding_consistent"] = bool(binding.get("run_binding_consistent"))
    out["script_run_seq_before"] = pre_s
    out["ledger_script_run_seq_after"] = post_s
    seq_changed = False
    if pre_s and post_s:
        try:
            seq_changed = int(post_s) > int(pre_s)
        except ValueError:
            seq_changed = post_s != pre_s
    out["script_run_seq_changed"] = seq_changed
    if not out.get("run_binding_consistent") and mode == BINDING_MODE_RECOMMENDATION_WIDGET:
        out["python_rerun_started"] = False
        out["python_rerun_observability_blocked"] = True
    else:
        out["python_rerun_observability_blocked"] = False
        if mode == BINDING_MODE_RECOMMENDATION_WIDGET:
            out["python_rerun_started"] = bool(seq_changed)
    return out


def classify_run_binding_observability(
    pre: dict[str, Any],
    *,
    dom_capture_ok: bool = True,
    binding_mode: str = BINDING_MODE_RECOMMENDATION_WIDGET,
) -> str:
    mode = str(pre.get("binding_mode") or binding_mode or BINDING_MODE_RECOMMENDATION_WIDGET)
    if mode == BINDING_MODE_CONTROL_ONLY:
        if not pre.get("run_binding_consistent"):
            return QUEUE1C3A2O1
        if not dom_capture_ok:
            return QUEUE1C3A2O2
        return ""
    if not pre.get("run_binding_consistent"):
        return QUEUE1C3A2O1
    if not dom_capture_ok:
        return QUEUE1C3A2O2
    return ""


# Backward-compatible names for older scripts/tests
def scrape_ledger_diag_probes(page) -> list[dict[str, Any]]:
    return scrape_current_app_run_diag_probes(page)


def pick_authoritative_ledger_probe(probes: list[dict[str, Any]], *, frame_url_hint: str = "") -> dict[str, Any]:
    return pick_authoritative_current_app_probe(probes, frame_url_hint=frame_url_hint)


def compute_run_binding_verdict(
    *,
    binding_mode: str,
    lifecycle_seq: int | None,
    transport_grade_seq: int | None,
    ledger_last: int | None,
    ledger_diag_seq: int | None,
    lifecycle_room_id: str = "",
    current_diag: dict[str, Any] | None = None,
    ledger_max: int | None = None,
    expected_room_id: str = "",
) -> tuple[bool, list[str], dict[str, Any]]:
    """Pure binding grade (tests). Recommendation mode requires current_diag."""
    mode = binding_mode or BINDING_MODE_RECOMMENDATION_WIDGET
    if mode == BINDING_MODE_CONTROL_ONLY:
        return compute_control_only_binding(
            current_diag=current_diag or {},
            ledger_max=ledger_max if ledger_max is not None else transport_grade_seq,
            ledger_last=ledger_last,
        )
    return compute_recommendation_widget_binding(
        lifecycle_seq=lifecycle_seq,
        lifecycle_room_id=lifecycle_room_id,
        current_diag=current_diag or {"script_run_seq": ledger_diag_seq, "probe_id": "test"},
        ledger_max=ledger_max if ledger_max is not None else transport_grade_seq,
        ledger_last=ledger_last,
        expected_room_id=expected_room_id,
    )
