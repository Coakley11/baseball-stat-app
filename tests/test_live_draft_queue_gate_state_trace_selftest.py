"""LOCAL live queue-gate-state observability on #rec-card-queue-render-trace.

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


def _check(name: str, ok: bool, detail: Any = None) -> dict[str, Any]:
    row = {"name": name, "ok": bool(ok)}
    if detail is not None and not ok:
        row["detail"] = detail
    return row


def _session(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "_streamlit_session_id": "sid-gate-obs-local",
        "draft_queue": [],
        "draft_state": {"queue": []},
        "live_draft_room": {"draft_room_id": "228B3378", "current_pick_index": 0},
        "_solo_stage1_script_run_seq": 19,
        "_solo_stage1_recommendation_fragment_run_seq": 2,
        "_solo_stage1_last_recommendation_paint": {"via": "fragment_interactive_live"},
        "_live_draft_heavy_paint_done": True,
    }
    base.update(over)
    return base


def _register_card(session: dict[str, Any]) -> None:
    from live_draft_rec_queue_click_trace import register_rec_queue_render_trace

    register_rec_queue_render_trace(
        session,
        room_id="228B3378",
        pick_index=0,
        player_id="231",
        player_name="Francisco Lindor",
        widget_key="rec_card_queue_228B3378_0_231_rec_card",
    )


def _emit_pair(st: _St, session: dict[str, Any]) -> tuple[str, str]:
    from live_draft_queue_state_snapshot_diag import render_queue_state_snapshot_probe
    from live_draft_rec_queue_click_trace import render_rec_queue_render_trace_probe

    _register_card(session)
    render_rec_queue_render_trace_probe(st, session)
    rec_html = st.last_md or ""
    render_queue_state_snapshot_probe(st, session)
    snap_html = st.last_md or ""
    return rec_html, snap_html


def _no_secrets(blob: Any) -> bool:
    text = json.dumps(blob, default=str).lower() if not isinstance(blob, str) else blob.lower()
    return not any(s in text for s in SECRET_FRAGMENTS)


def main() -> int:
    from live_draft_queue_state_snapshot_diag import (
        PROBE_ID,
        classify_queue_snapshot_early_return_reason,
        observe_queue_snapshot_gate_state,
        queue_state_snapshot_diag_enabled,
        render_queue_state_snapshot_probe,
    )
    from live_draft_rec_queue_click_trace import (
        RENDER_TRACE_PROBE_ELEMENT_ID,
        evaluate_context_a_live_queue_gate_reservation,
        scrape_rec_card_queue_gate_state_from_page,
        wait_and_scrape_rec_card_queue_gate_state_from_page,
        render_rec_queue_render_trace_probe,
    )
    from live_draft_stage1_parent_boundary import capture_stage1_diagnostic_intents

    results: list[dict[str, Any]] = []

    # A. query_params contains both flags
    s_a = _session()
    st_a = _St({"solo_component_diag": "1", "solo_stage1_parent_boundary": "1"})
    capture_stage1_diagnostic_intents(st_a, s_a)
    rec_a, snap_a = _emit_pair(st_a, s_a)
    obs_a = s_a.get("_stage1_queue_snapshot_gate_obs") or {}
    results.append(
        _check(
            "A_qp_both_flags_gate_true",
            s_a.get("_solo_stage1_parent_boundary_requested") is True
            and s_a.get("_solo_stage1_parent_boundary_probe") is True
            and obs_a.get("queue_state_snapshot_diag_enabled") is True
            and obs_a.get("queue_snapshot_early_return_reason") == "enabled"
            and f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_a
            and f'id="{PROBE_ID}"' in snap_a,
            obs_a,
        )
    )

    # B. query_params omits parent, context.url has parent=1
    s_b = _session()
    st_b = _St(
        {"solo_component_diag": "1"},
        url="https://app/?solo_component_diag=1&solo_stage1_parent_boundary=1",
    )
    capture_stage1_diagnostic_intents(st_b, s_b)
    rec_b, snap_b = _emit_pair(st_b, s_b)
    obs_b = s_b.get("_stage1_queue_snapshot_gate_obs") or {}
    results.append(
        _check(
            "B_url_only_parent_latches_and_emits",
            s_b.get("_solo_stage1_parent_boundary_requested") is True
            and s_b.get("_solo_stage1_parent_boundary_probe") is True
            and obs_b.get("parent_qp_flag") is False
            and obs_b.get("parent_url_flag") is True
            and obs_b.get("queue_state_snapshot_diag_enabled") is True
            and f'id="{PROBE_ID}"' in snap_b
            and f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_b,
            obs_b,
        )
    )

    # C. both query_params and context.url lose parent before capture
    s_c = _session()
    st_c = _St({}, url="https://app/?active_page=Live+Draft+Room")
    capture_stage1_diagnostic_intents(st_c, s_c)
    s_c["_solo_component_diag_enabled"] = True
    rec_c, snap_c = _emit_pair(st_c, s_c)
    obs_c = s_c.get("_stage1_queue_snapshot_gate_obs") or {}
    results.append(
        _check(
            "C_missing_parent_gate_false_trace_explains",
            s_c.get("_solo_stage1_parent_boundary_requested") is not True
            and s_c.get("_solo_stage1_parent_boundary_probe") is not True
            and obs_c.get("queue_state_snapshot_diag_enabled") is False
            and obs_c.get("queue_snapshot_early_return_reason") == "parent_requested_false"
            and f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_c
            and f'id="{PROBE_ID}"' not in rec_c
            and f'id="{PROBE_ID}"' not in snap_c,
            obs_c,
        )
    )

    # D. requested=true but solo=false — probe waits; rec-card hidden (solo-only)
    s_d = _session()
    s_d["_solo_stage1_parent_boundary_requested"] = True
    st_d = _St({})
    obs_d = observe_queue_snapshot_gate_state(st_d, s_d, renderer_call_reached=True)
    _register_card(s_d)
    render_rec_queue_render_trace_probe(st_d, s_d)
    results.append(
        _check(
            "D_requested_true_solo_false_probe_waits",
            s_d.get("_solo_stage1_parent_boundary_requested") is True
            and s_d.get("_solo_stage1_parent_boundary_probe") is not True
            and obs_d.get("queue_snapshot_early_return_reason") == "solo_disabled"
            and not st_d.markdowns,
            obs_d,
        )
    )

    # E. solo later becomes true → parent probe promotes → gate true
    s_d["_solo_component_diag_enabled"] = True
    obs_e = observe_queue_snapshot_gate_state(st_d, s_d, renderer_call_reached=True)
    results.append(
        _check(
            "E_solo_later_promotes_parent_probe",
            s_d.get("_solo_stage1_parent_boundary_probe") is True
            and obs_e.get("queue_state_snapshot_diag_enabled") is True
            and obs_e.get("queue_snapshot_early_return_reason") == "enabled",
            obs_e,
        )
    )

    # F. fragment rerun empty QP/URL with session latches true → gate remains
    s_f = _session(
        _solo_component_diag_enabled=True,
        _solo_stage1_parent_boundary_requested=True,
        _solo_stage1_parent_boundary_probe=True,
    )
    st_f = _St({}, url="https://app/")
    rec_f, snap_f = _emit_pair(st_f, s_f)
    obs_f = s_f.get("_stage1_queue_snapshot_gate_obs") or {}
    results.append(
        _check(
            "F_fragment_empty_qp_retains_latches",
            obs_f.get("queue_state_snapshot_diag_enabled") is True
            and obs_f.get("queue_snapshot_early_return_reason") == "enabled"
            and f'id="{PROBE_ID}"' in snap_f
            and "fragment_interactive_live" in rec_f,
            obs_f,
        )
    )

    # G. fragment rerun solo true, parent latches false
    s_g = _session(_solo_component_diag_enabled=True)
    st_g = _St({}, url="https://app/")
    rec_g, snap_g = _emit_pair(st_g, s_g)
    obs_g = s_g.get("_stage1_queue_snapshot_gate_obs") or {}
    results.append(
        _check(
            "G_solo_true_parent_false_trace_visible_snapshot_absent",
            f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_g
            and f'id="{PROBE_ID}"' not in snap_g
            and obs_g.get("solo_enabled") is True
            and obs_g.get("parent_requested") is not True
            and obs_g.get("parent_probe") is not True
            and obs_g.get("queue_state_snapshot_diag_enabled") is False
            and obs_g.get("queue_snapshot_early_return_reason") == "parent_requested_false"
            and 'data-queue-renderer-reached="1"' in rec_g,
            obs_g,
        )
    )

    # H. renderer call reached, gate=false
    results.append(
        _check(
            "H_renderer_reached_early_return_reason",
            obs_g.get("queue_snapshot_renderer_call_reached") is True
            and obs_g.get("queue_snapshot_renderer_would_render") is False
            and obs_g.get("queue_snapshot_early_return_reason") == "parent_requested_false"
            and 'data-queue-early-return-reason="parent_requested_false"' in rec_g,
        )
    )

    # I. renderer reached, gate=true → baseline probe
    results.append(
        _check(
            "I_gate_true_emits_baseline_probe",
            obs_a.get("queue_snapshot_renderer_would_render") is True
            and f'id="{PROBE_ID}"' in snap_a
            and "QUEUE_STATE_BASELINE" in snap_a
            and s_a["_stage1_queue_state_snapshot_baseline"]["session_queue"] == []
            and s_a["_stage1_queue_state_snapshot_baseline"]["canonical_queue"] == [],
        )
    )

    # Required field coverage + no secrets
    required_attrs = (
        "data-sid=",
        "data-paint-via=",
        "data-solo-qp-present=",
        "data-solo-enabled=",
        "data-parent-qp-present=",
        "data-parent-url-present=",
        "data-parent-requested=",
        "data-parent-probe=",
        "data-queue-gate=",
        "data-queue-renderer-reached=",
        "data-queue-would-render=",
        "data-queue-early-return-reason=",
    )
    results.append(_check("trace_contains_all_gate_fields", all(a in rec_g for a in required_attrs), rec_g[:500]))
    results.append(_check("no_secrets_in_obs", _no_secrets(obs_g) and _no_secrets(rec_g)))
    results.append(
        _check(
            "parent_qp_and_url_reported_independently",
            obs_b.get("parent_qp_present") is False
            and obs_b.get("parent_url_present") is True
            and 'data-parent-url-present="1"' in rec_b,
            obs_b,
        )
    )
    results.append(
        _check(
            "trace_visible_solo_only_parent_false",
            f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_g
            and f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_c,
        )
    )
    results.append(
        _check(
            "trace_visible_when_parent_true",
            f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_a
            and f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_f,
        )
    )
    results.append(
        _check(
            "gate_false_does_not_hide_sibling",
            f'id="{RENDER_TRACE_PROBE_ELEMENT_ID}"' in rec_g
            and obs_g.get("queue_state_snapshot_diag_enabled") is False,
        )
    )
    results.append(
        _check(
            "empty_queues_still_valid_when_emitted",
            s_a["_stage1_queue_state_snapshot_baseline"]["session_queue"] == []
            and s_a["_stage1_queue_state_snapshot_baseline"]["canonical_queue"] == []
            and s_a["_stage1_queue_state_snapshot_baseline"]["queues_equal"] is True,
        )
    )
    results.append(
        _check(
            "pick_0_unchanged",
            s_g["live_draft_room"]["current_pick_index"] == 0
            and s_a["live_draft_room"]["current_pick_index"] == 0,
        )
    )
    results.append(
        _check(
            "no_queue_mutation_or_persist",
            s_g.get("draft_queue") == []
            and s_g.get("draft_state", {}).get("queue") == []
            and s_a.get("draft_queue") == [],
        )
    )
    results.append(
        _check(
            "reason_classifier_first_failing",
            classify_queue_snapshot_early_return_reason(
                renderer_call_reached=False,
                gate_enabled=False,
                solo_enabled=True,
                parent_requested=False,
                parent_probe=False,
                parent_qp_present=False,
                parent_url_present=False,
            )
            == "renderer_not_called"
            and classify_queue_snapshot_early_return_reason(
                renderer_call_reached=True,
                gate_enabled=True,
                solo_enabled=True,
                parent_requested=True,
                parent_probe=True,
                parent_qp_present=True,
                parent_url_present=False,
            )
            == "enabled"
            and classify_queue_snapshot_early_return_reason(
                renderer_call_reached=True,
                gate_enabled=False,
                solo_enabled=True,
                parent_requested=True,
                parent_probe=False,
                parent_qp_present=False,
                parent_url_present=False,
            )
            == "parent_probe_false",
        )
    )

    class _Frame:
        def __init__(self, result, url="https://app/~/+/"):
            self.url = url
            self._result = result

        def evaluate(self, *_a, **_k):
            return self._result

    class _Page:
        def __init__(self, frames):
            self.frames = frames

        def evaluate(self, *_a, **_k):
            return {"probe_found": False, "probe_absent": True}

    page = _Page(
        [
            _Frame({"probe_found": False, "probe_absent": True}),
            _Frame(
                {
                    "probe_found": True,
                    "solo_enabled": True,
                    "parent_requested": False,
                    "queue_gate": False,
                    "early_return_reason": "parent_requested_false",
                }
            ),
        ]
    )
    scraped = scrape_rec_card_queue_gate_state_from_page(page)
    results.append(
        _check(
            "scraper_uses_page_frames",
            scraped.get("probe_found") is True
            and scraped.get("frame_index") == 1
            and scraped.get("frame_strategy") == "page.frames"
            and scraped.get("early_return_reason") == "parent_requested_false",
            scraped,
        )
    )

    rec_src = (ROOT / "live_draft_rec_queue_click_trace.py").read_text(encoding="utf-8")
    room_src = (ROOT / "live_draft_room_ui.py").read_text(encoding="utf-8")
    heavy_src = (ROOT / "live_draft_heavy_paint_ui.py").read_text(encoding="utf-8")
    rec_fn = room_src.split("def render_live_draft_rec_cards", 1)[-1].split("\ndef ", 1)[0]
    results.append(
        _check(
            "callsite_rec_card_then_queue_probe",
            "render_rec_queue_render_trace_probe" in rec_fn
            and "render_queue_state_snapshot_probe" in rec_fn
            and rec_fn.find("render_rec_queue_render_trace_probe")
            < rec_fn.find("render_queue_state_snapshot_probe")
            and "render_queue_state_snapshot_probe" in heavy_src,
        )
    )
    results.append(
        _check(
            "telemetry_not_behind_parent_gate",
            "observe_queue_snapshot_gate_state" in rec_src
            and "queue_state_snapshot_diag_enabled" not in rec_src.split("def _render_trace_diag_enabled", 1)[-1][:500],
        )
    )
    # Tighten: rec-card enable is solo-only
    results.append(
        _check(
            "rec_card_enable_is_solo_only",
            "solo_component_diag_enabled" in rec_src.split("def _render_trace_diag_enabled", 1)[-1][:400]
            and "solo_stage1_parent_boundary" not in rec_src.split("def _render_trace_diag_enabled", 1)[-1][:400],
        )
    )

    app_src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    parent_src = (ROOT / "live_draft_stage1_parent_boundary.py").read_text(encoding="utf-8")
    cloud_src = (ROOT / "live_draft_cloud_diagnostics.py").read_text(encoding="utf-8")
    solo_src = (ROOT / "live_draft_solo_component_diagnostics.py").read_text(encoding="utf-8")
    after_config = app_src.split("st.set_page_config", 1)[-1]
    results.append(
        _check(
            "early_capture_still_after_set_page_config",
            after_config.find("capture_stage1_diagnostic_intents")
            < after_config.find("enable_delivery_diag_from_query"),
        )
    )
    results.append(
        _check(
            "early_capture_from_solo_bootstrap_and_ldr",
            "capture_stage1_diagnostic_intents" in solo_src.split("def bootstrap_solo_component_diag", 1)[-1][:500]
            and app_src.count("capture_stage1_diagnostic_intents") >= 2,
        )
    )
    results.append(
        _check(
            "qp_get_still_falls_back_to_context_url",
            "return _qp_from_context_url(st, name)" in cloud_src
            and "def capture_stage1_diagnostic_intents" in parent_src,
        )
    )
    diag_src = (ROOT / "live_draft_queue_state_snapshot_diag.py").read_text(encoding="utf-8")
    record_part = diag_src.split("def record_queue_state_post_mutation_snapshot")[0]
    results.append(
        _check(
            "observe_has_no_queue_writes",
            "add_player_to_draft_queue" not in record_part
            and "q.append" not in record_part
            and "sync_draft_queue" not in record_part
            and "write_canonical_draft_state" not in record_part,
        )
    )

    # --- Context-A live gate extractor: bounded wait + frames (harness-only) ---
    good_gate = {
        "probe_found": True,
        "probe_absent": False,
        "solo_enabled": True,
        "parent_requested": True,
        "parent_probe": True,
        "queue_gate": True,
        "renderer_call_reached": True,
        "would_render": True,
        "early_return_reason": "enabled",
        "impl_rev": "rec_queue_render_trace_v5_queue_gate",
        "queue_gate_json": "",
    }
    stale_invalid = {
        "probe_found": True,
        "probe_absent": False,
        "solo_enabled": True,
        "parent_requested": True,
        "parent_probe": True,
        "queue_gate": True,
        "renderer_call_reached": True,
        "would_render": True,
        "early_return_reason": "enabled",
        "impl_rev": "rec_queue_render_trace_v5_queue_gate",
        "queue_gate_json": "{not-json",
    }

    class _GateFrame:
        def __init__(self, result, url="https://app/~/+/"):
            self.url = url
            self._result = result

        def evaluate(self, *_a, **_k):
            return self._result if not callable(self._result) else self._result()

    class _GatePage:
        def __init__(self, frames, top=None):
            self.frames = frames
            self._top = top if top is not None else {"probe_found": False, "probe_absent": True}
            self.navigated = False
            self.goto_calls = 0
            self.reload_calls = 0
            self.click_calls = 0
            self.evaluate_urls: list[str] = []

        def evaluate(self, *_a, **_k):
            return self._top if not callable(self._top) else self._top()

        def wait_for_timeout(self, _ms):
            return None

        def goto(self, *_a, **_k):
            self.goto_calls += 1
            self.navigated = True

        def reload(self, *_a, **_k):
            self.reload_calls += 1
            self.navigated = True

        def click(self, *_a, **_k):
            self.click_calls += 1

    main_hit = scrape_rec_card_queue_gate_state_from_page(
        _GatePage(frames=[_GateFrame(good_gate, url="https://streamlit.app/")])
    )
    results.append(
        _check(
            "ex1_main_frame_immediate",
            main_hit.get("probe_found") is True
            and main_hit.get("frame_strategy") == "page.frames"
            and main_hit.get("frame_index") == 0
            and main_hit.get("parent_requested") is True,
            main_hit,
        )
    )

    child_hit = scrape_rec_card_queue_gate_state_from_page(
        _GatePage(
            frames=[
                _GateFrame({"probe_found": False, "probe_absent": True}, url="https://streamlit.app/"),
                _GateFrame(good_gate, url="https://app/~/+/"),
            ],
            top={"probe_found": False, "probe_absent": True},
        )
    )
    results.append(
        _check(
            "ex2_child_frame_immediate",
            child_hit.get("probe_found") is True
            and child_hit.get("frame_index") == 1
            and child_hit.get("frame_strategy") == "page.frames",
            child_hit,
        )
    )

    srcdoc_hit = scrape_rec_card_queue_gate_state_from_page(
        _GatePage(
            frames=[
                _GateFrame({"probe_found": False}, url="https://streamlit.app/"),
                _GateFrame(good_gate, url="about:srcdoc"),
            ]
        )
    )
    results.append(
        _check(
            "ex3_about_srcdoc_frame",
            srcdoc_hit.get("probe_found") is True
            and srcdoc_hit.get("frame_url") == "about:srcdoc"
            and srcdoc_hit.get("frame_strategy") == "page.frames",
            srcdoc_hit,
        )
    )

    appear_seq = {"i": 0, "rows": [{"probe_found": False}, {"probe_found": False}, good_gate]}

    class _AppearPage(_GatePage):
        def __init__(self):
            super().__init__(frames=[])

        def evaluate(self, *_a, **_k):
            i = appear_seq["i"]
            appear_seq["i"] += 1
            return appear_seq["rows"][i] if i < len(appear_seq["rows"]) else appear_seq["rows"][-1]

    appear = wait_and_scrape_rec_card_queue_gate_state_from_page(_AppearPage(), timeout_s=2.0, poll_s=0.05)
    results.append(
        _check(
            "ex4_absent_then_appears",
            appear.get("probe_found") is True
            and int(appear.get("attempts") or 0) >= 3
            and appear.get("waited_for_probe") is True
            and appear.get("probe_wait_timeout") is False,
            appear,
        )
    )

    repl_seq = [{"probe_found": False}, good_gate]
    repl_i = {"n": 0}

    class _ReplFrame:
        url = "https://app/~/+/"

        def evaluate(self, *_a, **_k):
            n = repl_i["n"]
            repl_i["n"] += 1
            return repl_seq[n] if n < len(repl_seq) else repl_seq[-1]

    repl_page = _GatePage(frames=[_ReplFrame()])
    repl = wait_and_scrape_rec_card_queue_gate_state_from_page(repl_page, timeout_s=2.0, poll_s=0.05)
    results.append(
        _check(
            "ex5_frame_replaced_before_trace",
            repl.get("probe_found") is True and repl.get("frame_strategy") == "page.frames",
            repl,
        )
    )

    parse_seq = {"i": 0, "rows": [stale_invalid, good_gate]}

    class _ParseThenValidPage(_GatePage):
        def __init__(self):
            super().__init__(frames=[])

        def evaluate(self, *_a, **_k):
            i = parse_seq["i"]
            parse_seq["i"] += 1
            return parse_seq["rows"][i] if i < len(parse_seq["rows"]) else parse_seq["rows"][-1]

    parse_then = wait_and_scrape_rec_card_queue_gate_state_from_page(
        _ParseThenValidPage(), timeout_s=2.0, poll_s=0.05
    )
    results.append(
        _check(
            "ex6_unparseable_then_valid",
            parse_then.get("probe_found") is True
            and parse_then.get("parse_invalid") is not True
            and int(parse_then.get("attempts") or 0) >= 2,
            parse_then,
        )
    )

    absent = wait_and_scrape_rec_card_queue_gate_state_from_page(
        _GatePage(frames=[_GateFrame({"probe_found": False})]),
        timeout_s=0.6,
        poll_s=0.05,
    )
    results.append(
        _check(
            "ex7_permanently_absent_fail_closed",
            absent.get("probe_found") is False
            and absent.get("probe_absent") is True
            and absent.get("probe_wait_timeout") is True
            and int(absent.get("attempts") or 0) >= 2
            and "elapsed_s" in absent
            and absent.get("selector") == f"#{RENDER_TRACE_PROBE_ELEMENT_ID}",
            absent,
        )
    )

    bad_only = wait_and_scrape_rec_card_queue_gate_state_from_page(
        _GatePage(frames=[_GateFrame(stale_invalid)]),
        timeout_s=0.6,
        poll_s=0.05,
    )
    results.append(
        _check(
            "ex8_permanently_parse_invalid_distinct",
            bad_only.get("probe_found") is True
            and bad_only.get("parse_invalid") is True
            and bad_only.get("probe_absent") is False
            and bad_only.get("probe_wait_timeout") is True,
            bad_only,
        )
    )

    top_absent_child = scrape_rec_card_queue_gate_state_from_page(
        _GatePage(
            frames=[
                _GateFrame({"probe_found": False}, url="https://streamlit.app/"),
                _GateFrame(good_gate, url="https://app/~/+/"),
            ],
            top={"probe_found": False, "probe_absent": True},
        )
    )
    results.append(
        _check(
            "ex9_top_absent_child_valid",
            top_absent_child.get("probe_found") is True and top_absent_child.get("frame_index") == 1,
            top_absent_child,
        )
    )

    prefer_valid = scrape_rec_card_queue_gate_state_from_page(
        _GatePage(
            frames=[
                _GateFrame(stale_invalid, url="about:blank"),
                _GateFrame(good_gate, url="about:srcdoc"),
            ]
        )
    )
    results.append(
        _check(
            "ex10_stale_then_current_valid",
            prefer_valid.get("probe_found") is True
            and prefer_valid.get("parse_invalid") is not True
            and prefer_valid.get("frame_index") == 1
            and prefer_valid.get("frame_url") == "about:srcdoc",
            prefer_valid,
        )
    )

    side_effect_page = _GatePage(frames=[_GateFrame(good_gate)])
    wait_and_scrape_rec_card_queue_gate_state_from_page(side_effect_page, timeout_s=0.5, poll_s=0.05)
    results.append(
        _check(
            "ex11_16_no_nav_refresh_qp_browser_click_mutation",
            side_effect_page.goto_calls == 0
            and side_effect_page.reload_calls == 0
            and side_effect_page.click_calls == 0
            and side_effect_page.navigated is False,
        )
    )

    capture_src = (ROOT / "scripts" / "capture_playwright_daniel_auth_once.py").read_text(encoding="utf-8")
    capture_scrape = capture_src.split("rec_card_queue_gate", 1)[-1][:1200]
    results.append(
        _check(
            "ex18_19_wait_after_auth_boundary",
            "wait_and_scrape_queue_gate_preflight_from_page" in capture_src
            and "strict_auth_passed" in capture_src
            and capture_src.find("if not last_eval.get(\"strict_auth_passed\")")
            < capture_src.find("wait_and_scrape_queue_gate_preflight_from_page")
            and "page.goto" not in capture_scrape
            and "reload(" not in capture_scrape,
        )
    )
    results.append(
        _check(
            "ex_wait_helper_present",
            "def wait_and_scrape_rec_card_queue_gate_state_from_page" in rec_src
            and "page.frames" in rec_src
            and "contentDocument" in rec_src
            and "probe_wait_timeout" in rec_src,
        )
    )
    results.append(
        _check(
            "ex_context_a_reservation_uses_preflight_not_rec_card_wait",
            "wait_and_scrape_queue_gate_preflight_from_page" in capture_src
            and "wait_and_scrape_rec_card_queue_gate_state_from_page" not in capture_src.split("rec_card_queue_gate", 1)[-1][:1800],
        )
    )

    results.append(
        _check(
            "ex20_live_gate_fields_parse",
            all(
                k in main_hit
                for k in (
                    "solo_enabled",
                    "parent_requested",
                    "parent_probe",
                    "queue_gate",
                    "renderer_call_reached",
                    "would_render",
                    "early_return_reason",
                )
            ),
            main_hit,
        )
    )

    def _gate_eval(**over: Any) -> dict[str, Any]:
        base = dict(good_gate)
        base.update(over)
        return evaluate_context_a_live_queue_gate_reservation(base)

    results.append(
        _check(
            "ex21_parent_requested_false_gate_fail",
            _gate_eval(parent_requested=False).get("ok") is False
            and "parent_requested" in (_gate_eval(parent_requested=False).get("failing") or []),
        )
    )
    results.append(
        _check(
            "ex22_parent_probe_false_gate_fail",
            _gate_eval(parent_probe=False).get("ok") is False
            and "parent_probe" in (_gate_eval(parent_probe=False).get("failing") or []),
        )
    )
    results.append(
        _check(
            "ex23_queue_gate_false_gate_fail",
            _gate_eval(queue_gate=False).get("ok") is False
            and "queue_gate" in (_gate_eval(queue_gate=False).get("failing") or []),
        )
    )
    results.append(
        _check(
            "ex24_would_render_false_gate_fail",
            _gate_eval(would_render=False).get("ok") is False
            and "would_render" in (_gate_eval(would_render=False).get("failing") or []),
        )
    )
    enabled_ok = evaluate_context_a_live_queue_gate_reservation(good_gate)
    results.append(
        _check(
            "ex25_all_true_enabled_passes",
            enabled_ok.get("ok") is True and not (enabled_ok.get("failing") or []),
            enabled_ok,
        )
    )
    results.append(
        _check(
            "ex_trace_is_markdown_not_components_html",
            "st.markdown(" in rec_src.split("def render_rec_queue_render_trace_probe", 1)[-1].split("def ", 1)[0]
            and "components.html" not in rec_src.split("def render_rec_queue_render_trace_probe", 1)[-1].split("def ", 1)[0],
        )
    )
    results.append(
        _check(
            "ex_snapshot_dual_emit_vs_trace_markdown",
            "_emit_queue_state_probe_dom" in diag_src
            and "components.html" in diag_src.split("def _emit_queue_state_probe_dom", 1)[-1][:400],
        )
    )

    # Local 3cb-shaped replay: auth-boundary wait begins; absent then child-frame hit
    replay_i = {"n": 0}
    replay_rows = [
        {"probe_found": False, "probe_absent": True},
        {"probe_found": False, "probe_absent": True},
        good_gate,
    ]

    class _ReplayFrame:
        url = "about:srcdoc"

        def evaluate(self, *_a, **_k):
            n = replay_i["n"]
            replay_i["n"] += 1
            return replay_rows[n] if n < len(replay_rows) else replay_rows[-1]

    replay_page = _GatePage(
        frames=[
            _GateFrame({"probe_found": False}, url="https://streamlit.app/"),
            _ReplayFrame(),
        ],
        top={"probe_found": False, "probe_absent": True},
    )
    replay = wait_and_scrape_rec_card_queue_gate_state_from_page(replay_page, timeout_s=2.0, poll_s=0.05)
    results.append(
        _check(
            "ex_3cb_shape_delayed_child_frame",
            replay.get("probe_found") is True
            and replay.get("frame_strategy") == "page.frames"
            and int(replay.get("attempts") or 0) >= 3
            and replay_page.goto_calls == 0
            and replay_page.click_calls == 0,
            replay,
        )
    )
    permanent = wait_and_scrape_rec_card_queue_gate_state_from_page(
        _GatePage(frames=[_GateFrame({"probe_found": False})], top={"probe_found": False}),
        timeout_s=0.5,
        poll_s=0.05,
    )
    results.append(
        _check(
            "ex_3cb_shape_permanent_absence_not_observed",
            permanent.get("probe_found") is False
            and permanent.get("probe_wait_timeout") is True
            and permanent.get("probe_absent") is True,
            permanent,
        )
    )

    failed = [x["name"] for x in results if not x.get("ok")]
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "production": False,
        "browser": False,
        "context_a": False,
        "click": False,
        "queue_mutation": False,
        "labels": {
            "root_cause": "FRANCISCO_QUEUE_MUTATION_CONTEXT_A_GATE_TRACE_WAIT_DEFECT_CONFIRMED+FRANCISCO_QUEUE_MUTATION_CONTEXT_A_GATE_TRACE_PAINT_READINESS_DEFECT_CONFIRMED",
            "extractor_ready": "FRANCISCO_QUEUE_MUTATION_CONTEXT_A_LIVE_GATE_TRACE_EXTRACTOR_READY",
        },
    }
    print(json.dumps(summary, indent=2, default=str))
    if failed:
        for row in results:
            if not row.get("ok"):
                print("FAIL", row)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
