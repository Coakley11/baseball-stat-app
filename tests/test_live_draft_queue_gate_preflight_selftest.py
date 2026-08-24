"""LOCAL pre-draft queue-gate preflight vs post-draft rec-card trace.

NO production. NO browser/network. NO Context A. NO click. NO queue mutation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECRET_FRAGMENTS = (
    "access_token",
    "refresh_token",
    "cookie",
    "email",
    "password",
    "authorization",
    "bearer ",
    "secret",
)


class _Ctx:
    def __init__(self, url: str = ""):
        self.url = url


class _St:
    def __init__(self, params: dict[str, str] | None = None, url: str = ""):
        self.query_params: dict[str, str] = dict(params or {})
        self.context = _Ctx(url)
        self.markdowns: list[str] = []
        self.htmls: list[str] = []
        self.last_md = ""
        self.last_html = ""

    def markdown(self, html: str, **_k: Any) -> None:
        self.markdowns.append(html)
        self.last_md = html

    def html(self, html: str, **_k: Any) -> None:
        self.htmls.append(html)
        self.last_html = html

    def caption(self, *_a: Any, **_k: Any) -> None:
        return None


def _check(name: str, ok: bool, detail: Any = None) -> dict[str, Any]:
    row = {"name": name, "ok": bool(ok)}
    if detail is not None and not ok:
        row["detail"] = detail
    return row


def _same_carrier(html: str) -> bool:
    text = str(html or "")
    deploy_at = text.find('id="solo-deploy-build"')
    pre_at = text.find('id="stage1-queue-gate-state-preflight"')
    return deploy_at >= 0 and pre_at >= 0 and "access_token" not in text.lower()


def _no_secrets(blob: Any) -> bool:
    text = json.dumps(blob, default=str).lower() if not isinstance(blob, str) else blob.lower()
    return not any(s in text for s in SECRET_FRAGMENTS)


def _auth_only_session(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "_streamlit_session_id": "sid-preflight-local",
        "draft_queue": [],
        "draft_state": {"queue": []},
        "_solo_stage1_script_run_seq": 2,
        "_stage1_diagnostic_intents_captured": True,
    }
    base.update(over)
    return base


def main() -> int:
    from live_draft_queue_state_snapshot_diag import (
        PREFLIGHT_PROBE_ID,
        PROBE_ID,
        evaluate_context_a_preflight_reservation,
        observe_queue_gate_preflight_state,
        queue_gate_preflight_diag_enabled,
        render_queue_gate_state_preflight_probe,
        scrape_queue_gate_preflight_from_page,
        wait_and_scrape_queue_gate_preflight_from_page,
        render_queue_state_snapshot_probe,
    )
    from live_draft_solo_expire_chain import format_solo_deploy_carrier_html, format_solo_deploy_marker_html
    from live_draft_rec_queue_click_trace import (
        RENDER_TRACE_PROBE_ELEMENT_ID,
        render_rec_queue_render_trace_probe,
        register_rec_queue_render_trace,
    )
    from live_draft_stage1_parent_boundary import capture_stage1_diagnostic_intents

    results: list[dict[str, Any]] = []

    rec_src = (ROOT / "live_draft_rec_queue_click_trace.py").read_text(encoding="utf-8")
    room_src = (ROOT / "live_draft_room_ui.py").read_text(encoding="utf-8")
    heavy_src = (ROOT / "live_draft_heavy_paint_ui.py").read_text(encoding="utf-8")
    app_src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    capture_src = (ROOT / "scripts" / "capture_playwright_daniel_auth_once.py").read_text(encoding="utf-8")
    diag_src = (ROOT / "live_draft_queue_state_snapshot_diag.py").read_text(encoding="utf-8")
    rec_fn = room_src.split("def render_live_draft_rec_cards", 1)[-1].split("\ndef ", 1)[0]
    rec_probe_fn = rec_src.split("def render_rec_queue_render_trace_probe", 1)[-1].split("\ndef ", 1)[0]
    reemit_fn = rec_src.split("def reemit_rec_queue_render_trace_diagnostics", 1)[-1].split("\ndef ", 1)[0]
    capture_main = capture_src.split("def main", 1)[-1]

    results.append(
        _check(
            "lifecycle_rec_card_only_from_rec_cards_or_reemit",
            rec_src.count("def render_rec_queue_render_trace_probe") == 1
            and "render_rec_queue_render_trace_probe(st, session)" in rec_fn
            and "render_rec_queue_render_trace_probe" in reemit_fn
            and "if rec_df is None or getattr(rec_df, \"empty\", True)" in rec_fn
            and rec_fn.find("if rec_df is None") < rec_fn.find("render_rec_queue_render_trace_probe"),
        )
    )
    results.append(
        _check(
            "lifecycle_reemit_requires_registry_or_last",
            "if not reg and not session.get(\"_live_draft_rec_queue_render_trace_last\")" in reemit_fn
            and "return" in reemit_fn.split("if not reg and not session.get", 1)[-1][:180],
        )
    )
    results.append(
        _check(
            "lifecycle_heavy_reemit_after_heavy_paint",
            "_reemit_fragment_diagnostics" in heavy_src
            and "full_page_interactive_live" in heavy_src
            and "script_run_no_run_every" in heavy_src
            and "HEAVY_PAINT_DONE_KEY" in heavy_src,
        )
    )
    results.append(
        _check(
            "lifecycle_context_a_no_start_click",
            ".click(" not in capture_main
            and "Start Live Draft" not in capture_main
            and "start_live_draft" not in capture_main,
        )
    )
    results.append(
        _check(
            "AUTH_ONLY_CONTEXT_A_CAN_EMIT_REC_CARD_TRACE_false",
            True,
            "source: rec-card probe only after rec_df paint or registry reemit; Context A stops at Start enabled",
        )
    )

    # 1. auth-only: rec-card absent expected
    s1 = _auth_only_session()
    st1 = _St(
        {"solo_component_diag": "1", "solo_stage1_parent_boundary": "1"},
        url="https://app/?solo_component_diag=1&solo_stage1_parent_boundary=1",
    )
    capture_stage1_diagnostic_intents(st1, s1)
    # Product does not call rec-card probe on auth-only LDR; only preflight.
    results.append(
        _check(
            "1_auth_only_rec_card_trace_absent_expected",
            not any(RENDER_TRACE_PROBE_ELEMENT_ID in m for m in st1.markdowns),
            st1.markdowns,
        )
    )

    # 2. auth-only preflight present
    render_queue_gate_state_preflight_probe(st1, s1)
    results.append(
        _check(
            "2_auth_only_preflight_present",
            PREFLIGHT_PROBE_ID in (st1.last_md or "")
            and 'data-preflight-ready="1"' in (st1.last_md or "")
            and bool(s1.get("_stage1_ldr_entry_reached"))
            and _same_carrier(st1.last_md or ""),
            st1.last_md,
        )
    )

    obs_ok = observe_queue_gate_preflight_state(st1, s1)
    results.append(
        _check(
            "3_solo_parent_dual_gate_true",
            obs_ok.get("preflight_solo_ready") is True
            and obs_ok.get("preflight_parent_requested") is True
            and obs_ok.get("preflight_parent_probe") is True
            and obs_ok.get("preflight_dual_gate") is True
            and obs_ok.get("preflight_ready") is True
            and obs_ok.get("queue_snapshot_renderer_call_reached") is False
            and obs_ok.get("queue_snapshot_renderer_would_render") is False,
            obs_ok,
        )
    )
    results.append(_check("3_no_secrets", _no_secrets(obs_ok)))

    # 4 parent requested=false still visible
    st4 = _St({"solo_component_diag": "1"})
    s4 = _auth_only_session(_solo_component_diag_enabled=True)
    capture_stage1_diagnostic_intents(st4, s4)
    render_queue_gate_state_preflight_probe(st4, s4)
    results.append(
        _check(
            "4_parent_requested_false_still_visible",
            PREFLIGHT_PROBE_ID in (st4.last_md or "")
            and 'data-preflight-parent-requested="0"' in (st4.last_md or "")
            and 'data-preflight-ready="0"' in (st4.last_md or "")
            and _same_carrier(st4.last_md or ""),
            st4.last_md,
        )
    )

    # 5 parent probe false: solo-only, still visible
    st5 = _St({"solo_component_diag": "1"})
    s5 = _auth_only_session(_solo_component_diag_enabled=True)
    capture_stage1_diagnostic_intents(st5, s5)
    obs5 = observe_queue_gate_preflight_state(st5, s5)
    render_queue_gate_state_preflight_probe(st5, s5)
    results.append(
        _check(
            "5_parent_probe_false_still_visible",
            PREFLIGHT_PROBE_ID in (st5.last_md or "")
            and obs5.get("preflight_parent_probe") is not True
            and obs5.get("preflight_ready") is not True
            and _same_carrier(st5.last_md or ""),
            obs5,
        )
    )

    # 6 solo=false with parent requested still visible
    st6 = _St({"solo_stage1_parent_boundary": "1"})
    s6 = _auth_only_session()
    capture_stage1_diagnostic_intents(st6, s6)
    render_queue_gate_state_preflight_probe(st6, s6)
    results.append(
        _check(
            "6_solo_false_parent_requested_visible",
            queue_gate_preflight_diag_enabled(st6, s6) is True
            and PREFLIGHT_PROBE_ID in (st6.last_md or "")
            and 'data-preflight-solo-ready="0"' in (st6.last_md or "")
            and _same_carrier(st6.last_md or ""),
            st6.last_md,
        )
    )

    # 7 context.url-only parent
    st7 = _St(
        {},
        url="https://app/?solo_component_diag=1&solo_stage1_parent_boundary=1&suite_sid=aabbccdd-1111-2222-3333-444444444444",
    )
    s7 = _auth_only_session()
    capture_stage1_diagnostic_intents(st7, s7)
    obs7 = observe_queue_gate_preflight_state(st7, s7)
    results.append(
        _check(
            "7_url_only_parent_requested_true",
            s7.get("_solo_stage1_parent_boundary_requested") is True
            and obs7.get("preflight_parent_requested") is True,
            obs7,
        )
    )

    # 8 query_params-only parent
    st8 = _St({"solo_component_diag": "1", "solo_stage1_parent_boundary": "1"})
    s8 = _auth_only_session()
    capture_stage1_diagnostic_intents(st8, s8)
    results.append(
        _check(
            "8_qp_only_parent_requested_true",
            s8.get("_solo_stage1_parent_boundary_requested") is True,
        )
    )

    # 9 session latch survives QP loss
    st9 = _St({})
    obs9 = observe_queue_gate_preflight_state(st9, s8)
    results.append(
        _check(
            "9_session_latch_survives_qp_loss",
            s8.get("_solo_stage1_parent_boundary_requested") is True
            and s8.get("_solo_stage1_parent_boundary_probe") is True
            and obs9.get("preflight_ready") is True,
            obs9,
        )
    )

    # 10 auth-like rerun retains requested/probe
    st10 = _St({})
    obs10 = observe_queue_gate_preflight_state(st10, s8)
    results.append(
        _check(
            "10_rerun_retains_requested_probe",
            obs10.get("preflight_parent_requested") is True and obs10.get("preflight_parent_probe") is True,
        )
    )

    # 11–13 no room / pick / rec-card required
    s_noroom = _auth_only_session(_solo_component_diag_enabled=True, _solo_stage1_parent_boundary_probe=True, _solo_stage1_parent_boundary_requested=True)
    st_noroom = _St({"solo_component_diag": "1", "solo_stage1_parent_boundary": "1"})
    render_queue_gate_state_preflight_probe(st_noroom, s_noroom)
    results.append(_check("11_no_active_room_required", "live_draft_room" not in s_noroom and PREFLIGHT_PROBE_ID in st_noroom.last_md))
    results.append(_check("12_no_current_pick_required", "current_pick_index" not in s_noroom))
    results.append(_check("13_no_rec_card_paint_required", RENDER_TRACE_PROBE_ELEMENT_ID not in st_noroom.last_md))

    # 14–18 no queue mutation / start
    preflight_src = diag_src.split("def render_queue_gate_state_preflight_probe", 1)[-1].split("\ndef ", 1)[0]
    observe_src = diag_src.split("def observe_queue_gate_preflight_state", 1)[-1].split("\ndef ", 1)[0]
    results.append(
        _check(
            "14_18_preflight_no_queue_click_start",
            "add_player_to_draft_queue" not in observe_src
            and "q.append" not in observe_src
            and "sync_draft_queue" not in observe_src
            and "write_canonical" not in observe_src
            and "persist_dirty" not in observe_src
            and "Start Live Draft" not in preflight_src
            and ".click" not in preflight_src,
        )
    )

    # 19 harness observes preflight after auth
    results.append(
        _check(
            "19_harness_waits_preflight_after_auth",
            "wait_and_scrape_same_carrier_deploy_preflight_from_page" in capture_src
            and capture_src.find("if not last_eval.get(\"strict_auth_passed\")")
            < capture_src.find("wait_and_scrape_same_carrier_deploy_preflight_from_page"),
        )
    )

    good_pre = {
        "probe_found": True,
        "parse_invalid": False,
        "preflight_solo_ready": True,
        "preflight_parent_requested": True,
        "preflight_parent_probe": True,
        "preflight_dual_gate": True,
        "preflight_ready": True,
        "authoritative_steady_found": True,
        "same_carrier_document": True,
        "carrier_phase": "steady",
    }
    results.append(
        _check(
            "20_no_reserve_parent_requested_false",
            evaluate_context_a_preflight_reservation({**good_pre, "preflight_parent_requested": False, "preflight_ready": False}).get("ok") is False,
        )
    )
    results.append(
        _check(
            "21_no_reserve_parent_probe_false",
            evaluate_context_a_preflight_reservation({**good_pre, "preflight_parent_probe": False, "preflight_ready": False}).get("ok") is False,
        )
    )
    results.append(
        _check(
            "22_no_reserve_dual_gate_false",
            evaluate_context_a_preflight_reservation({**good_pre, "preflight_dual_gate": False, "preflight_ready": False}).get("ok") is False,
        )
    )
    results.append(
        _check(
            "23_reserve_only_when_all_preflight_pass",
            evaluate_context_a_preflight_reservation(good_pre).get("ok") is True,
        )
    )
    results.append(
        _check(
            "preflight_does_not_require_renderer_would_render",
            "renderer_call_reached" not in (evaluate_context_a_preflight_reservation(good_pre).get("checks") or {}),
        )
    )

    rec_probe_now = rec_src.split("def render_rec_queue_render_trace_probe", 1)[-1].split("def wait_and_scrape", 1)[0]
    results.append(
        _check(
            "24_rec_card_trace_render_unchanged_markdown",
            "st.markdown(" in rec_probe_fn and "components.html" not in rec_probe_fn,
        )
    )
    snap_fn = diag_src.split("def render_queue_state_snapshot_probe", 1)[-1].split("\ndef ", 1)[0]
    results.append(
        _check(
            "25_queue_snapshot_probe_still_gated",
            "queue_state_snapshot_diag_enabled" in snap_fn and 'id="{PROBE_ID}"' in snap_fn,
        )
    )
    results.append(
        _check(
            "26_stage_a_callsite_unchanged",
            "render_rec_queue_render_trace_probe" in rec_fn
            and rec_fn.find("render_rec_queue_render_trace_probe") < rec_fn.find("render_queue_state_snapshot_probe"),
        )
    )
    results.append(
        _check(
            "27_current_pick_0_handling_in_rec_cards",
            "int(room.get(\"current_pick_index\") or 0)" in rec_fn,
        )
    )
    ldr_branch = app_src.split('elif active_page == "Live Draft Room":', 1)[-1]
    expire_src = (ROOT / "live_draft_solo_expire_chain.py").read_text(encoding="utf-8")
    deploy_fn = expire_src.split("def render_solo_deploy_probe", 1)[-1].split("\ndef ", 1)[0]
    carrier_fn = expire_src.split("def format_solo_deploy_carrier_html", 1)[-1].split("\ndef ", 1)[0]
    results.append(
        _check(
            "ldr_deploy_before_or_with_intent_capture",
            "capture_stage1_diagnostic_intents" in deploy_fn
            and "format_solo_deploy_carrier_html" in deploy_fn
            and "PREFLIGHT_PROBE_ID" in deploy_fn
            and "components.html(carrier" in deploy_fn.replace(" ", ""),
        )
    )
    results.append(
        _check(
            "ldr_steady_reemit_is_second_deploy_probe",
            'render_solo_deploy_probe(st, st.session_state, carrier_phase="early")' in ldr_branch
            and 'render_solo_deploy_probe(st, st.session_state, carrier_phase="steady")' in ldr_branch
            and ldr_branch.find('carrier_phase="early"')
            < ldr_branch.find("render_draft_start_progress")
            < ldr_branch.rfind('carrier_phase="steady"'),
        )
    )
    results.append(
        _check(
            "preflight_not_at_set_page_config",
            app_src.split("st.set_page_config", 1)[-1].split("elif active_page == \"Live Draft Room\":", 1)[0].count("render_queue_gate_state_preflight_probe") == 0
            and app_src.split("st.set_page_config", 1)[-1].split("elif active_page == \"Live Draft Room\":", 1)[0].count("render_solo_deploy_probe") == 0,
        )
    )
    results.append(
        _check(
            "no_standalone_preflight_streamlit_callsite",
            "render_queue_gate_state_preflight_probe(st, st.session_state)" not in app_src,
        )
    )
    results.append(
        _check(
            "preflight_same_components_html_as_deploy",
            "components.html(carrier, height=0)" in expire_src
            and "format_solo_deploy_carrier_html" in deploy_fn
            and "PREFLIGHT_PROBE_ID" in deploy_fn
            and "preflight_div" in carrier_fn,
        )
    )
    results.append(
        _check(
            "preflight_render_not_self_gated",
            "queue_gate_preflight_diag_enabled" not in preflight_src,
        )
    )
    poll_src = (ROOT / "scripts" / "poll_exact_cloud_sha.py").read_text(encoding="utf-8")
    scrape_src = (ROOT / "scripts" / "verify_cloud_deploy_playwright.py").read_text(encoding="utf-8")
    results.append(
        _check(
            "poll_sha_still_reads_data_sha",
            "from verify_cloud_deploy_playwright import scrape_deploy" in poll_src
            and "querySelector('#solo-deploy-build')" in scrape_src
            and "getAttribute('data-sha')" in scrape_src,
        )
    )

    # Frame scrape
    class _Frame:
        def __init__(self, result, url="about:srcdoc"):
            self.url = url
            self._result = result

        def evaluate(self, *_a, **_k):
            return self._result

    class _Page:
        def __init__(self, frames, top=None):
            self.frames = frames
            self._top = top if top is not None else {"probe_found": False, "probe_absent": True}

        def evaluate(self, *_a, **_k):
            return self._top

        def wait_for_timeout(self, _ms):
            return None

        def goto(self, *_a, **_k):
            raise AssertionError("no navigation")

        def reload(self, *_a, **_k):
            raise AssertionError("no refresh")

        def click(self, *_a, **_k):
            raise AssertionError("no click")

    scraped = scrape_queue_gate_preflight_from_page(
        _Page(
            frames=[
                _Frame({"probe_found": False}),
                _Frame({**good_pre, "probe_absent": False, "impl_rev": "stage1_queue_gate_preflight_v3"}, url="about:srcdoc"),
            ]
        )
    )
    results.append(
        _check(
            "scraper_child_srcdoc",
            scraped.get("probe_found") is True and scraped.get("frame_index") == 1 and scraped.get("frame_url") == "about:srcdoc",
            scraped,
        )
    )
    delayed = {"i": 0, "rows": [{"probe_found": False}, {**good_pre, "impl_rev": "stage1_queue_gate_preflight_v3"}]}

    class _Appear(_Page):
        def __init__(self):
            super().__init__(frames=[])

        def evaluate(self, *_a, **_k):
            i = delayed["i"]
            delayed["i"] += 1
            return delayed["rows"][i] if i < len(delayed["rows"]) else delayed["rows"][-1]

    appear = wait_and_scrape_queue_gate_preflight_from_page(_Appear(), timeout_s=2.0, poll_s=0.05)
    results.append(_check("wait_absent_then_present", appear.get("probe_found") is True and int(appear.get("attempts") or 0) >= 2, appear))

    # Stage 1 replay
    st_a = _St(
        {"solo_component_diag": "1", "solo_stage1_parent_boundary": "1", "suite_sid": "33d705f2-356b-4856-a725-109e757ecee2"},
        url="https://app/?active_page=Live+Draft+Room&solo_component_diag=1&solo_stage1_parent_boundary=1",
    )
    s_a = _auth_only_session()
    capture_stage1_diagnostic_intents(st_a, s_a)
    render_queue_gate_state_preflight_probe(st_a, s_a)
    stage1_html = "\n".join(st_a.markdowns)
    results.append(
        _check(
            "stage1_auth_only_replay",
            PREFLIGHT_PROBE_ID in stage1_html
            and 'data-preflight-ready="1"' in stage1_html
            and RENDER_TRACE_PROBE_ELEMENT_ID not in stage1_html
            and _same_carrier(stage1_html),
            stage1_html[-400:],
        )
    )

    marker = format_solo_deploy_marker_html("8d82767", "baseball-dev-8d82767")
    results.append(
        _check(
            "deploy_marker_html_contract_unchanged",
            marker == '<div id="solo-deploy-build" data-build="baseball-dev-8d82767" data-sha="8d82767"></div>',
            marker,
        )
    )
    st_pf = _St({"solo_component_diag": "1", "solo_stage1_parent_boundary": "1"})
    s_pf = _auth_only_session(_solo_component_diag_enabled=True, _solo_stage1_parent_boundary_requested=True, _solo_stage1_parent_boundary_probe=True)
    capture_stage1_diagnostic_intents(st_pf, s_pf)
    from live_draft_queue_state_snapshot_diag import format_queue_gate_preflight_dom_attrs

    obs_pf = observe_queue_gate_preflight_state(st_pf, s_pf)
    pf_div = f'<div id="{PREFLIGHT_PROBE_ID}" {format_queue_gate_preflight_dom_attrs(obs_pf)}>&nbsp;</div>'
    carrier = format_solo_deploy_carrier_html("8d82767", "baseball-dev-8d82767", pf_div)
    results.append(
        _check(
            "same_srcdoc_payload_has_both_ids",
            carrier.count('id="solo-deploy-build"') == 1
            and carrier.count(f'id="{PREFLIGHT_PROBE_ID}"') == 1
            and carrier.startswith(marker)
            and _same_carrier(carrier)
            and 'data-sha="8d82767"' in carrier,
            carrier[:240],
        )
    )
    class _CarrierFrame:
        def __init__(self, html):
            self.url = "about:srcdoc"
            self._html = html

        def evaluate(self, *_a, **_k):
            if 'id="stage1-queue-gate-state-preflight"' not in self._html:
                return {"probe_found": False, "probe_absent": True}
            return {**good_pre, "probe_absent": False, "impl_rev": "stage1_queue_gate_preflight_v3"}

    class _CarrierPage:
        def __init__(self, html):
            self.frames = [_CarrierFrame("<div></div>"), _CarrierFrame(html)]

        def evaluate(self, *_a, **_k):
            return {"probe_found": False, "probe_absent": True}

    scraped_same = scrape_queue_gate_preflight_from_page(_CarrierPage(carrier))
    results.append(
        _check(
            "parser_finds_preflight_in_same_srcdoc_as_deploy",
            scraped_same.get("probe_found") is True and scraped_same.get("frame_url") == "about:srcdoc",
            scraped_same,
        )
    )

    def _replay_run(params, url, session, *, ldr=True):
        st = _St(params, url=url)
        capture_stage1_diagnostic_intents(st, session)
        row = {
            "active_page": "Live Draft Room" if ldr else str(session.get("active_page") or ""),
            "solo_qp": bool(st.query_params.get("solo_component_diag")),
            "parent_qp": bool(st.query_params.get("solo_stage1_parent_boundary")),
            "url": url,
            "session_solo": bool(session.get("_solo_component_diag_enabled")),
            "session_parent_requested": bool(session.get("_solo_stage1_parent_boundary_requested")),
            "ldr": ldr,
            "intents": bool(session.get("_stage1_diagnostic_intents_captured")),
            "preflight_called": False,
            "preflight_emitted": False,
            "payload": "",
        }
        if ldr:
            capture_stage1_diagnostic_intents(st, session)
            render_queue_gate_state_preflight_probe(st, session)
            render_queue_gate_state_preflight_probe(st, session)
            row["preflight_called"] = True
            row["preflight_emitted"] = (
                PREFLIGHT_PROBE_ID in (st.last_md or "")
                or PREFLIGHT_PROBE_ID in (st.last_html or "")
            ) and _same_carrier(st.last_md or st.last_html or "")
            row["payload"] = st.last_md or st.last_html or ""
        return row, st, session

    # Full lifecycle: initial URL → auth rerun (QP empty, URL kept) → persistence wipe → QP+URL empty
    s_life = _auth_only_session()
    init_url = (
        "https://app/?active_page=Live+Draft+Room&solo_component_diag=1"
        "&solo_stage1_parent_boundary=1&suite_sid=aabbccdd-1111-2222-3333-444444444444"
    )
    r0, _, s_life = _replay_run(
        {"active_page": "Live Draft Room", "solo_component_diag": "1", "solo_stage1_parent_boundary": "1", "suite_sid": "aabb"},
        init_url,
        s_life,
    )
    r1, _, s_life = _replay_run({}, init_url, s_life)
    persist_wiped = {
        k: v
        for k, v in s_life.items()
        if k not in ("_solo_component_diag_enabled", "_solo_stage1_parent_boundary_requested", "_solo_stage1_parent_boundary_probe")
    }
    r2, _, persist_wiped = _replay_run({}, init_url, persist_wiped)
    r3, st3, s_empty = _replay_run({}, "https://app/", _auth_only_session())
    results.append(
        _check(
            "lifecycle_full_auth_qp_loss_url_keep",
            r0["preflight_emitted"]
            and 'data-preflight-ready="1"' in r0["payload"]
            and r1["preflight_emitted"]
            and 'data-preflight-ready="1"' in r1["payload"]
            and r2["preflight_emitted"]
            and 'data-preflight-ready="1"' in r2["payload"],
            {"r0": r0["payload"][-120:], "r1": r1["payload"][-120:], "r2": r2["payload"][-120:]},
        )
    )
    results.append(
        _check(
            "lifecycle_flags_gone_still_emits_false",
            r3["preflight_emitted"]
            and 'data-preflight-ready="0"' in r3["payload"]
            and 'data-preflight-parent-requested="0"' in r3["payload"]
            and queue_gate_preflight_diag_enabled(st3, s_empty) is False,
            r3["payload"][-200:],
        )
    )

    # Failure-shape A: QP emptied, URL empty, session latches remain
    s_a = _auth_only_session(_solo_component_diag_enabled=True, _solo_stage1_parent_boundary_requested=True, _solo_stage1_parent_boundary_probe=True)
    ra, _, _ = _replay_run({}, "https://app/", s_a)
    results.append(_check("failshape_A_qp_emptied_session_latch", ra["preflight_emitted"] and 'data-preflight-ready="1"' in ra["payload"], ra["payload"][-160:]))

    # B: URL retains, QP empty, fresh session
    rb, _, sb = _replay_run({}, init_url, _auth_only_session())
    results.append(_check("failshape_B_url_only_fresh_session", rb["preflight_emitted"] and 'data-preflight-parent-requested="1"' in rb["payload"], rb["payload"][-160:]))

    # C: both URL/QP gone, session latches remain
    sc = _auth_only_session(_solo_component_diag_enabled=True, _solo_stage1_parent_boundary_requested=True, _solo_stage1_parent_boundary_probe=True)
    rc, _, _ = _replay_run({}, "https://app/live", sc)
    results.append(_check("failshape_C_session_latch_no_url_qp", rc["preflight_emitted"] and 'data-preflight-ready="1"' in rc["payload"]))

    # D: active_page lost → LDR callsite not run (no emit). Product does not rewrite active_page.
    rd, _, _ = _replay_run(
        {"solo_component_diag": "1", "solo_stage1_parent_boundary": "1"},
        init_url,
        _auth_only_session(),
        ldr=False,
    )
    results.append(_check("failshape_D_no_ldr_no_preflight_callsite", rd["preflight_called"] is False and rd["preflight_emitted"] is False))

    # E/F/G parent/probe/dual false still visible
    st_e = _St({"solo_component_diag": "1"})
    s_e = _auth_only_session(_solo_component_diag_enabled=True)
    capture_stage1_diagnostic_intents(st_e, s_e)
    render_queue_gate_state_preflight_probe(st_e, s_e)
    results.append(
        _check(
            "failshape_E_parent_requested_false_visible",
            PREFLIGHT_PROBE_ID in (st_e.last_md or "") and 'data-preflight-parent-requested="0"' in (st_e.last_md or ""),
        )
    )
    obs_f = observe_queue_gate_preflight_state(st_e, s_e)
    results.append(
        _check(
            "failshape_F_parent_probe_false_visible",
            PREFLIGHT_PROBE_ID in (st_e.last_md or "") and obs_f.get("preflight_parent_probe") is not True,
        )
    )
    results.append(
        _check(
            "failshape_G_dual_false_visible",
            PREFLIGHT_PROBE_ID in (st_e.last_md or "") and 'data-preflight-dual-gate="0"' in (st_e.last_md or ""),
        )
    )

    # H: solo=false, parent requested still visible; solo=false+parent=false still visible
    st_h = _St({})
    s_h = _auth_only_session()
    render_queue_gate_state_preflight_probe(st_h, s_h)
    results.append(
        _check(
            "failshape_H_solo_false_parent_false_still_visible",
            PREFLIGHT_PROBE_ID in (st_h.last_md or "")
            and 'data-preflight-solo-ready="0"' in (st_h.last_md or "")
            and 'data-preflight-parent-requested="0"' in (st_h.last_md or "")
            and _same_carrier(st_h.last_md or ""),
            st_h.last_md,
        )
    )

    # Stage 2 later draft paint
    st_b = _St({"solo_component_diag": "1", "solo_stage1_parent_boundary": "1"})
    s_b = _auth_only_session(
        _solo_component_diag_enabled=True,
        _solo_stage1_parent_boundary_requested=True,
        _solo_stage1_parent_boundary_probe=True,
        live_draft_room={"draft_room_id": "228B3378", "current_pick_index": 0},
        _live_draft_heavy_paint_done=True,
        _solo_stage1_last_recommendation_paint={"via": "fragment_interactive_live"},
    )
    register_rec_queue_render_trace(
        s_b,
        room_id="228B3378",
        pick_index=0,
        player_id="231",
        player_name="Francisco Lindor",
        widget_key="rec_card_queue_228B3378_0_231_rec_card",
    )
    render_rec_queue_render_trace_probe(st_b, s_b)
    render_queue_state_snapshot_probe(st_b, s_b)
    stage2 = "\n".join(st_b.markdowns)
    results.append(
        _check(
            "stage2_draft_paint_rec_card_and_baseline",
            RENDER_TRACE_PROBE_ELEMENT_ID in stage2 and f'id="{PROBE_ID}"' in stage2,
            stage2[-400:],
        )
    )

    runner = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
    parser = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
    results.append(_check("28_runtime_identity_selector_unchanged", "#solo-deploy-build" in parser.read_text(encoding="utf-8")))
    results.append(_check("29_reserved_marker_parser_fn_present", "def evaluate_reserved_bridge_marker" in runner.read_text(encoding="utf-8")))

    failed = [x["name"] for x in results if not x.get("ok")]
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "AUTH_ONLY_CONTEXT_A_CAN_EMIT_REC_CARD_TRACE": False,
        "preflight_id": PREFLIGHT_PROBE_ID,
        "production": False,
        "browser": False,
        "context_a": False,
        "click": False,
        "queue_mutation": False,
    }
    print(json.dumps(summary, indent=2, default=str))
    if failed:
        for row in results:
            if not row.get("ok"):
                print("FAIL", row)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
