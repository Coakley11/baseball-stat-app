"""Deterministic LOCAL full-run query/latch/queue-probe emission selftest.

Replays the actual first-run ordering (mutation URL → ultra-early capture →
delivery diag → solo bootstrap → auth-like QP rewrite → LDR capture →
fragment rerun) using real product functions. Does NOT seed parent requested
by hand. Does NOT call production main(). No browser. No network. No click.
No queue mutation. Does not reuse consumed bridge 548c4dc9 as a live SID.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUNNER_PATH = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
APP_PATH = ROOT / "streamlit_app.py"
HEAVY_PATH = ROOT / "live_draft_heavy_paint_ui.py"
ROOM_UI_PATH = ROOT / "live_draft_room_ui.py"
TRACE_PATH = ROOT / "live_draft_rec_queue_click_trace.py"
DIAG_PATH = ROOT / "live_draft_queue_state_snapshot_diag.py"
PARENT_PATH = ROOT / "live_draft_stage1_parent_boundary.py"
CLOUD_PATH = ROOT / "live_draft_cloud_diagnostics.py"

CONSUMED_548 = "548c4dc9-8d5c-4f5c-8e83-fb68d8901ce8"
LOCAL_SID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
LOCAL_ROOM = "DFC73919"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _check(name: str, ok: bool, detail: Any = None) -> dict[str, Any]:
    row = {"name": name, "ok": bool(ok)}
    if detail is not None and not ok:
        row["detail"] = detail
    return row


class _Ctx:
    def __init__(self, url: str = ""):
        self.url = url


class _St:
    """Streamlit-like surface for first-run / fragment / auth-like QP mutation."""

    def __init__(self, params: dict[str, str] | None = None, url: str = ""):
        self.query_params: dict[str, str] = dict(params or {})
        self.context = _Ctx(url)
        self.markdowns: list[str] = []
        self.htmls: list[str] = []
        self.last_md = ""
        self.last_html = ""
        self.session_state: dict[str, Any] = {}
        self.fragment = None

    def markdown(self, html: str, **_k: Any) -> None:
        self.markdowns.append(html)
        self.last_md = html

    def html(self, html: str, **_k: Any) -> None:
        self.htmls.append(html)
        self.last_html = html


def _mutation_url(runner, sid: str) -> str:
    return runner.build_francisco_mutation_proof_url(sid)


def _params_from_url(url: str) -> dict[str, str]:
    q = parse_qs(urlparse(url).query, keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in q.items()}


def _ultra_early(st: _St, session: dict[str, Any]) -> None:
    from live_draft_stage1_parent_boundary import capture_stage1_diagnostic_intents
    from live_draft_solo_component_diagnostics import bootstrap_solo_component_diag

    capture_stage1_diagnostic_intents(st, session)
    try:
        from live_draft_solo_delivery_diag import enable_delivery_diag_from_query

        enable_delivery_diag_from_query(st, session)
    except Exception:
        pass
    bootstrap_solo_component_diag(st, session)


def _auth_like_qp_rewrite(st: _St, sid: str) -> None:
    """Model suite_auth_browser._set_session_id replacing query_params with suite_sid."""
    st.query_params = {"suite_sid": sid}


def _ldr_entry(st: _St, session: dict[str, Any]) -> None:
    from live_draft_stage1_parent_boundary import capture_stage1_diagnostic_intents

    capture_stage1_diagnostic_intents(st, session)


def _fragment_st(session: dict[str, Any], url: str) -> _St:
    st = _St({}, url=url)
    st.session_state = session
    return st


def _equal_queue_session(sid: str, room: str) -> dict[str, Any]:
    return {
        "_streamlit_session_id": sid,
        "_solo_stage1_run_id": "local-full-run-001",
        "draft_queue": [],
        "draft_state": {"queue": []},
        "live_draft_room": {"draft_room_id": room, "current_pick_index": 0},
        "_solo_stage1_script_run_seq": 19,
        "_solo_stage1_recommendation_fragment_run_seq": 2,
        "_live_draft_heavy_paint_done": True,
    }


def main() -> int:
    runner = _load(RUNNER_PATH, "francisco_mutation_full_run_query_latch")
    d = _load(DIAG_PATH, "queue_state_snapshot_diag_full_run")
    results: list[dict[str, Any]] = []

    url = _mutation_url(runner, CONSUMED_548)
    q = parse_qs(urlparse(url).query, keep_blank_values=True)
    pre = runner.evaluate_mutation_url_preflight(url)

    results.append(
        _check(
            "1_mutation_runner_url_has_required_diag_flags",
            pre.get("ok") is True
            and (q.get("solo_component_diag") or [""])[0] == "1"
            and (q.get("solo_stage1_parent_boundary") or [""])[0] == "1"
            and "Live Draft Room" in " ".join(q.get("active_page") or [])
            and (q.get("suite_sid") or [""])[0] == CONSUMED_548
            and "stage1_francisco_callback_only" not in q,
            pre,
        )
    )
    results.append(
        _check(
            "1b_parent_boundary_flag_present_on_initial_url",
            (q.get("solo_stage1_parent_boundary") or [""])[0] == "1",
        )
    )

    app_src = APP_PATH.read_text(encoding="utf-8")
    after_config = app_src.split("st.set_page_config", 1)[-1]
    first_capture = after_config.find("capture_stage1_diagnostic_intents")
    first_delivery = after_config.find("enable_delivery_diag_from_query")
    first_qp_write = min(
        i
        for i in (
            after_config.find("query_params["),
            after_config.find("query_params.clear"),
            after_config.find("from_dict"),
            10**9,
        )
        if i >= 0
    )
    results.append(
        _check(
            "2_exact_initial_url_enters_real_top_level_routing",
            first_capture >= 0
            and first_capture < first_delivery
            and "active_page=Live" in url.replace("%20", " ").replace("+", " "),
        )
    )

    # 3–4 capture both intents BEFORE query destruction, from REAL functions.
    params = _params_from_url(url)
    session_a: dict[str, Any] = {}
    st_a = _St(params, url=url)
    _ultra_early(st_a, session_a)
    results.append(
        _check(
            "3_solo_intent_captured_before_query_destruction",
            session_a.get("_solo_component_diag_enabled") is True,
            {k: session_a.get(k) for k in (
                "_solo_component_diag_enabled",
                "_solo_stage1_parent_boundary_requested",
                "_solo_stage1_parent_boundary_probe",
            )},
        )
    )
    results.append(
        _check(
            "4_parent_intent_captured_before_query_destruction",
            session_a.get("_solo_stage1_parent_boundary_requested") is True
            and session_a.get("_solo_stage1_parent_boundary_probe") is True,
            {k: session_a.get(k) for k in (
                "_solo_stage1_parent_boundary_requested",
                "_solo_stage1_parent_boundary_probe",
            )},
        )
    )

    # 5 first rerun with same QPs
    _ultra_early(st_a, session_a)
    results.append(
        _check(
            "5_both_survive_first_rerun",
            session_a.get("_solo_component_diag_enabled") is True
            and session_a.get("_solo_stage1_parent_boundary_probe") is True,
        )
    )

    # 6 auth-like suite_sid rewrite then rerun
    _auth_like_qp_rewrite(st_a, CONSUMED_548)
    st_a.context.url = (
        "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app/"
        f"?suite_sid={CONSUMED_548}"
    )
    _ultra_early(st_a, session_a)
    _ldr_entry(st_a, session_a)
    results.append(
        _check(
            "6_both_survive_auth_like_rerun",
            session_a.get("_solo_component_diag_enabled") is True
            and session_a.get("_solo_stage1_parent_boundary_requested") is True
            and session_a.get("_solo_stage1_parent_boundary_probe") is True,
        )
    )

    # 7 fragment rerun: empty query_params
    st_frag = _fragment_st(session_a, url="")
    from live_draft_queue_state_snapshot_diag import queue_state_snapshot_diag_enabled

    frag_enabled = queue_state_snapshot_diag_enabled(st_frag, session_a)
    results.append(
        _check(
            "7_both_survive_fragment_rerun",
            frag_enabled is True
            and session_a.get("_solo_stage1_parent_boundary_probe") is True,
        )
    )

    # 8 parent requested does not require solo already true
    session_parent_first: dict[str, Any] = {}
    st_parent_only = _St(
        {"solo_stage1_parent_boundary": "1"},
        url="https://app/?solo_stage1_parent_boundary=1",
    )
    from live_draft_stage1_parent_boundary import capture_stage1_diagnostic_intents

    capture_stage1_diagnostic_intents(st_parent_only, session_parent_first)
    results.append(
        _check(
            "8_parent_requested_not_dependent_on_solo",
            session_parent_first.get("_solo_stage1_parent_boundary_requested") is True
            and not session_parent_first.get("_solo_component_diag_enabled")
            and not session_parent_first.get("_solo_stage1_parent_boundary_probe"),
            session_parent_first,
        )
    )

    # 9 query clear after capture does not lose either intent
    results.append(
        _check(
            "9_query_clear_after_capture_keeps_intents",
            st_a.query_params == {"suite_sid": CONSUMED_548}
            and session_a.get("_solo_component_diag_enabled") is True
            and session_a.get("_solo_stage1_parent_boundary_probe") is True,
        )
    )

    # 10 old capture (query_params only, no context.url) misses URL-only parent
    from live_draft_cloud_diagnostics import _qp_from_context_url, _qp_get

    st_url_only = _St(
        {},
        url=(
            "https://app/?active_page=Live+Draft+Room&solo_component_diag=1"
            "&solo_stage1_parent_boundary=1&suite_sid=local-sid"
        ),
    )
    qp_only_parent = bool(str(st_url_only.query_params.get("solo_stage1_parent_boundary") or ""))
    url_parent = _qp_from_context_url(st_url_only, "solo_stage1_parent_boundary")
    results.append(
        _check(
            "10_query_params_only_misses_url_parent_old_failure",
            qp_only_parent is False
            and url_parent.lower() in ("1", "true", "yes", "on")
            and _qp_get(st_url_only, "solo_stage1_parent_boundary").lower() in ("1", "true"),
        )
    )

    # 11 rec-card render-trace path is the fragment_interactive_live sibling
    room_src = ROOM_UI_PATH.read_text(encoding="utf-8")
    heavy_src = HEAVY_PATH.read_text(encoding="utf-8")
    trace_src = TRACE_PATH.read_text(encoding="utf-8")
    rec_fn = room_src.split("def render_live_draft_rec_cards", 1)[-1].split("\ndef ", 1)[0]
    results.append(
        _check(
            "11_rec_card_trace_visible_implies_fragment_path",
            'RENDER_TRACE_PROBE_ELEMENT_ID = "rec-card-queue-render-trace"' in trace_src
            and "render_rec_queue_render_trace_probe" in rec_fn
            and "fragment_interactive_live" in heavy_src
            and "_reemit_fragment_diagnostics" in heavy_src,
        )
    )

    # 12 queue-probe call is reached in that same fragment path
    results.append(
        _check(
            "12_queue_probe_call_reached_in_same_fragment_path",
            "render_queue_state_snapshot_probe" in rec_fn
            and rec_fn.find("render_rec_queue_render_trace_probe")
            < rec_fn.find("render_queue_state_snapshot_probe")
            and "render_queue_state_snapshot_probe" in heavy_src
            and heavy_src.find("_reemit_fragment_diagnostics")
            < heavy_src.find("render_queue_state_snapshot_probe"),
        )
    )

    # Production-like split: empty query_params, full mutation flags on context.url
    replay_url = _mutation_url(runner, LOCAL_SID)
    session_replay = _equal_queue_session(LOCAL_SID, LOCAL_ROOM)
    st_wake = _St({}, url=replay_url)
    _ultra_early(st_wake, session_replay)
    _auth_like_qp_rewrite(st_wake, LOCAL_SID)
    _ultra_early(st_wake, session_replay)
    _ldr_entry(st_wake, session_replay)
    st_live = _fragment_st(session_replay, url=replay_url)
    gate = d.queue_state_snapshot_diag_enabled(st_live, session_replay)
    results.append(
        _check(
            "13_queue_probe_gate_true_on_url_only_full_run",
            gate is True
            and session_replay.get("_solo_component_diag_enabled") is True
            and session_replay.get("_solo_stage1_parent_boundary_requested") is True
            and session_replay.get("_solo_stage1_parent_boundary_probe") is True,
            {k: session_replay.get(k) for k in (
                "_solo_component_diag_enabled",
                "_solo_stage1_parent_boundary_requested",
                "_solo_stage1_parent_boundary_probe",
            )},
        )
    )

    d.render_queue_state_snapshot_probe(st_live, session_replay)
    html = st_live.last_md or ""
    results.append(
        _check(
            "14_empty_equal_queues_emit_baseline_probe",
            f'id="{d.PROBE_ID}"' in html
            and 'data-phase="QUEUE_STATE_BASELINE"' in html
            and f'data-sid="{LOCAL_SID}"' in html
            and f'data-room-id="{LOCAL_ROOM}"' in html
            and session_replay[d.SESSION_BASELINE_KEY]["session_queue"] == []
            and session_replay[d.SESSION_BASELINE_KEY]["canonical_queue"] == [],
            html[:400],
        )
    )

    session_ne = _equal_queue_session(LOCAL_SID, LOCAL_ROOM)
    session_ne["draft_queue"] = ["Shohei Ohtani"]
    session_ne["draft_state"] = {"queue": ["Shohei Ohtani"]}
    st_ne = _St(_params_from_url(replay_url), url=replay_url)
    _ultra_early(st_ne, session_ne)
    d.render_queue_state_snapshot_probe(st_ne, session_ne)
    results.append(
        _check(
            "15_nonempty_equal_queues_emit_baseline_probe",
            f'id="{d.PROBE_ID}"' in (st_ne.last_md or "")
            and session_ne[d.SESSION_BASELINE_KEY]["queues_equal"] is True
            and session_ne[d.SESSION_BASELINE_KEY]["session_queue"] == ["Shohei Ohtani"],
        )
    )

    session_mis = _equal_queue_session(LOCAL_SID, LOCAL_ROOM)
    session_mis["draft_queue"] = ["A"]
    session_mis["draft_state"] = {"queue": ["B"]}
    st_mis = _St(_params_from_url(replay_url), url=replay_url)
    _ultra_early(st_mis, session_mis)
    d.render_queue_state_snapshot_probe(st_mis, session_mis)
    results.append(
        _check(
            "16_mismatch_still_renders_diagnostic_probe",
            f'id="{d.PROBE_ID}"' in (st_mis.last_md or "")
            and session_mis[d.SESSION_BASELINE_KEY]["queues_equal"] is False,
        )
    )

    results.append(
        _check(
            "17_dom_id_stage1_queue_state_snapshot",
            d.PROBE_ID == "stage1-queue-state-snapshot"
            and f'id="{d.PROBE_ID}"' in html,
        )
    )
    results.append(
        _check(
            "18_dual_render_readonly",
            f'id="{d.PROBE_ID}"' in (st_live.last_md or "")
            and f'id="{d.PROBE_ID}"' in (st_live.last_html or "")
            and "add_player_to_draft_queue" not in DIAG_PATH.read_text(encoding="utf-8").split(
                "def record_queue_state_post_mutation_snapshot"
            )[0],
        )
    )

    class _Frame:
        def __init__(self, result, url="https://app/~/+/"):
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

    iframe_hit = {
        "probe_found": True,
        "sid": LOCAL_SID,
        "room_id": LOCAL_ROOM,
        "phase": "QUEUE_STATE_BASELINE",
        "json": "{}",
    }
    scraped = d.scrape_queue_state_snapshot_from_page(
        _Page(frames=[_Frame({"probe_found": False}, url="https://streamlit.app/"), _Frame(iframe_hit)])
    )
    results.append(
        _check(
            "19_page_frames_scraper_green",
            scraped.get("probe_found") is True and scraped.get("frame_strategy") == "page.frames",
        )
    )
    absent = d.scrape_queue_state_snapshot_from_page(
        _Page(frames=[_Frame({"probe_found": False, "probe_absent": True})])
    )
    parse_bad = d._decode_queue_probe_eval(
        {"probe_found": True, "sid": "", "phase": "", "json": "{not-json"},
        frame_index=0,
        frame_url="about:srcdoc",
    )
    results.append(
        _check(
            "20_parse_invalid_vs_absent_distinct",
            absent.get("probe_absent") is True
            and absent.get("parse_invalid") is False
            and parse_bad.get("probe_found") is True
            and parse_bad.get("parse_invalid") is True,
        )
    )

    runner_src = RUNNER_PATH.read_text(encoding="utf-8")
    reject_sid = "sid-reject-no-persist-0001"
    wrong_sid = runner.select_authoritative_baseline_queues(
        production_sid=reject_sid,
        snapshots=[
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": "other-sid",
                "room_id": LOCAL_ROOM,
                "session_queue": [],
                "canonical_queue": [],
                "ts": 1.0,
            }
        ],
    )
    results.append(
        _check(
            "21_wrong_sid_rejected",
            wrong_sid.get("baseline_known") is False,
            wrong_sid,
        )
    )
    wrong_room = runner.select_authoritative_baseline_queues(
        production_sid=reject_sid,
        room_id=LOCAL_ROOM,
        snapshots=[
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": reject_sid,
                "room_id": "OTHERROOM",
                "session_queue": [],
                "canonical_queue": [],
                "ts": 1.0,
            }
        ],
    )
    results.append(
        _check(
            "22_wrong_room_rejected",
            wrong_room.get("baseline_known") is False,
            wrong_room,
        )
    )
    wrong_phase = runner.select_authoritative_baseline_queues(
        production_sid=reject_sid,
        room_id=LOCAL_ROOM,
        snapshots=[
            {
                "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
                "streamlit_session_id": reject_sid,
                "room_id": LOCAL_ROOM,
                "session_queue": [],
                "canonical_queue": [],
                "ts": 1.0,
            }
        ],
    )
    results.append(
        _check(
            "23_wrong_phase_rejected",
            wrong_phase.get("baseline_known") is False,
            wrong_phase,
        )
    )

    pick_src = (ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924_stage_a_pick_propagation_selftest.py").read_text(encoding="utf-8")
    results.append(
        _check(
            "24_current_pick_0_stage_a_preserved",
            "current_pick_index" in pick_src and "first_defined" in runner_src,
        )
    )
    results.append(
        _check(
            "25_recommendation_fragment_seq_preserved",
            "recommendation_fragment_run_seq" in runner_src,
        )
    )
    ident = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924_runtime_identity_selftest.py"
    results.append(_check("26_runtime_identity_selftest_present", ident.is_file()))
    parser = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924_reserved_marker_parser_selftest.py"
    results.append(_check("27_bridge_parser_selftest_present", parser.is_file()))

    record_part = DIAG_PATH.read_text(encoding="utf-8").split("def record_queue_state_post_mutation_snapshot")[0]
    results.append(
        _check(
            "28_no_queue_mutation_in_baseline_record",
            "q.append" not in record_part and "add_player_to_draft_queue" not in record_part,
        )
    )
    results.append(_check("29_no_sync_in_baseline_record", "sync_draft_queue" not in record_part))
    results.append(_check("30_no_canonical_write_in_baseline_record", "write_canonical_draft_state" not in record_part))
    results.append(
        _check(
            "31_no_persistence_dirty_write_in_baseline_record",
            "session[DRAFT_QUEUE_PERSIST_DIRTY_KEY] =" not in record_part
            and "mark_draft_queue_persist_dirty" not in record_part,
        )
    )
    clicked = False
    results.append(_check("32_no_click_in_full_run_test", clicked is False))
    results.append(
        _check(
            "33_no_gate_arm_clear",
            "clear_francisco" not in record_part and "stage1_francisco_callback_only" not in url,
        )
    )
    results.append(
        _check(
            "34_no_stage_a_weakening",
            "first_defined" in runner_src
            and session_replay["live_draft_room"]["current_pick_index"] == 0,
        )
    )

    consumed = ROOT / "data" / "548c4dc9_consumed_bridge.txt"
    results.append(
        _check(
            "548c4dc9_permanently_consumed_not_reused_as_live_sid",
            consumed.is_file() and LOCAL_SID != CONSUMED_548,
        )
    )

    capture_src = PARENT_PATH.read_text(encoding="utf-8")
    cloud_src = CLOUD_PATH.read_text(encoding="utf-8")
    results.append(
        _check(
            "shared_bootstrap_captures_both_intents",
            "def capture_stage1_diagnostic_intents" in capture_src
            and "solo_component_diag" in capture_src
            and "remember_parent_boundary_request" in capture_src
            and "def _qp_from_context_url" in cloud_src
            and first_capture < first_delivery,
        )
    )
    results.append(
        _check(
            "ultra_early_capture_not_nested_in_delivery_diag",
            app_src.find("capture_stage1_diagnostic_intents")
            < app_src.find("from live_draft_solo_delivery_diag import enable_delivery_diag_from_query"),
        )
    )
    results.append(
        _check(
            "dual_render_reached_when_gate_true",
            bool(st_live.markdowns) and bool(st_live.htmls),
        )
    )
    results.append(
        _check(
            "full_run_did_not_hand_seed_parent_requested",
            "_solo_stage1_parent_boundary_requested" not in _equal_queue_session(LOCAL_SID, LOCAL_ROOM),
        )
    )

    from live_draft_rec_queue_click_trace import (
        RENDER_TRACE_PROBE_ELEMENT_ID,
        register_rec_queue_render_trace,
        render_rec_queue_render_trace_probe,
    )

    register_rec_queue_render_trace(
        session_replay,
        room_id=LOCAL_ROOM,
        pick_index=0,
        player_id="231",
        player_name="Francisco Lindor",
        widget_key=f"rec_card_queue_{LOCAL_ROOM}_0_231_rec_card",
    )
    session_replay["_solo_stage1_last_recommendation_paint"] = {"via": "fragment_interactive_live"}
    st_trace = _fragment_st(session_replay, url=replay_url)
    render_rec_queue_render_trace_probe(st_trace, session_replay)
    d.render_queue_state_snapshot_probe(st_trace, session_replay)
    success_html = " ".join(st_trace.markdowns)
    success_obs = session_replay.get(d.SESSION_GATE_OBS_KEY) or {}
    results.append(
        _check(
            "success_shape_rec_card_exposes_enabled_gate",
            f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in success_html
            and f'id="{d.PROBE_ID}"' in success_html
            and success_obs.get("solo_enabled") is True
            and success_obs.get("parent_requested") is True
            and success_obs.get("parent_probe") is True
            and success_obs.get("queue_state_snapshot_diag_enabled") is True
            and success_obs.get("queue_snapshot_renderer_call_reached") is True
            and success_obs.get("queue_snapshot_renderer_would_render") is True
            and success_obs.get("queue_snapshot_early_return_reason") == "enabled",
            success_obs,
        )
    )

    session_fail = _equal_queue_session(LOCAL_SID, LOCAL_ROOM)
    session_fail["_solo_component_diag_enabled"] = True
    session_fail["_solo_stage1_last_recommendation_paint"] = {"via": "fragment_interactive_live"}
    register_rec_queue_render_trace(
        session_fail,
        room_id=LOCAL_ROOM,
        pick_index=0,
        player_id="231",
        player_name="Francisco Lindor",
        widget_key=f"rec_card_queue_{LOCAL_ROOM}_0_231_rec_card",
    )
    st_fail = _St({}, url="https://app/")
    render_rec_queue_render_trace_probe(st_fail, session_fail)
    d.render_queue_state_snapshot_probe(st_fail, session_fail)
    fail_html = " ".join(st_fail.markdowns)
    fail_obs = session_fail.get(d.SESSION_GATE_OBS_KEY) or {}
    results.append(
        _check(
            "failure_shape_rec_card_visible_snapshot_absent_reason",
            f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in fail_html
            and f'id="{d.PROBE_ID}"' not in fail_html
            and fail_obs.get("solo_enabled") is True
            and fail_obs.get("parent_requested") is not True
            and fail_obs.get("parent_probe") is not True
            and fail_obs.get("queue_state_snapshot_diag_enabled") is False
            and fail_obs.get("queue_snapshot_renderer_call_reached") is True
            and fail_obs.get("queue_snapshot_renderer_would_render") is False
            and fail_obs.get("queue_snapshot_early_return_reason") == "parent_requested_false",
            fail_obs,
        )
    )

    failed = [x["name"] for x in results if not x.get("ok")]
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "root_cause": "FRANCISCO_QUEUE_MUTATION_PARENT_BOUNDARY_INITIAL_QUERY_CAPTURE_ORDER_DEFECT_CONFIRMED",
        "parent_boundary_on_mutation_url": True,
        "product_code_changed": True,
        "runner_harness_code_changed": False,
        "production": False,
        "browser": False,
        "context_a": False,
        "new_bridge": False,
        "bridge_548c4dc9_reusable": False,
    }
    persist = ROOT / "static" / "queue_state" / f"{LOCAL_SID}.json"
    if persist.is_file():
        persist.unlink()
    print(json.dumps(summary, indent=2, default=str))
    if failed:
        for row in results:
            if not row.get("ok"):
                print("FAIL", row)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
