"""Helpers for Pause → fragment probe → Francisco production fragment diagnostic gate."""

from __future__ import annotations

import time
from typing import Any

OBSERVABILITY_FRAGMENT_LEDGER_NOT_VISIBLE = "OBSERVABILITY_FRAGMENT_LEDGER_NOT_VISIBLE"


def callback_ledger_dom_observable(scrape: dict[str, Any] | None) -> bool:
    if not isinstance(scrape, dict) or scrape.get("error"):
        return False
    if not str(scrape.get("impl_rev") or "").strip():
        return False
    return scrape.get("ledger_len") is not None and str(scrape.get("ledger_len")) != ""


def snapshot_fragment_lifecycle(page, *, stage: str) -> dict[str, Any]:
    ctx = snapshot_fragment_exec_context(page)
    probe = ctx.get("fragment_widget_probe") if isinstance(ctx.get("fragment_widget_probe"), dict) else {}
    francisco_probe = ctx.get("francisco_exec_probe") if isinstance(ctx.get("francisco_exec_probe"), dict) else {}
    rt = ctx.get("francisco_render_trace") if isinstance(ctx.get("francisco_render_trace"), dict) else {}
    binding = ctx.get("full_app_binding") if isinstance(ctx.get("full_app_binding"), dict) else {}
    return {
        "stage": stage,
        "ts": time.time(),
        "recommendation_fragment_run_seq_probe": probe.get("recommendation_fragment_run_seq"),
        "recommendation_fragment_run_seq_francisco_probe": francisco_probe.get("recommendation_fragment_run_seq"),
        "recommendation_fragment_run_seq_render_trace": rt.get("current_script_run_seq"),
        "paint_via_probe": probe.get("paint_via"),
        "paint_via_francisco": francisco_probe.get("paint_via"),
        "fragment_context_probe": probe.get("fragment_context"),
        "heavy_paint_done": rt.get("heavy_paint_done"),
        "widget_liveness": rt.get("widget_liveness"),
        "probe_source": rt.get("probe_source"),
        "paint_body_executed_vs_reemit_only": (
            "reemit_only"
            if str(rt.get("probe_source") or "") == "registry_reemit"
            else "paint_body_or_actual_render"
            if rt.get("widget_liveness") == "live_this_run"
            else "unknown"
        ),
        "full_app_run_seq": binding.get("current_app_diag_seq") or binding.get("lifecycle_current_script_run_seq"),
        "callback_ledger_observable": callback_ledger_dom_observable(ctx.get("callback_ledger_scrape")),
        "ledger_len": (ctx.get("callback_ledger_scrape") or {}).get("ledger_len"),
    }


def snapshot_fragment_exec_context(page) -> dict[str, Any]:
    from stage1_rec_fragment_exec_scrape import scrape_fragment_callback_ledger, scrape_fragment_exec_probes
    from stage1_run_binding import BINDING_MODE_RECOMMENDATION_WIDGET, capture_run_binding_snapshot
    from stage1_rec_queue_click_trace_scrape import scrape_rec_queue_render_trace

    probes = scrape_fragment_exec_probes(page)
    probe_btn = next((p for p in probes if p.get("widget_kind") == "fragment_widget_probe"), {})
    francisco = next((p for p in probes if p.get("widget_kind") == "francisco_add_to_queue"), {})
    francisco_name = str(francisco.get("player_name") or "Francisco Lindor").strip()
    render_trace = scrape_rec_queue_render_trace(page, player_name=francisco_name)
    binding = capture_run_binding_snapshot(
        page,
        frame_url_hint="",
        lifecycle_render_trace=render_trace if render_trace.get("widget_key") else None,
        phase="fragment_exec_snapshot",
        binding_mode=BINDING_MODE_RECOMMENDATION_WIDGET,
    )
    ledger = scrape_fragment_callback_ledger(page)
    return {
        "ts": time.time(),
        "full_app_binding": binding,
        "fragment_exec_probes": probes,
        "fragment_widget_probe": probe_btn,
        "francisco_exec_probe": francisco,
        "francisco_render_trace": render_trace,
        "callback_ledger_scrape": ledger,
        "ledger_payload": ledger.get("payload") if isinstance(ledger.get("payload"), dict) else {},
    }


def _app_frame(page):
    for fr in page.frames:
        url = str(fr.url or "")
        if "/~/" in url or "~/+" in url:
            return fr
    return page.main_frame


def prove_fragment_probe_rendered(ctx: dict[str, Any], *, room_id: str) -> tuple[bool, str]:
    probe = ctx.get("fragment_widget_probe") if isinstance(ctx.get("fragment_widget_probe"), dict) else {}
    if not probe.get("widget_key"):
        return False, "fragment_widget_probe_dom_missing"
    rid = str(room_id or "").strip().upper()[:16]
    if rid and str(probe.get("room_id") or "").strip().upper()[:16] not in ("", rid):
        return False, "fragment_probe_room_mismatch"
    if str(probe.get("pick_index") or "") not in ("", "0"):
        return False, "fragment_probe_pick_not_zero"
    return True, ""


def _ledger_delta(
    before_payload: dict[str, Any],
    after_payload: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    before_len = int(before_payload.get("ledger_len") or 0)
    after_len = int(after_payload.get("ledger_len") or 0)
    last = ledger_last_for_source(after_payload, source)
    if not last and isinstance(after_payload.get("last"), dict):
        row = after_payload["last"]
        if str(row.get("source") or "") == source:
            last = dict(row)
    return {
        "ledger_len_before": before_len,
        "ledger_len_after": after_len,
        "new_event": after_len > before_len or bool(last.get("event_id")),
        "callback_ledger_last": last,
        "callback_entered": bool(last.get("callback_entered")),
    }


def click_fragment_widget_probe(page, *, settle_ms: int = 3500) -> dict[str, Any]:
    from stage1_dom_click_capture import (
        CAPTURE_TARGET_FRAGMENT_PROBE,
        prepare_isolated_dom_click_capture,
        read_and_summarize_dom_click_capture,
    )
    from stage1_rec_fragment_exec_scrape import scrape_fragment_callback_ledger

    out: dict[str, Any] = {"control": "B_fragment_widget_probe", "started_ts": time.time()}
    out["lifecycle_before"] = snapshot_fragment_lifecycle(page, stage="before_probe_click")
    out["pre"] = snapshot_fragment_exec_context(page)
    before_payload = dict(out["pre"].get("ledger_payload") or {})
    fr = _app_frame(page)
    prep = prepare_isolated_dom_click_capture(
        fr,
        capture_target=CAPTURE_TARGET_FRAGMENT_PROBE,
        frame_url_hint=str(fr.url or ""),
    )
    out["dom_click_capture_prep"] = prep
    label = "Stage1 Recommendation Widget Probe"
    clicked = False
    err = ""
    try:
        loc = fr.get_by_role("button", name=label, exact=False)
        if loc.count() == 0:
            loc = page.get_by_role("button", name=label, exact=False)
        loc.first.scroll_into_view_if_needed(timeout=8000)
        loc.first.click(timeout=8000)
        clicked = True
    except Exception as exc:
        err = f"{type(exc).__name__}:{exc}"
    out["click_dispatched"] = clicked
    out["click_error"] = err[:240]
    page.wait_for_timeout(min(settle_ms, 800))
    dom = read_and_summarize_dom_click_capture(fr, capture_target=CAPTURE_TARGET_FRAGMENT_PROBE)
    dom["capture_cleared_before_click"] = bool(prep.get("capture_cleared_before_click"))
    out["dom_click_capture"] = dom
    out["browser_dom_click_events"] = list(dom.get("browser_dom_click_events") or [])
    out["trusted_dom_click"] = bool(dom.get("trusted_dom_click"))
    page.wait_for_timeout(max(0, settle_ms - 800))
    out["post"] = snapshot_fragment_exec_context(page)
    out["lifecycle_after"] = snapshot_fragment_lifecycle(page, stage="after_probe_click")
    ledger = scrape_fragment_callback_ledger(page)
    after_payload = ledger.get("payload") if isinstance(ledger.get("payload"), dict) else {}
    delta = _ledger_delta(before_payload, after_payload, source="fragment_widget_probe")
    out["callback_ledger_delta"] = delta
    out["callback_ledger_last"] = delta.get("callback_ledger_last") or {}
    out["callback_entered"] = bool(delta.get("callback_entered"))
    out["probe_click_count"] = after_payload.get("probe_click_count")
    out["ledger_dom_observable"] = callback_ledger_dom_observable(ledger)
    out["finished_ts"] = time.time()
    return out


def ledger_last_for_source(ledger_payload: dict[str, Any], source: str) -> dict[str, Any]:
    rows = list(ledger_payload.get("rows") or [])
    for row in reversed(rows):
        if isinstance(row, dict) and str(row.get("source") or "") == source:
            return dict(row)
    last = ledger_payload.get("last") if isinstance(ledger_payload.get("last"), dict) else {}
    if str(last.get("source") or "") == source:
        return dict(last)
    return {}


def click_francisco_add_to_queue(
    page,
    *,
    scrape_container_fn,
    preferred_name: str = "Francisco Lindor",
    settle_ms: int = 4500,
) -> dict[str, Any]:
    from stage1_add_to_queue_delivery import (
        BINDING_UNIQUE,
        deliver_add_to_queue_click,
        discover_bound_add_to_queue_controls,
        select_next_seed_candidate,
    )
    from stage1_rec_fragment_exec_scrape import scrape_fragment_callback_ledger
    from stage1_rec_queue_click_trace_scrape import merge_render_trace_into_step, scrape_rec_queue_render_trace
    from stage1_run_binding import BINDING_MODE_RECOMMENDATION_WIDGET, capture_run_binding_snapshot
    from stage1_queue_seed_harness import _poll_queue_mutation, _snapshot_queue

    out: dict[str, Any] = {"control": "C_francisco_add_to_queue", "started_ts": time.time()}
    out["lifecycle_before"] = snapshot_fragment_lifecycle(page, stage="before_francisco_click")
    out["pre"] = snapshot_fragment_exec_context(page)
    before_payload = dict(out["pre"].get("ledger_payload") or {})
    candidates = discover_bound_add_to_queue_controls(page)
    pick, reject = select_next_seed_candidate(
        candidates,
        exclude_player_names=set(),
        preferred_player_name=preferred_name,
    )
    out["candidate_reject"] = reject
    out["pre_click_record"] = pick
    if not pick or str(pick.get("binding_confidence") or "") != BINDING_UNIQUE:
        out["click_dispatched"] = False
        out["classification"] = "ABORTED_FRANCISCO_BINDING"
        return out
    player_name = str(pick.get("player_name") or preferred_name).strip()
    pre_q = _snapshot_queue(page, scrape_container_fn)
    step: dict[str, Any] = {
        "player_name": player_name,
        "queue_before": list(pre_q.get("queue_names") or []),
    }
    merge_render_trace_into_step(step, scrape_rec_queue_render_trace(page, player_name=player_name))
    out["render_trace"] = step.get("app_render_trace") or step
    binding = capture_run_binding_snapshot(
        page,
        frame_url_hint=str(pick.get("frameUrl") or ""),
        lifecycle_render_trace=step.get("app_render_trace") if isinstance(step.get("app_render_trace"), dict) else None,
        phase="pre_click",
        binding_mode=BINDING_MODE_RECOMMENDATION_WIDGET,
    )
    out["pre_click_run_binding"] = binding
    if binding.get("run_binding_consistent") is False:
        out["classification"] = "QUEUE1C3A2O1"
        out["click_dispatched"] = False
        return out
    liveness = str((step.get("app_render_trace") or {}).get("widget_liveness") or step.get("render_trace_widget_liveness") or "")
    out["widget_liveness"] = liveness
    if liveness != "live_this_run":
        out["classification"] = "ABORTED_FRANCISCO_NOT_LIVE_THIS_RUN"
        out["click_dispatched"] = False
        return out
    delivery = deliver_add_to_queue_click(page, pick, playwright_only=True)
    out["delivery_detail"] = delivery
    out["dom_click_capture"] = delivery.get("dom_click_capture") or {}
    out["click_dispatched"] = bool(delivery.get("click_dispatched"))
    out["browser_dom_click_events"] = list(delivery.get("browser_dom_click_events") or [])
    out["trusted_dom_click"] = bool(delivery.get("trusted_dom_click") or out["dom_click_capture"].get("trusted_dom_click"))
    page.wait_for_timeout(settle_ms)
    mut = _poll_queue_mutation(
        page,
        scrape_container_fn,
        queue_before=step["queue_before"],
        player_name=player_name,
        timeout_s=5.0,
    )
    out["queue_after"] = list(mut.get("queue_after") or [])
    out["mutation_proven"] = bool(mut.get("mutation_observed"))
    out["queue_mutation_visible"] = bool(mut.get("visible_confirmation"))
    try:
        from stage1_rec_queue_click_trace_scrape import merge_app_trace_into_step, scrape_rec_queue_app_trace

        merge_app_trace_into_step(out, scrape_rec_queue_app_trace(page))
    except ImportError:
        pass
    out["post"] = snapshot_fragment_exec_context(page)
    out["lifecycle_after"] = snapshot_fragment_lifecycle(page, stage="after_francisco_click")
    ledger = scrape_fragment_callback_ledger(page)
    after_payload = ledger.get("payload") if isinstance(ledger.get("payload"), dict) else {}
    delta = _ledger_delta(before_payload, after_payload, source="rec_card_add_to_queue")
    out["callback_ledger_delta"] = delta
    out["callback_ledger_last"] = delta.get("callback_ledger_last") or {}
    out["callback_entered"] = bool(delta.get("callback_entered"))
    out["ledger_dom_observable"] = callback_ledger_dom_observable(ledger)
    out["finished_ts"] = time.time()
    return out


def classify_fragment_gate(
    *,
    pause_ok: bool,
    pause_dom: dict[str, Any] | None,
    probe_step: dict[str, Any],
    francisco_step: dict[str, Any],
    probe_render_ok: bool,
) -> str:
    from stage1_rec_fragment_exec_scrape import classify_fragment_exec_comparison

    if not probe_render_ok:
        return "ABORTED_FRAGMENT_PROBE_NOT_RENDERED"
    if not pause_ok:
        return "ABORTED_PAUSE_NOT_RESOLVED"
    if not probe_step.get("ledger_dom_observable") or not francisco_step.get("ledger_dom_observable"):
        return OBSERVABILITY_FRAGMENT_LEDGER_NOT_VISIBLE

    pause_trusted = bool((pause_dom or {}).get("trusted_dom_click"))
    probe_ledger = probe_step.get("callback_ledger_last") if isinstance(probe_step.get("callback_ledger_last"), dict) else {}
    fr_ledger = francisco_step.get("callback_ledger_last") if isinstance(francisco_step.get("callback_ledger_last"), dict) else {}
    base = classify_fragment_exec_comparison(
        pause_functional=pause_ok and pause_trusted,
        probe_ledger_last=probe_ledger,
        francisco_ledger_last=fr_ledger,
        probe_dom_click=bool(probe_step.get("trusted_dom_click")),
        francisco_dom_click=bool(francisco_step.get("trusted_dom_click")),
    )
    fr_entered = bool(francisco_step.get("callback_entered"))
    fr_mut = bool(francisco_step.get("mutation_proven"))
    queue_after = bool(francisco_step.get("queue_mutation_visible"))
    if base == "QUEUE1C3A2F2_CANDIDATE" or (fr_entered and not fr_mut):
        if fr_entered and fr_mut and not queue_after:
            return "QUEUE1C3A2F3"
        if fr_entered:
            return "QUEUE1C3A2F2"
    if base == "QUEUE1C3A2F4":
        return "QUEUE1C3A2F4"
    if base == "QUEUE1C3A2F1":
        return "QUEUE1C3A2F1"
    if fr_entered and fr_mut and not queue_after:
        return "QUEUE1C3A2F3"
    if fr_entered and not fr_mut:
        return "QUEUE1C3A2D_FRAGMENT_CALLBACK_NO_MUTATION"
    return "QUEUE1C3A2D_FRAGMENT_UNCLASSIFIED"
