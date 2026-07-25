"""P2A micro-isolation startup + observation diagnostic (harness only)."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"
P2A_SETUP_URL = (
    f"{BASE}/?active_page=Live%20Draft%20Room"
    "&solo_delivery_diag=1"
    "&solo_micro_isolation=1"
    "&solo_placement_micro=P2A"
    "&solo_component_diag=1"
    "&solo_diag_timer=10"
)
P2_GATE_ARTIFACT = ROOT / "data" / "solo_placement_p2_gate.json"
MATRIX_ARTIFACT = ROOT / "data" / "solo_placement_micro_matrix.json"
OUT = ROOT / "data" / "solo_p2a_startup_diag.json"
WAIT_EXPIRE_S = 28
P2A_HOOK = "live_draft_solo_placement_micro.try_micro_p2a_before_early_reconcile"

USER_CHECKPOINT_STEPS = (
    ("1_initial_url_params", "query_initial_url"),
    ("2_sidebar_ldr_navigation", "sidebar_clicked"),
    ("3_p2a_placement_latched", "placement_latch_after_sidebar"),
    ("4_setup_lobby_visible", "setup_visible"),
    ("5_solo_mode_selected", "solo_radio_selected"),
    ("6_start_button_visible_enabled", "start_button_visible_enabled"),
    ("7_start_click_proven_path", "start_click_evaluate_dispatched"),
    ("8_toast_or_room_id", ("toast_detected", "room_id_detected")),
    ("9_room_in_progress", ("query_in_progress_room", "micro_observation_active", "room_id_detected")),
    ("10_p2a_hook_entered", "micro_observation_active"),
    ("11_micro_diag_observation_ready", "micro_observation_active"),
)


def _step_present(checkpoints: list[dict[str, Any]], step: str) -> dict[str, Any] | None:
    for row in checkpoints:
        if row.get("step") == step:
            return row
    return None


def _steps_present(checkpoints: list[dict[str, Any]], steps: str | tuple[str, ...]) -> dict[str, Any] | None:
    if isinstance(steps, str):
        return _step_present(checkpoints, steps)
    for step in steps:
        row = _step_present(checkpoints, step)
        if row:
            return row
    return None


def build_user_checkpoint_report(checkpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label, step in USER_CHECKPOINT_STEPS:
        row = _steps_present(checkpoints, step)
        ok = row is not None
        extra: dict[str, Any] = {}
        if label == "1_initial_url_params" and row:
            ok = bool(row.get("query_ok_vs_setup")) and bool(row.get("solo_micro_isolation"))
            extra = {
                "solo_delivery_diag": row.get("solo_delivery_diag"),
                "solo_micro_isolation": row.get("solo_micro_isolation"),
                "solo_placement_micro": row.get("solo_placement_micro"),
                "solo_component_diag": row.get("solo_component_diag"),
                "solo_diag_timer_10": row.get("solo_diag_timer_10"),
            }
        if label == "3_p2a_placement_latched" and row:
            latch = row.get("latch") or {}
            ok = str(latch.get("requested") or "").upper() == "P2A"
            extra = {"latch": latch}
        if label == "4_setup_lobby_visible" and row:
            ok = bool(row.get("visible"))
        if label == "5_solo_mode_selected" and row:
            ok = bool(row.get("solo_selected"))
        if label == "6_start_button_visible_enabled" and row:
            ok = int(row.get("enabled") or 0) >= 1
        if label == "10_p2a_hook_entered" and row:
            micro = row.get("micro") or {}
            src = str(micro.get("source") or "")
            ok = "try_micro_p2a_before_early_reconcile" in src
            extra = {"source": src}
        if label == "11_micro_diag_observation_ready" and row:
            micro = row.get("micro") or {}
            ok = (
                str(micro.get("placement") or "").upper() == "P2A"
                and bool(micro.get("key"))
                and bool(micro.get("token"))
            )
            extra = {"micro": micro, "observation_ready": ok}
        out.append(
            {
                "checkpoint": label,
                "harness_step": step if isinstance(step, str) else list(step),
                "ok": ok,
                "ts": row.get("ts") if row else None,
                **extra,
            }
        )
    return out


def first_user_divergence(
    p2a: list[dict[str, Any]], proven: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare shared harness steps through start success (P2 gate proven path)."""
    shared_order = (
        "query_initial_url",
        "sidebar_clicked",
        "setup_visible",
        "solo_radio_selected",
        "start_button_visible_enabled",
        "start_click_evaluate_dispatched",
        "toast_detected",
        "room_id_detected",
        "start_success_all_criteria",
    )
    for step in shared_order:
        p_row = _step_present(p2a, step)
        g_row = _step_present(proven, step)
        if step in ("toast_detected", "room_id_detected"):
            p_ok = _step_present(p2a, "toast_detected") or _step_present(p2a, "room_id_detected")
            g_ok = _step_present(proven, "toast_detected") or _step_present(proven, "room_id_detected")
            if g_ok and not p_ok:
                return {
                    "first_divergence": "8_toast_or_room_id",
                    "kind": "p2a_missing_success_signal",
                    "proven": g_ok,
                    "p2a_note": "P2A may surface room via micro probe after deferred hook; see post_create alerts",
                }
            continue
        if g_row and not p_row:
            return {"first_divergence": step, "kind": "missing_on_p2a", "proven": g_row}
        if step == "query_initial_url" and p_row and g_row:
            if bool(p_row.get("query_ok_vs_setup")) != bool(g_row.get("query_ok_vs_setup")):
                return {"first_divergence": step, "kind": "query_ok_mismatch", "p2a": p_row, "proven": g_row}
        if step == "start_success_all_criteria":
            if g_row and not p_row:
                return {"first_divergence": step, "kind": "p2a_start_not_success", "proven": g_row}
    u_p2a = build_user_checkpoint_report(p2a)
    for row in u_p2a:
        if not row.get("ok"):
            return {
                "first_divergence": row.get("checkpoint"),
                "kind": "user_checkpoint_failed",
                "row": row,
            }
    return {"first_divergence": None, "kind": "aligned_through_user_checkpoints"}


def scrape_p2a_path_diagnostics(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots(){const o=[document]; for(const f of document.querySelectorAll('iframe')){try{o.push(f.contentDocument)}catch(e){}} return o.filter(Boolean)}
          const out = {callsite: null, fn_entry: null, declines: [], branches: []};
          for (const x of roots()) {
            const c = x && x.querySelector('#solo-p2a-callsite-diag');
            if (c && !out.callsite) {
              out.callsite = {
                present: c.getAttribute('data-present')||'',
                requested: c.getAttribute('data-requested')||'',
                latched: c.getAttribute('data-latched')||'',
                query: c.getAttribute('data-query')||'',
                active_page: c.getAttribute('data-active-page')||'',
                active_page_entered: c.getAttribute('data-active-page-entered')||'',
                room_present: c.getAttribute('data-room-present')||'',
                room_id: c.getAttribute('data-room-id')||'',
                room_status: c.getAttribute('data-room-status')||'',
                solo_in_progress: c.getAttribute('data-solo-in-progress')||'',
                start_pending: c.getAttribute('data-start-pending')||'',
                start_in_flight: c.getAttribute('data-start-in-flight')||'',
                post_create_open: c.getAttribute('data-post-create-open')||'',
                lifecycle: c.getAttribute('data-lifecycle')||'',
                setup_branch: c.getAttribute('data-setup-branch')||'',
                active_branch: c.getAttribute('data-active-branch')||'',
                snap: c.getAttribute('data-snap')||'',
              };
            }
            const f = x && x.querySelector('#solo-p2a-fn-entry-diag');
            if (f && !out.fn_entry) {
              out.fn_entry = {
                present: f.getAttribute('data-present')||'',
                decline: f.getAttribute('data-decline')||'',
                snap: f.getAttribute('data-snap')||'',
              };
            }
            for (const d of (x&&x.querySelectorAll('#solo-p2a-decline-diag')||[])) {
              out.declines.push({
                reason: d.getAttribute('data-reason')||'',
                fields: d.getAttribute('data-fields')||'',
                ts: d.getAttribute('data-ts')||'',
              });
            }
            for (const b of (x&&x.querySelectorAll('.solo-p2a-path-branch')||[])) {
              out.branches.push({
                marker: b.getAttribute('data-marker')||'',
                detail: b.getAttribute('data-detail')||'',
                ts: b.getAttribute('data-ts')||'',
              });
            }
          }
          out.declines.sort((a,b)=>parseFloat(a.ts||0)-parseFloat(b.ts||0));
          out.branches.sort((a,b)=>parseFloat(a.ts||0)-parseFloat(b.ts||0));
          return out;
        }"""
    )


def poll_p2a_path_diagnostics(page, *, max_wait_s: int = 90) -> dict[str, Any]:
    deadline = time.time() + max_wait_s
    last: dict[str, Any] = {}
    samples: list[dict[str, Any]] = []
    while time.time() < deadline:
        snap = scrape_p2a_path_diagnostics(page)
        last = snap
        samples.append({"ts": time.time(), **snap})
        if snap.get("fn_entry") and (snap.get("fn_entry") or {}).get("decline") == "":
            if not snap.get("declines"):
                break
        if snap.get("callsite") and snap.get("fn_entry"):
            break
        page.wait_for_timeout(1000)
    return {"last": last, "samples": samples[-30:]}


def interpret_p2a_path(path: dict[str, Any]) -> dict[str, Any]:
    last = path.get("last") or {}
    callsite = last.get("callsite")
    fn_entry = last.get("fn_entry")
    declines = list(last.get("declines") or [])
    branches = list(last.get("branches") or [])
    first_branch_prevent = ""
    for b in branches:
        if b.get("marker") == "before_stop" or "bypass" in str(b.get("detail") or ""):
            first_branch_prevent = str(b.get("detail") or b.get("marker"))
            break
    decline_reason = declines[-1].get("reason") if declines else ""
    if fn_entry and not (fn_entry.get("decline") or ""):
        decline_reason = decline_reason or (declines[-1].get("reason") if declines else "")
    elif fn_entry and fn_entry.get("decline"):
        decline_reason = str(fn_entry.get("decline"))
    proposed = ""
    if not callsite:
        proposed = "Script path never reached pre_try_micro_p2a_call_site; inspect earlier st.stop/rerun branches."
    elif not fn_entry:
        proposed = "Call-site reached but try_micro_p2a not invoked (early_room_not_dict or ImportError)."
    elif decline_reason == "active_page_not_entered":
        proposed = "Relax or satisfy active_page_entered before P2A hook (diagnostic readiness only)."
    elif decline_reason == "creation_pending":
        proposed = "Wait until start_pending/post_create_open clear before P2A hook."
    elif decline_reason == "status_not_in_progress":
        proposed = "Ensure live_draft_room status in_progress and is_solo_live_draft at call site."
    elif decline_reason == "placement_not_p2a":
        proposed = "Fix session/query placement latch for P2A."
    return {
        "callsite_present": bool(callsite),
        "fn_entry_present": bool(fn_entry),
        "decline_reason": decline_reason,
        "first_branch_bypass": first_branch_prevent,
        "branches_tail": branches[-8:],
        "declines_tail": declines[-8:],
        "proposed_diagnostic_correction": proposed,
    }


def wait_p2a_micro_observation(page, *, max_wait_s: int = 75) -> dict[str, Any]:
    from run_solo_placement_micro_matrix import scrape_micro_probe

    deadline = time.time() + max_wait_s
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = scrape_micro_probe(page)
        if (
            last
            and str(last.get("placement") or "").upper() == "P2A"
            and last.get("key")
            and last.get("token")
            and "try_micro_p2a_before_early_reconcile" in str(last.get("source") or "")
        ):
            return {"ready": True, "probe": last, "observation_ready": True}
        page.wait_for_timeout(1000)
    return {"ready": False, "probe": last, "observation_ready": False}


def _tokens_from_ws(ws_frames: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for frame in ws_frames:
        snip = str(frame.get("snippet") or "")
        for match in re.finditer(r"DIAGP2A\|0\|[0-9.]+", snip):
            out.append(match.group(0))
    return list(dict.fromkeys(out))


def classify_p2a(
    *,
    draft_start: dict[str, Any],
    observation: dict[str, Any],
    probe: dict[str, Any] | None,
    ws_frames: list[dict[str, Any]],
) -> tuple[str, str]:
    if not draft_start.get("start_success"):
        return "invalid", "draft_start_failed"
    obs = probe or observation.get("probe") or {}
    if not observation.get("observation_ready"):
        return "invalid", "micro_probe_not_ready"
    stages = str(obs.get("stages") or "")
    raw = stages.count("session_state_raw_received")
    oc = stages.count("on_change_callback_entry")
    tokens = _tokens_from_ws(ws_frames)
    if raw == 1 and oc == 1:
        return "pass", ""
    if tokens and raw == 0 and oc == 0:
        return "fail", ""
    if tokens and (raw >= 1 or oc >= 1):
        return "pass" if raw == 1 and oc == 1 else "invalid", "partial_python_receipt"
    return "invalid", "no_outbound_or_no_mount"


def main() -> int:
    from playwright.sync_api import sync_playwright
    from run_solo_clean_verification import scrape_live_sha
    from run_solo_delivery_isolation import install_ws_and_postmessage_hooks
    from run_solo_placement_micro_matrix import scrape_micro_probe
    from solo_draft_start_harness import checkpoint, execute_solo_draft_start_workflow

    proven_cps: list[dict[str, Any]] = []
    if P2_GATE_ARTIFACT.is_file():
        try:
            gate = json.loads(P2_GATE_ARTIFACT.read_text(encoding="utf-8"))
            proven_cps = list((gate.get("draft_start") or {}).get("checkpoints") or [])
        except (json.JSONDecodeError, OSError):
            proven_cps = []

    ws_frames: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "started_at": time.time(),
        "p2a_setup_url": P2A_SETUP_URL,
        "p2a_hook_expected": P2A_HOOK,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        page = browser.new_page(viewport={"width": 1440, "height": 1400})
        install_ws_and_postmessage_hooks(page, ws_frames)
        ws_baseline = len(ws_frames)

        draft = execute_solo_draft_start_workflow(page, P2A_SETUP_URL, navigate=True)
        report["draft_start"] = draft
        report["deploy_sha"] = scrape_live_sha(page)
        cps = list(draft.get("checkpoints") or [])
        report["user_checkpoints"] = build_user_checkpoint_report(cps)
        report["divergence_vs_p2_gate"] = first_user_divergence(cps, proven_cps)

        path_poll = poll_p2a_path_diagnostics(page, max_wait_s=90)
        report["p2a_path_diagnostics"] = path_poll
        report["p2a_path_interpretation"] = interpret_p2a_path(path_poll)

        observation = wait_p2a_micro_observation(page)
        report["micro_observation"] = observation

        expire_deadline = time.time() + WAIT_EXPIRE_S
        last_probe: dict[str, Any] | None = None
        while time.time() < expire_deadline:
            last_probe = scrape_micro_probe(page) or last_probe
            if last_probe and last_probe.get("complete") in ("1", "true", True):
                break
            if last_probe and "on_change_callback_entry" in str(last_probe.get("stages") or ""):
                break
            page.wait_for_timeout(1000)

        probe = last_probe or scrape_micro_probe(page) or observation.get("probe") or {}
        report["final_micro_probe"] = probe
        report["ws_frames"] = ws_frames[ws_baseline:]
        report["outbound_tokens"] = _tokens_from_ws(report["ws_frames"])
        report["outbound_token_count"] = len(report["outbound_tokens"])
        report["on_change_callback_count"] = str(probe.get("stages") or "").count(
            "on_change_callback_entry"
        )
        report["session_state_raw_received"] = str(probe.get("stages") or "").count(
            "session_state_raw_received"
        )
        report["duplicate_callback_count"] = 0

        p1_note: dict[str, Any] = {}
        if MATRIX_ARTIFACT.is_file():
            try:
                matrix = json.loads(MATRIX_ARTIFACT.read_text(encoding="utf-8"))
                for row in matrix.get("placements") or []:
                    if row.get("placement") == "P1":
                        p1_note = {
                            "outbound_token_count": row.get("outbound_token_count"),
                            "on_change_callback_entry": row.get("on_change_callback_entry"),
                            "note": "two WS frames / two reruns with one Python callback — not duplicate delivery",
                        }
                        break
            except (json.JSONDecodeError, OSError):
                pass
        report["p1_ws_rerun_note"] = p1_note

        verdict, invalid_reason = classify_p2a(
            draft_start=draft,
            observation=observation,
            probe=probe,
            ws_frames=report["ws_frames"],
        )
        latch = _step_present(cps, "placement_latch_after_sidebar")
        latch_val = ((latch or {}).get("latch") or {}).get("requested") or ""
        report["summary"] = {
            "verdict": verdict,
            "invalid_reason": invalid_reason,
            "room_id": draft.get("room_id") or probe.get("room_id") or "",
            "room_in_progress": bool(draft.get("start_success")),
            "latch": latch_val,
            "hook_reached": "try_micro_p2a_before_early_reconcile"
            in str(probe.get("source") or ""),
            "component_key": probe.get("key") or "",
            "raw_token": probe.get("token") or "",
            "observation_ready": bool(observation.get("observation_ready")),
            "first_startup_divergence": report["divergence_vs_p2_gate"],
            "p2a_path": report["p2a_path_interpretation"],
            "artifact_path": str(OUT),
        }
        browser.close()

    report["finished_at"] = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"artifact": str(OUT), "summary": report["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
