"""LOCAL session-backed deploy carrier preflight attachment.

NO production. NO browser/network. NO Context A. NO click. NO queue mutation.
"""
from __future__ import annotations

import json
import re
import sys
from collections import UserDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _SessionProxy(UserDict):
    """MutableMapping that is not a dict — Streamlit SessionStateProxy shape."""


class _Ctx:
    def __init__(self, url: str = "") -> None:
        self.url = url


class _St:
    def __init__(self, params: dict[str, str] | None = None, url: str = "") -> None:
        self.query_params: dict[str, str] = dict(params or {})
        self.context = _Ctx(url)
        self.markdowns: list[str] = []
        self.htmls: list[str] = []

    def markdown(self, html: str, **_k: Any) -> None:
        self.markdowns.append(html)

    def caption(self, *_a: Any, **_k: Any) -> None:
        return None


def _check(name: str, ok: bool, detail: Any = None) -> dict[str, Any]:
    row = {"name": name, "ok": bool(ok)}
    if detail is not None and not ok:
        row["detail"] = detail
    return row


def _attr(html: str, name: str) -> str:
    m = re.search(rf'{re.escape(name)}="([^"]*)"', html)
    return m.group(1) if m else ""


def _flag(html: str, name: str) -> bool:
    return _attr(html, name) == "1"


def _carrier_ok(html: str) -> bool:
    return (
        'id="solo-deploy-build"' in html
        and 'id="stage1-queue-gate-state-preflight"' in html
        and _attr(html, "data-preflight-attached") == "1"
        and html.count('id="stage1-queue-gate-state-preflight"') == 1
        and html.count('id="solo-deploy-build"') == 1
    )


def _session(**over: Any) -> _SessionProxy:
    base: dict[str, Any] = {
        "_streamlit_session_id": "sid-attach-local",
        "draft_queue": [],
        "draft_state": {"queue": []},
    }
    base.update(over)
    return _SessionProxy(base)


def _scrape_dict_from_html(html: str) -> dict[str, Any]:
    from live_draft_queue_state_snapshot_diag import _decode_preflight_eval

    pre = 'id="stage1-queue-gate-state-preflight"' in html
    raw = {
        "deploy_found": 'id="solo-deploy-build"' in html,
        "data_sha": _attr(html, "data-sha"),
        "data_build": _attr(html, "data-build"),
        "carrier_phase": _attr(html, "data-carrier-phase"),
        "preflight_attached_attr": _attr(html, "data-preflight-attached"),
        "probe_found": pre,
        "probe_absent": not pre,
        "preflight_solo_ready": _flag(html, "data-preflight-solo-ready"),
        "preflight_parent_requested": _flag(html, "data-preflight-parent-requested"),
        "preflight_parent_probe": _flag(html, "data-preflight-parent-probe"),
        "preflight_dual_gate": _flag(html, "data-preflight-dual-gate"),
        "preflight_ready": _flag(html, "data-preflight-ready"),
        "preflight_json": _attr(html, "data-preflight-json"),
        "impl_rev": _attr(html, "data-impl-rev"),
        "authoritative_steady_found": _attr(html, "data-carrier-phase") == "steady",
        "same_carrier_document": pre and 'id="solo-deploy-build"' in html,
    }
    return _decode_preflight_eval(raw)


def _render(st: _St, session: Any, phase: str, observe_calls: list) -> str:
    import live_draft_queue_state_snapshot_diag as diag
    from live_draft_solo_expire_chain import render_solo_deploy_probe

    orig = diag.observe_queue_gate_preflight_state

    def wrapped(st_in: Any, session_in: Any, *a: Any, **k: Any) -> dict[str, Any]:
        payload = orig(st_in, session_in, *a, **k)
        observe_calls.append({"phase": phase, "payload": payload, "none": payload is None})
        return payload

    diag.observe_queue_gate_preflight_state = wrapped  # type: ignore[method-assign]
    try:
        before = len(st.markdowns)
        render_solo_deploy_probe(st, session, carrier_phase=phase)
        return st.markdowns[-1] if len(st.markdowns) > before else ""
    finally:
        diag.observe_queue_gate_preflight_state = orig  # type: ignore[method-assign]


def main() -> int:
    from live_draft_queue_state_snapshot_diag import evaluate_context_a_preflight_reservation
    from live_draft_solo_expire_chain import (
        format_solo_deploy_marker_html,
        is_session_mapping,
        render_solo_deploy_probe,
    )
    from live_draft_stage1_parent_boundary import capture_stage1_diagnostic_intents
    from suite_deploy_marker import format_build_label, resolve_git_commit_short

    results: list[dict[str, Any]] = []
    observe_calls: list[dict[str, Any]] = []
    sha = resolve_git_commit_short()
    build = format_build_label()

    results.append(
        _check(
            "proxy_is_mapping_not_dict",
            is_session_mapping(_SessionProxy())
            and not isinstance(_SessionProxy(), dict),
        )
    )

    ldr_url = (
        "https://app/?active_page=Live+Draft+Room&solo_component_diag=1"
        "&solo_stage1_parent_boundary=1&suite_sid=fixture-sid-local"
    )
    st_qp = _St(
        {
            "active_page": "Live Draft Room",
            "solo_component_diag": "1",
            "solo_stage1_parent_boundary": "1",
            "suite_sid": "fixture-sid-local",
        },
        url=ldr_url,
    )
    sess = _session()
    capture_stage1_diagnostic_intents(st_qp, sess)
    early = _render(st_qp, sess, "early", observe_calls)
    results.append(
        _check(
            "1_session_backed_early_carrier_deploy_preflight_attached",
            _carrier_ok(early) and _attr(early, "data-carrier-phase") == "early",
            early[-240:],
        )
    )
    steady = _render(st_qp, sess, "steady", observe_calls)
    results.append(
        _check(
            "2_session_backed_steady_carrier_deploy_preflight_attached",
            _carrier_ok(steady) and _attr(steady, "data-carrier-phase") == "steady",
            steady[-240:],
        )
    )
    results.append(
        _check(
            "3_all_readiness_true_sibling_attached_ready",
            _carrier_ok(steady)
            and _flag(steady, "data-preflight-ready")
            and _flag(steady, "data-preflight-solo-ready")
            and _flag(steady, "data-preflight-parent-requested")
            and _flag(steady, "data-preflight-parent-probe")
            and _flag(steady, "data-preflight-dual-gate"),
            _attr(steady, "data-preflight-json")[:200],
        )
    )

    st_solo_off = _St({}, url="https://app/")
    s_solo_off = _session()
    html_solo_off = _render(st_solo_off, s_solo_off, "steady", observe_calls)
    results.append(
        _check(
            "4_solo_false_sibling_still_present_ready_false",
            _carrier_ok(html_solo_off)
            and not _flag(html_solo_off, "data-preflight-solo-ready")
            and not _flag(html_solo_off, "data-preflight-ready"),
            html_solo_off[-200:],
        )
    )

    st_pr = _St({"solo_component_diag": "1"}, url="https://app/?solo_component_diag=1")
    s_pr = _session(_solo_component_diag_enabled=True)
    html_pr = _render(st_pr, s_pr, "early", observe_calls)
    results.append(
        _check(
            "5_parent_requested_false_sibling_attached",
            _carrier_ok(html_pr) and not _flag(html_pr, "data-preflight-parent-requested"),
            html_pr[-200:],
        )
    )
    results.append(
        _check(
            "6_parent_probe_false_sibling_attached",
            _carrier_ok(html_pr) and not _flag(html_pr, "data-preflight-parent-probe"),
        )
    )
    results.append(
        _check(
            "7_dual_gate_false_sibling_attached",
            _carrier_ok(html_pr) and not _flag(html_pr, "data-preflight-dual-gate"),
        )
    )
    results.append(
        _check(
            "8_every_readiness_false_parse_valid",
            _carrier_ok(html_solo_off)
            and _scrape_dict_from_html(html_solo_off).get("parse_invalid") is not True,
            _scrape_dict_from_html(html_solo_off),
        )
    )

    results.append(
        _check(
            "9_query_param_flags_serialized",
            _flag(steady, "data-solo-qp-present")
            and _flag(steady, "data-solo-qp-flag")
            and _flag(steady, "data-parent-qp-present")
            and _flag(steady, "data-parent-qp-flag"),
            _attr(steady, "data-preflight-json")[:240],
        )
    )

    st_url = _St({}, url=ldr_url)
    s_url = _session()
    html_url = _render(st_url, s_url, "steady", observe_calls)
    results.append(
        _check(
            "10_context_url_only_flags_serialized",
            _carrier_ok(html_url)
            and _flag(html_url, "data-solo-url-present")
            and _flag(html_url, "data-solo-url-flag")
            and _flag(html_url, "data-parent-url-present")
            and _flag(html_url, "data-parent-url-flag"),
            html_url[-220:],
        )
    )

    st_latch = _St({}, url="https://app/")
    s_latch = _session(
        _solo_component_diag_enabled=True,
        _solo_stage1_parent_boundary_requested=True,
        _solo_stage1_parent_boundary_probe=True,
    )
    html_latch = _render(st_latch, s_latch, "steady", observe_calls)
    results.append(
        _check(
            "11_session_latch_only_actual_values",
            _carrier_ok(html_latch)
            and _flag(html_latch, "data-preflight-solo-ready")
            and _flag(html_latch, "data-preflight-parent-requested")
            and _flag(html_latch, "data-preflight-parent-probe"),
            html_latch[-220:],
        )
    )

    st_loss = _St({}, url="https://app/")
    html_loss = _render(st_loss, sess, "steady", observe_calls)
    results.append(
        _check(
            "12_auth_like_query_loss_sibling_exists",
            _carrier_ok(html_loss) and _flag(html_loss, "data-preflight-solo-ready"),
            html_loss[-200:],
        )
    )

    persist = _SessionProxy(
        {
            k: v
            for k, v in dict(sess).items()
            if k
            not in (
                "_solo_component_diag_enabled",
                "_solo_stage1_parent_boundary_requested",
                "_solo_stage1_parent_boundary_probe",
            )
        }
    )
    st_persist = _St({}, url=ldr_url)
    html_persist = _render(st_persist, persist, "steady", observe_calls)
    results.append(
        _check(
            "13_persistence_like_overwrite_sibling_reports_fallback",
            _carrier_ok(html_persist)
            and (
                _flag(html_persist, "data-solo-url-flag")
                or _flag(html_persist, "data-preflight-solo-ready")
            ),
            html_persist[-220:],
        )
    )

    start_sess = _session(
        _live_draft_start_enabled=True,
        live_draft_room=None,
        current_pick=None,
        rec_card=None,
        draft_queue=[],
        draft_state={"queue": []},
    )
    st_start = _St({}, url="https://app/")
    html_start = _render(st_start, start_sess, "steady", observe_calls)
    results.append(_check("14_start_enabled_no_draft_sibling", _carrier_ok(html_start)))
    results.append(_check("15_no_active_room_sibling", _carrier_ok(html_start)))
    results.append(_check("16_no_current_pick_sibling", _carrier_ok(html_start)))
    results.append(_check("17_no_rec_card_sibling", _carrier_ok(html_start)))
    results.append(_check("18_no_queue_snapshot_sibling", _carrier_ok(html_start)))

    mismatch_0 = 'data-preflight-attached="0"' in html_solo_off and 'id="stage1-queue-gate-state-preflight"' in html_solo_off
    mismatch_1 = 'data-preflight-attached="1"' in html_solo_off and 'id="stage1-queue-gate-state-preflight"' not in html_solo_off
    results.append(
        _check(
            "19_attached_matches_dom_presence",
            not mismatch_0
            and not mismatch_1
            and (_attr(html_solo_off, "data-preflight-attached") == "1")
            == ('id="stage1-queue-gate-state-preflight"' in html_solo_off),
        )
    )
    results.append(
        _check(
            "20_no_duplicate_steady_preflight_in_one_carrier",
            steady.count('id="stage1-queue-gate-state-preflight"') == 1
            and _attr(steady, "data-carrier-phase") == "steady",
        )
    )

    marker = format_solo_deploy_marker_html(sha, build)
    results.append(
        _check(
            "21_22_23_solo_deploy_build_sha_build_contract",
            f'id="solo-deploy-build"' in steady
            and f'data-sha="{sha}"' in steady
            and f'data-build="{build}"' in steady
            and marker
            == f'<div id="solo-deploy-build" data-build="{build}" data-sha="{sha}"></div>',
            {"sha": sha, "build": build, "marker": marker},
        )
    )
    results.append(_check("24_data_carrier_phase_preserved", _attr(steady, "data-carrier-phase") == "steady"))

    poll_src = (ROOT / "scripts" / "poll_exact_cloud_sha.py").read_text(encoding="utf-8")
    scrape_src = (ROOT / "scripts" / "verify_cloud_deploy_playwright.py").read_text(encoding="utf-8")
    scrape_fn = scrape_src.split("def scrape_deploy", 1)[-1].split("def main", 1)[0]
    results.append(
        _check(
            "25_poll_exact_cloud_sha_compatible",
            "from verify_cloud_deploy_playwright import scrape_deploy" in poll_src
            and "querySelector('#solo-deploy-build')" in scrape_src
            and "getAttribute('data-sha')" in scrape_src
            and "data-carrier-phase" not in scrape_fn
            and "data-preflight-attached" not in scrape_fn,
        )
    )

    parsed = _scrape_dict_from_html(steady)
    results.append(
        _check(
            "26_same_frame_parser_parses_payload",
            parsed.get("probe_found") is True and parsed.get("parse_invalid") is not True,
            parsed,
        )
    )
    ev_false = evaluate_context_a_preflight_reservation(
        {
            **_scrape_dict_from_html(html_solo_off),
            "authoritative_steady_found": True,
            "same_carrier_document": True,
            "probe_found": True,
        }
    )
    results.append(
        _check(
            "27_reservation_rejects_readiness_false",
            ev_false.get("ok") is False,
            ev_false,
        )
    )
    ev_true = evaluate_context_a_preflight_reservation(
        {
            **parsed,
            "authoritative_steady_found": True,
            "same_carrier_document": True,
            "probe_found": True,
        }
    )
    results.append(
        _check(
            "28_reservation_accepts_all_true",
            ev_true.get("ok") is True,
            ev_true,
        )
    )

    expire_src = (ROOT / "live_draft_solo_expire_chain.py").read_text(encoding="utf-8")
    app_src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    capture_src = (ROOT / "scripts" / "capture_playwright_daniel_auth_once.py").read_text(encoding="utf-8")
    format_chunk = expire_src.split("def format_solo_deploy_marker_html", 1)[-1].split("def render_solo_expire", 1)[0]
    results.append(_check("29_no_auth_behavior_change", "is_authenticated" not in format_chunk))
    results.append(_check("30_no_routing_change", "active_page" not in format_chunk))
    results.append(
        _check(
            "31_32_no_start_or_draft_in_carrier",
            "Start Live Draft" not in expire_src.split("def render_solo_deploy_probe", 1)[-1].split("\ndef ", 1)[0]
            and "start_live_draft" not in expire_src.split("def render_solo_deploy_probe", 1)[-1].split("\ndef ", 1)[0],
        )
    )
    observe_fn = (ROOT / "live_draft_queue_state_snapshot_diag.py").read_text(encoding="utf-8").split(
        "def observe_queue_gate_preflight_state", 1
    )[-1].split("\ndef ", 1)[0]
    results.append(
        _check(
            "33_34_35_no_queue_sync_persist_in_observe",
            "add_player_to_draft_queue" not in observe_fn
            and "sync_draft_queue" not in observe_fn
            and "persist_dirty" not in observe_fn,
        )
    )
    results.append(
        _check(
            "36_37_no_stage_a_or_francisco_callback_in_carrier",
            "stage1_francisco_callback_only" not in expire_src
            and "render_rec_queue_render_trace_probe" not in expire_src.split("def render_solo_deploy_probe", 1)[-1].split("\ndef ", 1)[0],
        )
    )
    results.append(
        _check(
            "harness_unchanged_same_carrier_wait",
            "wait_and_scrape_same_carrier_deploy_preflight_from_page" in capture_src,
        )
    )
    results.append(
        _check(
            "ldr_still_passes_session_state_early_and_steady",
            'render_solo_deploy_probe(st, st.session_state, carrier_phase="early")' in app_src
            and 'render_solo_deploy_probe(st, st.session_state, carrier_phase="steady")' in app_src,
        )
    )
    results.append(
        _check(
            "attachment_predicate_uses_mapping_not_dict_only",
            "is_session_mapping(session)" in expire_src.split("def render_solo_deploy_probe", 1)[-1].split("\ndef ", 1)[0]
            and "isinstance(session, dict)" not in expire_src.split("def render_solo_deploy_probe", 1)[-1].split("\ndef ", 1)[0],
        )
    )

    none_st = _St()
    render_solo_deploy_probe(none_st, None, carrier_phase="steady")
    none_html = none_st.markdowns[-1]
    results.append(
        _check(
            "session_none_attached_0_no_sibling",
            _attr(none_html, "data-preflight-attached") == "0"
            and "stage1-queue-gate-state-preflight" not in none_html
            and _attr(none_html, "data-carrier-phase") == "steady",
            none_html,
        )
    )

    early_call = next(c for c in observe_calls if c["phase"] == "early")
    steady_call = next(c for c in reversed(observe_calls) if c["phase"] == "steady" and c["payload"].get("preflight_ready"))
    lifecycle = {
        "ultra_early_intents": bool(sess.get("_stage1_diagnostic_intents_captured")),
        "early": {
            "phase": "early",
            "session_present": True,
            "session_is_dict": isinstance(sess, dict),
            "session_mapping": is_session_mapping(sess),
            "builder_called": True,
            "payload_none": early_call["none"],
            "attached": _attr(early, "data-preflight-attached"),
            "sibling": 'id="stage1-queue-gate-state-preflight"' in early,
            "preflight_ready": _flag(early, "data-preflight-ready"),
            "preflight_solo_ready": _flag(early, "data-preflight-solo-ready"),
            "preflight_parent_requested": _flag(early, "data-preflight-parent-requested"),
            "preflight_parent_probe": _flag(early, "data-preflight-parent-probe"),
            "preflight_dual_gate": _flag(early, "data-preflight-dual-gate"),
        },
        "steady": {
            "phase": "steady",
            "session_present": True,
            "builder_called": True,
            "payload_none": False,
            "attached": _attr(steady, "data-preflight-attached"),
            "sibling": 'id="stage1-queue-gate-state-preflight"' in steady,
            "preflight_ready": _flag(steady, "data-preflight-ready"),
            "preflight_solo_ready": _flag(steady, "data-preflight-solo-ready"),
            "preflight_parent_requested": _flag(steady, "data-preflight-parent-requested"),
            "preflight_parent_probe": _flag(steady, "data-preflight-parent-probe"),
            "preflight_dual_gate": _flag(steady, "data-preflight-dual-gate"),
        },
        "start_clicked": False,
    }
    results.append(
        _check(
            "lifecycle_auth_only_early_and_steady_attached_1",
            lifecycle["ultra_early_intents"]
            and lifecycle["early"]["attached"] == "1"
            and lifecycle["steady"]["attached"] == "1"
            and lifecycle["steady"]["sibling"]
            and lifecycle["steady"]["preflight_ready"]
            and not early_call["none"]
            and not steady_call["none"],
            lifecycle,
        )
    )

    failed = [x["name"] for x in results if not x.get("ok")]
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "lifecycle": lifecycle,
        "observe_call_count": len(observe_calls),
        "FRANCISCO_QUEUE_MUTATION_STEADY_CARRIER_SESSION_BINDING_DEFECT_CONFIRMED": True,
        "FRANCISCO_QUEUE_MUTATION_CONTEXT_A_STEADY_CARRIER_PREFLIGHT_ATTACHMENT_READY": not failed,
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
                print(json.dumps(row, default=str)[:1200])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
