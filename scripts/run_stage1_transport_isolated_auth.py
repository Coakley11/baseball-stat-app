"""Authenticated Cloud Stage 1 transport isolation — minimal-only vs production-only (separate rooms)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
REQUIRED_CLOUD_SHA = ""  # filled from deploy_commit.txt at runtime
OUT_SUMMARY = ROOT / "data" / "stage1_transport_isolated_summary.json"
OUT_A = ROOT / "data" / "stage1_transport_isolated_test_a.json"
OUT_B = ROOT / "data" / "stage1_transport_isolated_test_b.json"


def _required_cloud_sha() -> str:
    line = (ROOT / "deploy_commit.txt").read_text(encoding="utf-8").splitlines()[0]
    return line.split("#", 1)[0].strip().lower()[:7]


from playwright_daniel_auth_session import (  # noqa: E402
    STORAGE_PATH,
    append_suite_sid_to_url,
    harness_ready,
)
from replay_playwright_daniel_auth_preflight import run_preflight  # noqa: E402
from run_production_stage1_authenticated import (  # noqa: E402
    ensure_fresh_setup_lobby,
    redact_url,
    validate_production_draft_start,
)
from run_production_solo_soak import (  # noqa: E402
    scrape_iframe_lifecycle,
    scrape_stage1_audit,
    scrape_transport_boundary,
)
from run_solo_diag_10s_controlled import scrape_snapshot, stages_from_chain  # noqa: E402
from stage1_frame_transport_probe import (  # noqa: E402
    MINIMAL_WIDGET_KEY,
    PRODUCTION_WIDGET_KEY,
    collect_frame_topology,
    install_immediate_parent_listeners,
    scrape_immediate_parent_messages,
)


def isolated_test_url(mode: str) -> str:
    """Isolated component + transport probe without paired minimal control."""
    params: dict[str, str] = {
        "active_page": "Live Draft Room",
        "solo_diag_timer": "10",
        "solo_transport_probe": "1",
    }
    if mode == "minimal":
        params["solo_transport_isolated"] = "minimal"
    elif mode == "production":
        params["solo_transport_isolated"] = "production"
    else:
        raise ValueError(mode)
    q = urlencode(params)
    return append_suite_sid_to_url(f"{BASE}/?{q}")


def _probe_script_run(page) -> int | None:
    try:
        raw = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const el = root.querySelector('#solo-transport-boundary-diag');
                if (el) {
                  const n = parseInt(el.getAttribute('data-script-run') || '', 10);
                  return Number.isFinite(n) ? n : null;
                }
              }
              return null;
            }"""
        )
        return int(raw) if raw is not None else None
    except Exception:
        return None


def _transport_log_tail(page) -> list[dict[str, Any]]:
    transport = scrape_transport_boundary(page)
    probe = transport.get("probe") or {}
    if isinstance(probe, dict):
        tail = probe.get("log_tail") or []
        if isinstance(tail, list):
            return [x for x in tail if isinstance(x, dict)]
    return []


def _streamlit_session_from_probe(page) -> str:
    for row in _transport_log_tail(page):
        sid = str(row.get("streamlit_session_id") or "").strip()
        if sid:
            return sid
    for row in _transport_log_tail(page):
        if row.get("stage") == "python_post_send_snapshot":
            return str(row.get("streamlit_session_id") or "")
    return ""


def wait_single_component_expire(page, *, mode: str, timeout_s: float = 55.0) -> dict[str, Any]:
    t0 = time.time()
    samples: list[dict[str, Any]] = []
    script_run_before_arm: int | None = None
    script_run_before_send: int | None = None
    script_run_after_send: int | None = None
    timer_armed_at: float | None = None
    send_ts_ms: int | None = None
    observe_until = t0 + timeout_s

    install_immediate_parent_listeners(page)

    while time.time() < observe_until:
        install_immediate_parent_listeners(page)
        snap: dict[str, Any] = {"elapsed_s": round(time.time() - t0, 1)}
        snap["script_run"] = _probe_script_run(page)
        snap["frame_topology"] = collect_frame_topology(page)
        iframe_life = scrape_iframe_lifecycle(page)
        snap["iframe_merged_stages"] = iframe_life.get("merged_stages") or []
        transport = scrape_transport_boundary(page)
        snap["transport_probe_stages"] = list((transport.get("probe") or {}).get("stages") or [])
        audit = scrape_stage1_audit(page)
        snap["audit_callback_count"] = len(audit.get("callbacks") or [])
        samples.append(snap)

        stages = set(snap.get("iframe_merged_stages") or [])
        if "timer_armed" in stages and timer_armed_at is None:
            timer_armed_at = time.time()
            script_run_before_arm = snap.get("script_run")
            observe_until = max(observe_until, timer_armed_at + 22.0)

        if "transport_before_postMessage" in stages or "component_value_sent" in stages:
            if script_run_before_send is None:
                script_run_before_send = snap.get("script_run")
            for fr in iframe_life.get("frames") or []:
                for block in fr.get("logs") or []:
                    for e in block.get("entries") or []:
                        if str(e.get("stage") or "") in (
                            "transport_postmessage_invoked",
                            "component_value_sent",
                        ):
                            try:
                                send_ts_ms = int(e.get("ts") or 0)
                            except (TypeError, ValueError):
                                pass

        if {"component_value_sent", "transport_postmessage_invoked"} & stages:
            page.wait_for_timeout(8000)
            script_run_after_send = _probe_script_run(page)
            break

        if timer_armed_at and time.time() >= timer_armed_at + 22:
            break
        page.wait_for_timeout(2000)

    if script_run_after_send is None:
        script_run_after_send = _probe_script_run(page)

    iframe_final = scrape_iframe_lifecycle(page)
    transport_final = scrape_transport_boundary(page) or {}
    audit_final = scrape_stage1_audit(page) or {}
    immediate = scrape_immediate_parent_messages(page)
    topo = collect_frame_topology(page)
    for snap in reversed(samples):
        ft = snap.get("frame_topology") or {}
        if (ft.get("frame_count") or 0) >= 5:
            topo = ft
            break

    log_tail = list((transport_final.get("probe") or {}).get("log_tail") or [])
    post_send_rows = [
        r
        for r in log_tail
        if isinstance(r, dict)
        and r.get("stage") in ("python_run_entry", "python_post_send_snapshot", "minimal_control_on_change")
    ]

    prod_frames = sum(1 for f in topo.get("frames") or [] if f.get("has_production_countdown"))
    min_frames = sum(1 for f in topo.get("frames") or [] if f.get("has_minimal_control"))

    expected_key = MINIMAL_WIDGET_KEY if mode == "minimal" else PRODUCTION_WIDGET_KEY
    expected_msgs = [
        m
        for m in immediate
        if isinstance(m, dict)
        and m.get("has_set_component_value")
        and (
            (mode == "minimal" and "|minimal|" in str(m.get("value_preview") or ""))
            or (mode == "production" and "|minimal|" not in str(m.get("value_preview") or "") and m.get("value_preview"))
        )
    ]

    callbacks = list(audit_final.get("callbacks") or [])
    accepted = [c for c in callbacks if c.get("delivery_claimed") and not c.get("reject_code")]
    minimal_on_change = any(r.get("stage") == "minimal_control_on_change" for r in log_tail if isinstance(r, dict))
    prod_on_change = any(
        r.get("phase") == "production_on_change" for r in log_tail if isinstance(r, dict) and r.get("stage") == "python_run_entry"
    )

    python_reached = bool(minimal_on_change if mode == "minimal" else (accepted or prod_on_change))

    iframe_entries: list[dict[str, Any]] = []
    for fr in iframe_final.get("frames") or []:
        if not isinstance(fr, dict):
            continue
        for block in fr.get("logs") or []:
            if isinstance(block, dict):
                iframe_entries.extend(block.get("entries") or [])

    classification = classify_isolated_result(
        mode=mode,
        iframe_sent="component_value_sent" in set(iframe_final.get("merged_stages") or []),
        immediate_parent_has=bool(expected_msgs),
        python_reached=python_reached,
        post_send_rows=post_send_rows,
        callback_count=len(accepted),
        minimal_on_change=minimal_on_change,
        confounded=(prod_frames > 0 and min_frames > 0),
        transport_log=log_tail,
        immediate_messages=immediate,
        iframe_entries=iframe_entries,
    )

    token_preview = ""
    if expected_msgs:
        token_preview = str(expected_msgs[0].get("value_preview") or "")

    pick_commits = list(audit_final.get("pick_commits") or [])
    post_send_snapshot = next(
        (r for r in reversed(log_tail) if isinstance(r, dict) and r.get("stage") == "python_post_send_snapshot"),
        {},
    )
    component_iframes: list[dict[str, Any]] = []
    for f in topo.get("frames") or []:
        if f.get("has_production_countdown"):
            component_iframes.append({"role": "production", "url": f.get("sanitized_url")})
        if f.get("has_minimal_control"):
            component_iframes.append({"role": "minimal", "url": f.get("sanitized_url")})

    return {
        "mode": mode,
        "observation_duration_s": round(time.time() - t0, 1),
        "cloud_sha_required": _required_cloud_sha(),
        "streamlit_session_id": _streamlit_session_from_probe(page),
        "script_run_before_timer_arm": script_run_before_arm,
        "script_run_immediately_before_send": script_run_before_send,
        "script_run_after_send": script_run_after_send,
        "new_python_run_after_send": (
            script_run_after_send is not None
            and script_run_before_send is not None
            and script_run_after_send > script_run_before_send
        ),
        "expected_component_key": expected_key,
        "expected_token_preview": token_preview,
        "immediate_parent_set_component_value": expected_msgs,
        "immediate_parent_all_messages": immediate[-20:],
        "frame_topology": topo,
        "production_iframe_frames_seen": prod_frames,
        "minimal_iframe_frames_seen": min_frames,
        "isolation_confounded": prod_frames > 0 and min_frames > 0,
        "iframe_lifecycle": iframe_final,
        "transport_boundary": transport_final,
        "transport_log_tail": log_tail[-30:],
        "post_send_python_rows": post_send_rows,
        "stage1_audit": audit_final,
        "callback_accepted_count": len(accepted),
        "classification": classification,
        "first_missing_stage": classification.get("first_missing_stage") or "",
        "artifact_path": str(OUT_A if mode == "minimal" else OUT_B),
        "component_iframe_identities": component_iframes,
        "component_iframe_count": len(component_iframes),
        "earliest_post_send_session_state": {
            "production_key": post_send_snapshot.get("production_key") or post_send_snapshot.get("widget_key"),
            "production_raw": post_send_snapshot.get("production_raw_value") or post_send_snapshot.get("raw_value"),
            "minimal_key": post_send_snapshot.get("minimal_key"),
            "minimal_raw": post_send_snapshot.get("minimal_raw_value"),
        },
        "component_return_value": post_send_snapshot.get("production_component_return")
        or post_send_snapshot.get("minimal_component_return"),
        "on_change_callback_count": int(post_send_snapshot.get("minimal_callback_count") or 0)
        + int(post_send_snapshot.get("production_callback_count") or 0),
        "pick_commits": pick_commits if mode == "production" else [],
        "audit_callbacks_accepted": accepted,
        "audit_callbacks_rejected": [c for c in callbacks if c.get("reject_code")],
        "samples_tail": samples[-6:],
        "client_send_ts_ms": send_ts_ms,
    }


def classify_isolated_result(
    *,
    mode: str,
    iframe_sent: bool,
    immediate_parent_has: bool,
    python_reached: bool,
    post_send_rows: list[dict[str, Any]],
    callback_count: int,
    minimal_on_change: bool,
    confounded: bool,
    transport_log: list[dict[str, Any]],
    immediate_messages: list[dict[str, Any]],
    iframe_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    if confounded:
        return {
            "label": "paired_interference_likely",
            "first_missing_stage": "",
            "note": "Both component iframes present; not an isolated run.",
        }
    try:
        from live_draft_solo_transport_boundary_diag import classify_transport_stage

        stage = classify_transport_stage(
            iframe_entries=iframe_entries,
            parent_entries=[],
            transport_log=transport_log,
            callback_count=callback_count if mode == "production" else (1 if minimal_on_change else 0),
            iframe_has_component_sent=iframe_sent,
            immediate_parent_messages=immediate_messages,
        )
        if stage:
            return {"label": stage, "first_missing_stage": stage, "note": f"Transport stage {stage}."}
    except ImportError:
        pass
    if not iframe_sent:
        return {"label": "A", "first_missing_stage": "A", "note": "No child postMessage path completed."}
    if not immediate_parent_has:
        return {"label": "B", "first_missing_stage": "B", "note": "Immediate parent did not receive setComponentValue."}

    has_post_send = bool(post_send_rows)
    key_present = any(
        r.get("production_key_exists")
        or r.get("minimal_key_in_session_state")
        or r.get("key_in_session_state")
        for r in post_send_rows
    )
    if not has_post_send and not python_reached:
        return {"label": "C", "first_missing_stage": "C", "note": "Parent received message; no Python post-send observation."}
    if has_post_send and not key_present:
        return {"label": "D", "first_missing_stage": "D", "note": "Python reran but widget key/value absent."}
    if key_present and not (callback_count or minimal_on_change):
        return {"label": "E", "first_missing_stage": "E", "note": "Value present; on_change did not run."}
    if (callback_count or minimal_on_change) and mode == "production" and callback_count == 0:
        return {"label": "F", "first_missing_stage": "F", "note": "on_change ran but audit empty."}
    if python_reached:
        return {"label": "pass_isolated_delivery", "first_missing_stage": "", "note": "Isolated component reached Python."}
    return {"label": "unknown", "first_missing_stage": "", "note": "Unclassified."}


def run_one_test(page, *, mode: str, preflight: dict[str, Any]) -> dict[str, Any]:
    from cloud_streamlit_wake import goto_and_wake
    from run_production_solo_soak import scrape_deploy_build
    from solo_draft_start_harness import execute_solo_draft_start_workflow

    url = isolated_test_url(mode)
    goto_and_wake(page, url, timeout_s=240)
    page.wait_for_timeout(12000)
    try:
        page.get_by_text("Real Accounts", exact=False).first.click(timeout=4000)
        page.wait_for_timeout(2500)
    except Exception:
        pass
    page.wait_for_timeout(10000)

    sha = scrape_deploy_build(page) or str(preflight.get("cloud_sha") or "")
    sha_short = str(sha).lower()[:7]
    req = _required_cloud_sha()
    if sha_short != req:
        return {
            "aborted": True,
            "reason": "cloud_sha_mismatch",
            "cloud_sha": sha_short,
            "required": req,
            "mode": mode,
        }

    cleanup = ensure_fresh_setup_lobby(page, max_wait_s=240)
    if not cleanup.get("ok"):
        return {"aborted": True, "reason": "cleanup_failed", "cleanup": cleanup, "mode": mode}

    prior = str(cleanup.get("detected_room_id") or "").strip().upper()
    draft = execute_solo_draft_start_workflow(page, url, navigate=False)
    start_val = validate_production_draft_start(page, draft, prior_room_id=prior)
    if not start_val.get("valid"):
        return {"aborted": True, "reason": "draft_start_invalid", "validation": start_val, "mode": mode}

    result = wait_single_component_expire(page, mode=mode)
    result["setup_url_redacted"] = redact_url(url)
    result["room_id"] = start_val.get("latched_room_id")
    result["cloud_sha"] = sha_short
    result["cleanup"] = cleanup
    return result


def main() -> int:
    if not harness_ready():
        print(json.dumps({"aborted": True, "reason": "auth_harness_incomplete"}))
        return 1
    pre = run_preflight()
    if not pre.get("authenticated_restored"):
        print(json.dumps({"aborted": True, "reason": "auth_preflight_failed"}))
        return 1

    from playwright.sync_api import sync_playwright

    req = _required_cloud_sha()
    summary: dict[str, Any] = {
        "started_at": time.time(),
        "required_cloud_sha": req,
        "build_label": f"baseball-dev-{req}",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            storage_state=str(STORAGE_PATH),
            viewport={"width": 1440, "height": 1400},
        )
        page = context.new_page()

        test_b = run_one_test(page, mode="production", preflight=pre)
        summary["test_b_production_only"] = test_b
        OUT_B.write_text(json.dumps(test_b, indent=2, default=str), encoding="utf-8")

        page.wait_for_timeout(8000)
        test_a = run_one_test(page, mode="minimal", preflight=pre)
        summary["test_a_minimal_only"] = test_a
        OUT_A.parent.mkdir(parents=True, exist_ok=True)
        OUT_A.write_text(json.dumps(test_a, indent=2, default=str), encoding="utf-8")

        context.close()
        browser.close()

    stages = []
    for key in ("test_a_minimal_only", "test_b_production_only"):
        block = summary.get(key) or {}
        if block.get("aborted"):
            continue
        fs = str(block.get("first_missing_stage") or "")
        if fs:
            stages.append(f"{key}:{fs}")
    summary["first_proven_missing_stage"] = stages[0] if stages else ""
    summary["finished_at"] = time.time()
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
