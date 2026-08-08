"""Helpers for Pause → fragment probe → Francisco production fragment diagnostic gate."""

from __future__ import annotations

import time
from typing import Any


def snapshot_fragment_exec_context(page) -> dict[str, Any]:
    from stage1_rec_fragment_exec_scrape import scrape_fragment_callback_ledger, scrape_fragment_exec_probes
    from stage1_run_binding import capture_run_binding_snapshot, BINDING_MODE_RECOMMENDATION_WIDGET
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


def _install_dom_on_app_frame(page) -> dict[str, Any]:
    try:
        from stage1_dom_click_capture import install_dom_click_capture_on_frame

        fr = _app_frame(page)
        return install_dom_click_capture_on_frame(fr, frame_url_hint=str(fr.url or ""), mode="rec_card")
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def _read_dom_events(page) -> list[dict[str, Any]]:
    try:
        from stage1_dom_click_capture import read_dom_click_capture_from_frame, read_dom_click_capture_log

        fr = _app_frame(page)
        events = read_dom_click_capture_from_frame(fr)
        return events if events else read_dom_click_capture_log(page)
    except Exception:
        return []


def _trusted_click(events: list[dict[str, Any]]) -> bool:
    return any(isinstance(e, dict) and e.get("type") == "click" and e.get("isTrusted") for e in events)


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


def click_fragment_widget_probe(page, *, settle_ms: int = 3500) -> dict[str, Any]:
    from stage1_rec_fragment_exec_scrape import scrape_fragment_callback_ledger

    out: dict[str, Any] = {"control": "B_fragment_widget_probe", "started_ts": time.time()}
    out["pre"] = snapshot_fragment_exec_context(page)
    out["dom_click_capture_install"] = _install_dom_on_app_frame(page)
    label = "Stage1 Recommendation Widget Probe"
    clicked = False
    err = ""
    try:
        fr = _app_frame(page)
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
    page.wait_for_timeout(settle_ms)
    out["browser_dom_click_events"] = _read_dom_events(page)
    out["trusted_dom_click"] = _trusted_click(out["browser_dom_click_events"])
    out["post"] = snapshot_fragment_exec_context(page)
    ledger = scrape_fragment_callback_ledger(page)
    payload = ledger.get("payload") if isinstance(ledger.get("payload"), dict) else {}
    last = payload.get("last") if isinstance(payload.get("last"), dict) else {}
    out["callback_ledger_last"] = last
    out["probe_click_count"] = payload.get("probe_click_count")
    out["callback_entered"] = bool(last.get("callback_entered")) and str(last.get("source") or "") == "fragment_widget_probe"
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
    from stage1_run_binding import capture_run_binding_snapshot, BINDING_MODE_RECOMMENDATION_WIDGET
    from stage1_queue_seed_harness import _poll_queue_mutation, _snapshot_queue

    out: dict[str, Any] = {"control": "C_francisco_add_to_queue", "started_ts": time.time()}
    out["pre"] = snapshot_fragment_exec_context(page)
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
    out["dom_click_capture_install"] = _install_dom_on_app_frame(page)
    delivery = deliver_add_to_queue_click(page, pick, playwright_only=True)
    out["delivery_detail"] = delivery
    out["click_dispatched"] = bool(delivery.get("click_dispatched"))
    out["browser_dom_click_events"] = list(delivery.get("browser_dom_click_events") or [])
    out["trusted_dom_click"] = _trusted_click(out["browser_dom_click_events"])
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
    out["app_callback_entered"] = out.get("app_callback_entered")
    out["post"] = snapshot_fragment_exec_context(page)
    ledger = scrape_fragment_callback_ledger(page)
    payload = ledger.get("payload") if isinstance(ledger.get("payload"), dict) else {}
    fr_last = ledger_last_for_source(payload, "rec_card_add_to_queue")
    out["callback_ledger_last"] = fr_last
    out["callback_entered"] = bool(fr_last.get("callback_entered"))
    out["finished_ts"] = time.time()
    return out


def classify_fragment_gate(
    *,
    pause_ok: bool,
    probe_step: dict[str, Any],
    francisco_step: dict[str, Any],
    probe_render_ok: bool,
) -> str:
    from stage1_rec_fragment_exec_scrape import classify_fragment_exec_comparison

    if not probe_render_ok:
        return "ABORTED_FRAGMENT_PROBE_NOT_RENDERED"
    if not pause_ok:
        return "ABORTED_PAUSE_NOT_RESOLVED"

    probe_ledger = probe_step.get("callback_ledger_last") if isinstance(probe_step.get("callback_ledger_last"), dict) else {}
    fr_ledger = francisco_step.get("callback_ledger_last") if isinstance(francisco_step.get("callback_ledger_last"), dict) else {}
    base = classify_fragment_exec_comparison(
        pause_functional=True,
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
    if base:
        return base
    if fr_entered and fr_mut and not queue_after:
        return "QUEUE1C3A2F3"
    if fr_entered and not fr_mut:
        return "QUEUE1C3A2D_FRAGMENT_CALLBACK_NO_MUTATION"
    return "QUEUE1C3A2D_FRAGMENT_UNCLASSIFIED"
