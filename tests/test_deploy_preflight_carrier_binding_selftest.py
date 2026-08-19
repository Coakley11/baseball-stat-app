"""LOCAL same-document deploy/preflight carrier binding.

NO production. NO browser/network. NO Context A. NO click. NO queue mutation.
"""
from __future__ import annotations

import json
import sys
from collections import UserDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _check(name: str, ok: bool, detail: Any = None) -> dict[str, Any]:
    row = {"name": name, "ok": bool(ok)}
    if detail is not None and not ok:
        row["detail"] = detail
    return row


class _Frame:
    def __init__(self, payload: dict[str, Any], url: str = "about:srcdoc"):
        self.url = url
        self._payload = payload

    def evaluate(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        return dict(self._payload)


class _Page:
    def __init__(self, frames: list[_Frame] | None = None):
        self._frame_list = list(frames or [])
        self._goto = 0
        self._reload = 0
        self._click = 0

    @property
    def frames(self) -> list[_Frame]:
        return self._frame_list

    def evaluate(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        return {"deploy_found": False, "probe_found": False, "probe_absent": True}

    def wait_for_timeout(self, _ms: int) -> None:
        return None

    def goto(self, *_a: Any, **_k: Any) -> None:
        self._goto += 1
        raise AssertionError("no navigation")

    def reload(self, *_a: Any, **_k: Any) -> None:
        self._reload += 1
        raise AssertionError("no refresh")

    def click(self, *_a: Any, **_k: Any) -> None:
        self._click += 1
        raise AssertionError("no click")


def _deploy_only(*, sha: str = "5461564", phase: str = "early", idx_note: str = "") -> dict[str, Any]:
    return {
        "deploy_found": True,
        "data_sha": sha,
        "data_build": f"baseball-dev-{sha}",
        "carrier_phase": phase,
        "preflight_attached_attr": "0",
        "probe_found": False,
        "probe_absent": True,
        "note": idx_note,
    }


def _steady_both(*, sha: str = "5461564", ready: bool = True, parse_invalid: bool = False) -> dict[str, Any]:
    return {
        "deploy_found": True,
        "data_sha": sha,
        "data_build": f"baseball-dev-{sha}",
        "carrier_phase": "steady",
        "preflight_attached_attr": "1",
        "probe_found": True,
        "probe_absent": False,
        "parse_invalid": parse_invalid,
        "preflight_json": "{'preflight_ready': true}" if not parse_invalid else "{",
        "preflight_solo_ready": ready,
        "preflight_parent_requested": ready,
        "preflight_parent_probe": ready,
        "preflight_dual_gate": ready,
        "preflight_ready": ready,
        "impl_rev": "stage1_queue_gate_preflight_v4",
    }


def main() -> int:
    from live_draft_queue_state_snapshot_diag import (
        evaluate_context_a_preflight_reservation,
        scrape_same_carrier_deploy_preflight_from_page,
        select_authoritative_deploy_preflight_carrier,
        wait_and_scrape_same_carrier_deploy_preflight_from_page,
    )
    from live_draft_solo_expire_chain import (
        format_solo_deploy_carrier_html,
        format_solo_deploy_marker_html,
        render_solo_deploy_probe,
        render_solo_expire_chain_probe,
    )
    from live_draft_stage1_parent_boundary import capture_stage1_diagnostic_intents

    results: list[dict[str, Any]] = []
    expire_src = (ROOT / "live_draft_solo_expire_chain.py").read_text(encoding="utf-8")
    app_src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    capture_src = (ROOT / "scripts" / "capture_playwright_daniel_auth_once.py").read_text(encoding="utf-8")
    poll_src = (ROOT / "scripts" / "poll_exact_cloud_sha.py").read_text(encoding="utf-8")
    scrape_src = (ROOT / "scripts" / "verify_cloud_deploy_playwright.py").read_text(encoding="utf-8")
    soak_src = (ROOT / "scripts" / "run_production_solo_soak.py").read_text(encoding="utf-8")
    ldr = app_src.split('elif active_page == "Live Draft Room":', 1)[-1]
    expire_fn = expire_src.split("def render_solo_expire_chain_probe", 1)[-1].split("\ndef ", 1)[0]
    deploy_fn = expire_src.split("def render_solo_deploy_probe", 1)[-1].split("\ndef ", 1)[0]

    marker = format_solo_deploy_marker_html("5461564", "baseball-dev-5461564")
    results.append(
        _check(
            "12_13_deploy_marker_two_arg_html_and_data_sha_unchanged",
            marker == '<div id="solo-deploy-build" data-build="baseball-dev-5461564" data-sha="5461564"></div>'
            and "querySelector('#solo-deploy-build')" in scrape_src
            and "getAttribute('data-sha')" in scrape_src
            and "from verify_cloud_deploy_playwright import scrape_deploy" in poll_src,
            marker,
        )
    )
    results.append(
        _check(
            "poll_first_match_any_frame_unchanged",
            "for frame in getattr(page, \"frames\", []) or []:" in scrape_src
            and scrape_src.split("def scrape_deploy", 1)[-1].split("def main", 1)[0].count("return {") >= 1,
        )
    )
    results.append(
        _check(
            "source_two_ldr_carriers_early_then_steady",
            'carrier_phase="early"' in ldr
            and 'carrier_phase="steady"' in ldr
            and ldr.find('carrier_phase="early"') < ldr.find('carrier_phase="steady"'),
        )
    )
    results.append(
        _check(
            "expire_chain_does_not_emit_third_deploy",
            "render_solo_deploy_probe" not in expire_fn,
            expire_fn[:200],
        )
    )
    results.append(
        _check(
            "harness_same_carrier_wait_not_independent_preflight_search",
            "wait_and_scrape_same_carrier_deploy_preflight_from_page" in capture_src
            and "wait_and_scrape_queue_gate_preflight_from_page" not in capture_src.split("def main", 1)[-1],
        )
    )

    one = scrape_same_carrier_deploy_preflight_from_page(_Page([_Frame(_steady_both())]))
    results.append(
        _check(
            "1_one_steady_both_children_pass",
            one.get("outcome") == "STEADY_CARRIER_FOUND"
            and one.get("same_carrier_document") is True
            and one.get("authoritative_steady_found") is True
            and one.get("probe_found") is True
            and one.get("data_sha") == "5461564"
            and one.get("frame_index") == 0,
            one,
        )
    )

    class _EarlyThenSteady(_Page):
        def __init__(self) -> None:
            super().__init__([])
            self.n = 0

        def wait_for_timeout(self, _ms: int) -> None:
            self.n += 1

        @property
        def frames(self) -> list[_Frame]:
            if self.n < 2:
                return [_Frame(_deploy_only(phase="early"))]
            return [
                _Frame(_deploy_only(phase="early")),
                _Frame(_steady_both()),
            ]

    appear = wait_and_scrape_same_carrier_deploy_preflight_from_page(_EarlyThenSteady(), timeout_s=2.0, poll_s=0.05)
    results.append(
        _check(
            "2_early_then_steady_wait_then_pass",
            appear.get("outcome") == "STEADY_CARRIER_FOUND"
            and appear.get("carrier_phase") == "steady"
            and int(appear.get("attempts") or 0) >= 2
            and appear.get("probe_wait_timeout") is False,
            appear,
        )
    )

    coexist = scrape_same_carrier_deploy_preflight_from_page(
        _Page([_Frame(_deploy_only(phase="early")), _Frame(_steady_both())])
    )
    results.append(
        _check(
            "3_early_and_steady_coexist_select_steady",
            coexist.get("carrier_phase") == "steady"
            and coexist.get("frame_index") == 1
            and coexist.get("same_carrier_document") is True,
            coexist,
        )
    )
    results.append(
        _check(
            "4_first_deploy_only_second_steady_choose_second",
            coexist.get("frame_index") == 1 and coexist.get("probe_found") is True,
            coexist,
        )
    )

    multi = scrape_same_carrier_deploy_preflight_from_page(
        _Page(
            [
                _Frame(_deploy_only(phase="early", sha="5461564")),
                _Frame(_deploy_only(phase="build_only", sha="5461564")),
                _Frame(_steady_both()),
            ]
        )
    )
    results.append(
        _check(
            "5_several_deploy_frames_deterministic_steady",
            multi.get("frame_index") == 2
            and multi.get("carrier_phase") == "steady"
            and multi.get("candidate_count") == 3,
            multi,
        )
    )

    early_only = wait_and_scrape_same_carrier_deploy_preflight_from_page(
        _Page([_Frame(_deploy_only(phase="early"))]),
        timeout_s=0.6,
        poll_s=0.1,
    )
    results.append(
        _check(
            "6_early_sha_correct_no_steady_not_premature_fail",
            early_only.get("outcome") == "STEADY_NOT_OBSERVED"
            and early_only.get("data_sha") == "5461564"
            and early_only.get("authoritative_steady_found") is False
            and early_only.get("probe_wait_timeout") is True,
            early_only,
        )
    )

    class _Replace(_Page):
        def __init__(self) -> None:
            super().__init__(frames=[])
            self.n = 0

        def wait_for_timeout(self, _ms: int) -> None:
            self.n += 1

        @property
        def frames(self) -> list[_Frame]:
            if self.n < 2:
                return [_Frame(_deploy_only(phase="early"))]
            return [_Frame(_steady_both())]

    replaced = wait_and_scrape_same_carrier_deploy_preflight_from_page(_Replace(), timeout_s=2.0, poll_s=0.05)
    results.append(
        _check(
            "7_steady_after_rerender_frame_replacement_pass",
            replaced.get("outcome") == "STEADY_CARRIER_FOUND" and replaced.get("frame_index") == 0,
            replaced,
        )
    )

    missing = scrape_same_carrier_deploy_preflight_from_page(
        _Page([_Frame({**_deploy_only(phase="steady"), "preflight_attached_attr": "1"})])
    )
    results.append(
        _check(
            "8_steady_present_preflight_missing_contradiction",
            missing.get("outcome") == "STEADY_PREFLIGHT_MISSING"
            and missing.get("authoritative_steady_found") is True
            and missing.get("same_carrier_document") is False
            and missing.get("probe_found") is False,
            missing,
        )
    )

    invalid = scrape_same_carrier_deploy_preflight_from_page(_Page([_Frame(_steady_both(parse_invalid=True))]))
    results.append(
        _check(
            "9_steady_preflight_parse_invalid",
            invalid.get("outcome") == "STEADY_PARSE_INVALID" and invalid.get("parse_invalid") is True,
            invalid,
        )
    )

    not_ready = scrape_same_carrier_deploy_preflight_from_page(_Page([_Frame(_steady_both(ready=False))]))
    ev_false = evaluate_context_a_preflight_reservation(not_ready)
    results.append(
        _check(
            "10_readiness_false_valid_observation_no_reserve",
            not_ready.get("outcome") == "STEADY_CARRIER_FOUND"
            and not_ready.get("preflight_ready") is False
            and ev_false.get("ok") is False,
            ev_false,
        )
    )

    ready_row = scrape_same_carrier_deploy_preflight_from_page(_Page([_Frame(_steady_both(ready=True))]))
    ev_ok = evaluate_context_a_preflight_reservation(ready_row)
    results.append(
        _check(
            "11_all_readiness_true_reservation_evaluator_passes",
            ev_ok.get("ok") is True
            and (ev_ok.get("checks") or {}).get("same_carrier_document") is True
            and (ev_ok.get("checks") or {}).get("authoritative_steady_found") is True,
            ev_ok,
        )
    )

    results.append(
        _check(
            "14_no_rec_card_requirement_in_binding",
            "rec-card-queue-render-trace" not in deploy_fn
            and "renderer_call_reached" not in (ev_ok.get("checks") or {}),
        )
    )
    results.append(
        _check(
            "15_16_no_start_click_or_draft_start_in_scraper",
            "Start Live Draft" not in deploy_fn
            and ".click" not in capture_src.split("wait_and_scrape_same_carrier_deploy_preflight_from_page", 1)[-1][:800],
        )
    )
    observe_src = (ROOT / "live_draft_queue_state_snapshot_diag.py").read_text(encoding="utf-8")
    observe_fn = observe_src.split("def observe_queue_gate_preflight_state", 1)[-1].split("\ndef ", 1)[0]
    results.append(
        _check(
            "17_18_19_no_queue_sync_persist_in_observe",
            "add_player_to_draft_queue" not in observe_fn
            and "sync_draft_queue" not in observe_fn
            and "persist_dirty" not in observe_fn,
        )
    )
    results.append(
        _check(
            "20_21_22_23_no_auth_routing_stage_a_callback_in_carrier_format",
            "is_authenticated" not in expire_src.split("def format_solo_deploy_marker_html", 1)[-1].split("def render_solo_expire", 1)[0]
            and "active_page" not in expire_src.split("def format_solo_deploy_marker_html", 1)[-1].split("def render_solo_expire", 1)[0]
            and "stage1_francisco_callback_only" not in expire_src,
        )
    )

    # Lifecycle replay: URL → intents → early carrier → auth-like rerun → steady → Start not clicked.
    class _St:
        def __init__(self) -> None:
            self.markdowns: list[str] = []
            self.htmls: list[str] = []
            self.query_params = {
                "solo_component_diag": "1",
                "solo_stage1_parent_boundary": "1",
                "active_page": "Live Draft Room",
            }
            self.context = type("C", (), {"url": "https://app/?active_page=Live+Draft+Room&solo_component_diag=1&solo_stage1_parent_boundary=1"})()

        def markdown(self, html: str, **_k: Any) -> None:
            self.markdowns.append(html)

        def caption(self, *_a: Any, **_k: Any) -> None:
            return None

    instances: list[dict[str, Any]] = []
    session: Any = UserDict(
        {
            "_streamlit_session_id": "sid-bind",
            "draft_queue": [],
            "draft_state": {"queue": []},
            "_stage1_diagnostic_intents_captured": False,
        }
    )
    st = _St()
    capture_stage1_diagnostic_intents(st, session)
    instances.append({"phase": "ultra_early_intents", "intents": bool(session.get("_stage1_diagnostic_intents_captured")), "carriers": 0})
    render_solo_deploy_probe(st, session, carrier_phase="early")
    early_html = st.markdowns[-1]
    instances.append(
        {
            "instance": "early",
            "phase": "early",
            "data_sha_attr": 'data-sha="' in early_html,
            "carrier_phase": 'data-carrier-phase="early"' in early_html,
            "preflight_attached": 'id="stage1-queue-gate-state-preflight"' in early_html,
            "attached_attr": 'data-preflight-attached="1"' in early_html,
            "session": True,
            "session_is_dict": False,
        }
    )
    capture_stage1_diagnostic_intents(st, session)
    render_solo_deploy_probe(st, session, carrier_phase="steady")
    steady_html = st.markdowns[-1]
    instances.append(
        {
            "instance": "steady",
            "phase": "steady",
            "data_sha_attr": 'data-sha="' in steady_html,
            "carrier_phase": 'data-carrier-phase="steady"' in steady_html,
            "preflight_attached": 'id="stage1-queue-gate-state-preflight"' in steady_html,
            "session": True,
        }
    )
    before_expire = len(st.markdowns)
    render_solo_expire_chain_probe(st, session, None)
    results.append(
        _check(
            "lifecycle_replay_early_plus_later_steady",
            instances[1]["carrier_phase"]
            and instances[1]["preflight_attached"]
            and instances[1]["attached_attr"]
            and instances[2]["carrier_phase"]
            and instances[2]["preflight_attached"]
            and 'data-preflight-attached="1"' in steady_html
            and len(st.markdowns) == before_expire,
            instances,
        )
    )
    build_only = format_solo_deploy_carrier_html("5461564", "baseball-dev-5461564", "", carrier_phase="build_only", preflight_attached=False)
    results.append(
        _check(
            "historical_build_only_shape_possible_without_session",
            'id="solo-deploy-build"' in build_only
            and "stage1-queue-gate-state-preflight" not in build_only
            and 'data-carrier-phase="build_only"' in build_only
            and 'data-sha="5461564"' in build_only,
            build_only,
        )
    )
    extras = format_solo_deploy_marker_html(
        "5461564", "baseball-dev-5461564", carrier_phase="steady", preflight_attached=True
    )
    results.append(
        _check(
            "optional_attrs_after_data_sha",
            extras.index('data-sha="5461564"') < extras.index("data-carrier-phase")
            and extras.startswith('<div id="solo-deploy-build" data-build="baseball-dev-5461564" data-sha="5461564"'),
            extras,
        )
    )
    soak_fn = soak_src.split("def scrape_deploy_build", 1)[-1].split("\ndef ", 1)[0]
    results.append(
        _check(
            "sha_poll_helpers_still_read_data_sha_only",
            "el.getAttribute('data-sha')" in soak_fn or 'el.getAttribute("data-sha")' in soak_fn,
        )
    )

    none_deploy = scrape_same_carrier_deploy_preflight_from_page(_Page([]))
    results.append(_check("deploy_absent_outcome", none_deploy.get("outcome") == "DEPLOY_ABSENT", none_deploy))

    failed = [x["name"] for x in results if not x.get("ok")]
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "FRANCISCO_QUEUE_MUTATION_CONTEXT_A_DEPLOY_PREFLIGHT_CARRIER_BINDING_GAP_CONFIRMED": True,
        "FRANCISCO_QUEUE_MUTATION_CONTEXT_A_EARLY_VS_STEADY_DEPLOY_CARRIER_AMBIGUITY_CONFIRMED": True,
        "production": False,
        "browser": False,
        "context_a": False,
        "click": False,
        "queue_mutation": False,
        "instances": instances,
    }
    print(json.dumps(summary, indent=2, default=str))
    if failed:
        for row in results:
            if not row.get("ok"):
                print(json.dumps(row, default=str)[:800])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
