"""Deterministic LOCAL Cloud-execution wiring selftest for Francisco mutation proof.

NO Cloud. NO Playwright. NO network. NO production main against 709269b3.
NO real bridge consumption. Uses temp fixture markers only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
REAL_BRIDGE = "709269b3-a9bf-442e-8eac-37936f766caa"
FIXTURE_BRIDGE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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


def _write_reserved(path: Path, bridge: str) -> None:
    path.write_text(
        f"{bridge}\n# RESERVED for FRANCISCO NORMAL QUEUE-MUTATION PROOF ONLY\n# NOT consumed\n",
        encoding="utf-8",
    )


def _obs_ok(r) -> dict[str, Any]:
    """Force observability pass for orchestration path tests."""
    return {
        "ok": True,
        "canonical_queue_observable_without_latch": True,
        "session_queue_observable_without_latch": True,
        "classification": None,
        "gap_detail": None,
    }


def _run(
    r,
    tmp: Path,
    *,
    auth=None,
    runtime=None,
    stage_a=None,
    gate=None,
    baseline=None,
    post=None,
    launch=True,
    click_ok=True,
    require_obs=False,
    state=None,
    context_a_sid="context-a-sid-HISTORICAL",
    required_sha="95b26f9",
    capture_cloud_runtime_sha="d664924",
):
    marker = tmp / "fixture_reserved_bridge.txt"
    _write_reserved(marker, FIXTURE_BRIDGE)
    # Consumption writes a separate consumed path via ports; use marker as consume target.
    consume_path = tmp / "fixture_consumed_bridge.txt"
    st = state if state is not None else {}
    ports = r.build_fixture_mutation_ports(
        marker_path=consume_path,
        bridge_id=FIXTURE_BRIDGE,
        auth=auth,
        runtime=runtime,
        stage_a=stage_a,
        gate=gate,
        baseline=baseline,
        post=post,
        launch=launch,
        click_ok=click_ok,
        state=st,
        required_sha=required_sha,
    )
    url = r.build_francisco_mutation_proof_url(FIXTURE_BRIDGE)
    pre = r.evaluate_mutation_url_preflight(url)
    cfg = r.MutationCloudConfig(
        bridge_id=FIXTURE_BRIDGE,
        context_a_sid=context_a_sid,
        context_a_diagnostic_run_id="context-a-run-HISTORICAL",
        require_canonical_observability=require_obs,
        production_reexecuted=False,
        required_sha=required_sha,
        capture_cloud_runtime_sha=capture_cloud_runtime_sha,
    )
    report = r.run_cloud_mutation_orchestration(
        ports,
        cfg,
        url=url,
        preflight=pre,
        observability=_obs_ok(r) if not require_obs else r.assess_d664924_unlatched_queue_observability(),
    )
    report["_state"] = st
    report["_consume_path"] = str(consume_path)
    report["_reserved_fixture"] = str(marker)
    return report


def main() -> int:
    r = _load(RUNNER_PATH, "francisco_mutation_cloud_exec_selftest")
    results: list[dict[str, Any]] = []

    # 1. Cloud auth flag false -> abort pre-browser (main path)
    prev = os.environ.pop("FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD", None)
    os.environ["FRANCISCO_MUTATION_PROOF_BRIDGE_ID"] = FIXTURE_BRIDGE
    os.environ["STAGE1_BRIDGE_SUITE_SID"] = FIXTURE_BRIDGE
    # Avoid touching real marker: temporarily point by using missing reserved for fixture id
    code_buf: list[str] = []

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = r.main()
    out = buf.getvalue()
    payload = json.loads(out.strip().splitlines()[-1])
    results.append(
        _check(
            "1_cloud_auth_false_pre_browser",
            rc == 2
            and payload.get("classification") == r.CLASSIFICATION_CLOUD_NOT_AUTHORIZED
            and payload.get("browser_launched") is False
            and payload.get("bridge_consumed") is False,
            payload.get("classification"),
        )
    )
    if prev is not None:
        os.environ["FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD"] = prev
    else:
        os.environ.pop("FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD", None)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # 2. auth true + valid reserved (fixture orchestration eligible to launch)
        rep = _run(r, tmp)
        results.append(
            _check(
                "2_auth_true_valid_bridge_launches",
                rep.get("browser_launched") is True and int(rep.get("click_count") or 0) == 1,
            )
        )

        # 3. invalid bridge (retired) via main
        os.environ["FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD"] = "1"
        os.environ["REQUIRED_CLOUD_SHA"] = "95b26f9"
        os.environ["FRANCISCO_MUTATION_PROOF_BRIDGE_ID"] = r.RETIRED_BRIDGE_IDS[0]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = r.main()
        payload = json.loads(buf.getvalue().strip().splitlines()[-1])
        results.append(
            _check(
                "3_invalid_bridge_pre_browser",
                rc == 2
                and payload.get("classification") == r.CLASSIFICATION_BRIDGE_INVALID
                and payload.get("browser_launched") is not True,
                payload.get("classification"),
            )
        )

        # 4. pre-browser failure does not consume fixture bridge
        consume = tmp / "no_consume.txt"
        _write_reserved(tmp / "res.txt", FIXTURE_BRIDGE)
        ports = r.build_fixture_mutation_ports(
            marker_path=consume, bridge_id=FIXTURE_BRIDGE, launch=False, state={}
        )
        url = r.build_francisco_mutation_proof_url(FIXTURE_BRIDGE)
        rep = r.run_cloud_mutation_orchestration(
            ports,
            r.MutationCloudConfig(
                bridge_id=FIXTURE_BRIDGE,
                require_canonical_observability=False,
                required_sha="95b26f9",
            ),
            url=url,
            observability=_obs_ok(r),
        )
        results.append(
            _check(
                "4_pre_browser_fail_no_consume",
                rep.get("bridge_consumed") is False and not consume.is_file(),
            )
        )

        # 5. simulated browser boundary consumes fixture once
        consume2 = tmp / "consume_once.txt"
        st = {}
        ports = r.build_fixture_mutation_ports(
            marker_path=consume2, bridge_id=FIXTURE_BRIDGE, state=st
        )
        rep = r.run_cloud_mutation_orchestration(
            ports,
            r.MutationCloudConfig(
                bridge_id=FIXTURE_BRIDGE,
                require_canonical_observability=False,
                required_sha="95b26f9",
            ),
            url=url,
            observability=_obs_ok(r),
        )
        marker_eval = r.evaluate_reserved_bridge_marker(
            consume2.read_text(encoding="utf-8"), expected_bridge_id=FIXTURE_BRIDGE
        )
        results.append(
            _check(
                "5_browser_boundary_consumes_once",
                rep.get("bridge_consumed") is True
                and marker_eval.get("consumed") is True
                and st.get("consumed") is True,
            )
        )

        # 6. runtime mismatch -> no click
        st = {}
        rep = _run(
            r,
            tmp,
            runtime={"runtime_match": False, "runtime_sha_normalized": "deadbee"},
            state=st,
        )
        results.append(
            _check(
                "6_runtime_mismatch_no_click",
                rep.get("classification") == r.CLASSIFICATION_RUNTIME_MISMATCH
                and int(st.get("click_invocations") or 0) == 0,
            )
        )

        # 7. auth failure -> no click
        st = {}
        rep = _run(
            r,
            tmp,
            auth={"authenticated_restored": False, "restore_blocked_reason": "auth_failed"},
            state=st,
        )
        results.append(
            _check(
                "7_auth_fail_no_click",
                rep.get("classification") == r.CLASSIFICATION_AUTH_FAIL
                and int(st.get("click_invocations") or 0) == 0,
            )
        )

        # 8. production SID differs from Context A and is used
        rep = _run(r, tmp, context_a_sid="context-a-sid-HISTORICAL")
        results.append(
            _check(
                "8_production_sid_not_context_a",
                rep.get("production_sid_differs_from_context_a") is True
                and rep.get("production_streamlit_sid") == "prod-sid-fixture-0001"
                and rep.get("production_streamlit_sid") != "context-a-sid-HISTORICAL",
            )
        )

        # 9. Stage A fail -> no click
        st = {}
        rep = _run(r, tmp, stage_a={"steady_authorized": False}, state=st)
        results.append(
            _check(
                "9_stage_a_fail_no_click",
                rep.get("classification") == r.CLASSIFICATION_STAGE_A_FAIL
                and int(st.get("click_invocations") or 0) == 0,
            )
        )

        # 10. Stage A pass -> continue (membership success path)
        rep = _run(r, tmp)
        results.append(_check("10_stage_a_pass_continues", rep.get("ok") is True))

        # 11–14 URL / navigation safety
        url = r.build_francisco_mutation_proof_url(FIXTURE_BRIDGE)
        pre = r.evaluate_mutation_url_preflight(url)
        q = parse_qs(urlparse(url).query)
        results.append(_check("11_latch_count_0", pre.get("latch_count") == 0))
        results.append(_check("12_host_query_count_0", pre.get("host_query_probe_count") == 0))
        results.append(
            _check(
                "13_no_set_query_param",
                pre.get("set_query_param_required") is False
                and "SET_QUERY_PARAM" not in open(RUNNER_PATH, encoding="utf-8").read().split("def trusted_click")[0][-500:],
            )
        )
        results.append(
            _check(
                "14_no_second_navigation",
                pre.get("latch_page_goto_selected") is False
                and pre.get("gate_clear_selected") is False,
            )
        )

        # 15–17 gate
        g_ok = r.evaluate_gate_allows_normal_mutation(
            latch_absent=True, fresh_production_sid=True, gate_lifecycle="unarmed"
        )
        g_arm = r.evaluate_gate_allows_normal_mutation(
            latch_absent=True, fresh_production_sid=True, gate_lifecycle="armed"
        )
        g_lock = r.evaluate_gate_allows_normal_mutation(
            latch_absent=True, fresh_production_sid=True, gate_lifecycle="consumed_locked"
        )
        results.append(_check("15_gate_unarmed_eligible", g_ok.get("ok") is True))
        results.append(_check("16_gate_armed_reject", g_arm.get("ok") is False))
        results.append(_check("17_gate_consumed_locked_reject", g_lock.get("ok") is False))

        # 18–22 baseline
        b_eq = r.evaluate_queue_baseline(session_queue=["A"], canonical_queue=["A"])
        results.append(_check("18_baseline_equal_continue", b_eq.get("ok") is True))
        st = {}
        rep = _run(
            r,
            tmp,
            baseline={"canonical_unavailable": True, "session_queue": [], "canonical_queue": None},
            state=st,
        )
        results.append(
            _check(
                "19_canonical_unavailable_fail_closed",
                rep.get("classification") == r.CLASSIFICATION_PRODUCT_GAP
                and int(st.get("click_invocations") or 0) == 0,
            )
        )
        b_present = r.evaluate_queue_baseline(
            session_queue=["Francisco Lindor"], canonical_queue=["Francisco Lindor"]
        )
        results.append(_check("20_francisco_present_reject", b_present.get("ok") is False))
        b_empty = r.evaluate_queue_baseline(session_queue=[], canonical_queue=[])
        results.append(_check("21_empty_baseline_authorize", b_empty.get("ok") is True))
        b_ne = r.evaluate_queue_baseline(session_queue=["Aaron Judge"], canonical_queue=["Aaron Judge"])
        results.append(_check("22_nonempty_absent_authorize", b_ne.get("ok") is True))

        # 23–24 one click max + only after auth
        st = {}
        rep = _run(r, tmp, state=st)
        results.append(
            _check(
                "23_one_click_maximum",
                int(rep.get("click_count") or 0) == 1 and int(st.get("click_invocations") or 0) == 1,
            )
        )
        st = {}
        rep = _run(r, tmp, auth={"authenticated_restored": False}, state=st)
        results.append(
            _check(
                "24_click_only_after_authorization",
                int(st.get("click_invocations") or 0) == 0
                and rep.get("francisco_mutation_click_authorized") is False,
            )
        )

        # 25 unexpected STOP
        rep = _run(
            r,
            tmp,
            post={"premutation_stop_observed": True, "premutation_stop": {"phase": r.PHASE_STOP}},
        )
        results.append(
            _check(
                "25_unexpected_stop_fails",
                rep.get("classification") == r.CLASSIFICATION_STOP_UNEXPECTED,
            )
        )

        # 26 helper+added+exact +1
        rep = _run(
            r,
            tmp,
            baseline={"session_queue": ["A"], "canonical_queue": ["A"], "ui_queue": ["A"]},
            post={
                "mutation_helper_entered": True,
                "added": True,
                "session_queue": ["A", "Francisco Lindor"],
                "canonical_queue": ["A", "Francisco Lindor"],
                "ui_queue": ["A", "Francisco Lindor"],
                "queue_mutation_visible": True,
                "callback_entered": True,
                "callback_ledger_observed": True,
            },
        )
        results.append(
            _check(
                "26_helper_added_plus1_membership",
                rep.get("FRANCISCO_MEMBERSHIP_MUTATION_PROVEN") is True
                and rep.get("AUTHORITATIVE") == "yes",
            )
        )

        # 27 added=false
        rep = _run(r, tmp, post={"added": False, "mutation_helper_entered": True})
        results.append(
            _check(
                "27_added_false_fails",
                rep.get("ok") is False and "added_false" in str((rep.get("membership_detail") or {}).get("failures")),
            )
        )

        # 28 Francisco absent after
        rep = _run(
            r,
            tmp,
            post={
                "added": True,
                "mutation_helper_entered": True,
                "session_queue": [],
                "canonical_queue": [],
                "queue_mutation_visible": False,
            },
        )
        results.append(_check("28_francisco_absent_after_fails", rep.get("ok") is False))

        # 29 duplicate
        rep = _run(
            r,
            tmp,
            post={
                "added": True,
                "mutation_helper_entered": True,
                "session_queue": ["Francisco Lindor", "Francisco Lindor"],
                "canonical_queue": ["Francisco Lindor", "Francisco Lindor"],
            },
        )
        results.append(_check("29_duplicate_francisco_fails", rep.get("ok") is False))

        # 30 unrelated add
        rep = _run(
            r,
            tmp,
            baseline={"session_queue": [], "canonical_queue": []},
            post={
                "added": True,
                "mutation_helper_entered": True,
                "session_queue": ["Aaron Judge"],
                "canonical_queue": ["Aaron Judge"],
            },
        )
        results.append(_check("30_unrelated_add_fails", rep.get("ok") is False))

        # 31 baseline removal
        rep = _run(
            r,
            tmp,
            baseline={"session_queue": ["A", "B"], "canonical_queue": ["A", "B"]},
            post={
                "added": True,
                "mutation_helper_entered": True,
                "session_queue": ["A", "Francisco Lindor"],
                "canonical_queue": ["A", "Francisco Lindor"],
            },
        )
        results.append(_check("31_baseline_removal_fails", rep.get("ok") is False))

        # 32 canonical mismatch after
        rep = _run(
            r,
            tmp,
            post={
                "added": True,
                "mutation_helper_entered": True,
                "session_queue": ["Francisco Lindor"],
                "canonical_queue": [],
            },
        )
        results.append(_check("32_canonical_mismatch_after_fails", rep.get("ok") is False))

        # 33 ledger missing + substantive success
        rep = _run(
            r,
            tmp,
            post={
                "added": True,
                "mutation_helper_entered": True,
                "session_queue": ["Francisco Lindor"],
                "canonical_queue": ["Francisco Lindor"],
                "callback_ledger_observed": False,
                "callback_entered": True,
                "queue_mutation_visible": True,
            },
        )
        results.append(
            _check(
                "33_ledger_gap_membership_still_pass",
                rep.get("FRANCISCO_MEMBERSHIP_MUTATION_PROVEN") is True
                and rep.get("callback_ledger_observability_gap") is True,
            )
        )

        # 34 UI visible + callback/mutation -> PLAYER_A
        results.append(
            _check(
                "34_player_a_pass_when_visible",
                rep.get("PLAYER_A_QUEUE_MUTATION_RESOLVED") is True,
            )
        )

        # 35 UI missing + membership pass -> PLAYER_A unissued
        rep = _run(
            r,
            tmp,
            post={
                "added": True,
                "mutation_helper_entered": True,
                "session_queue": ["Francisco Lindor"],
                "canonical_queue": ["Francisco Lindor"],
                "callback_entered": True,
                "queue_mutation_visible": False,
                "callback_ledger_observed": True,
            },
        )
        results.append(
            _check(
                "35_membership_pass_player_a_unissued_without_ui",
                rep.get("FRANCISCO_MEMBERSHIP_MUTATION_PROVEN") is True
                and rep.get("PLAYER_A_QUEUE_MUTATION_RESOLVED") is False,
            )
        )

        # 36–37 no cleanup / no force-save
        src = RUNNER_PATH.read_text(encoding="utf-8")
        results.append(
            _check(
                "36_no_cleanup_remove",
                "remove_player_from_user_draft_queue" not in src
                and "cleanup_remove_selected" in src
                and "cleanup_remove_selected\": True" not in src.replace(" ", ""),
            )
        )
        results.append(
            _check(
                "37_no_force_save",
                "durable_flush_required" in src
                and "force_save_selected\": True" not in src.replace(" ", "")
                and "flush_draft_queue_persist" not in src,
            )
        )

        # 38–39 failure/success never second click
        st = {}
        _run(r, tmp, post={"added": False, "mutation_helper_entered": True}, state=st)
        results.append(_check("38_failure_no_second_click", int(st.get("click_invocations") or 0) <= 1))
        st = {}
        _run(r, tmp, state=st)
        results.append(_check("39_success_no_second_click", int(st.get("click_invocations") or 0) == 1))

        # 40 bridge permanently consumed after simulated boundary
        consume3 = tmp / "perm_consumed.txt"
        ports = r.build_fixture_mutation_ports(marker_path=consume3, bridge_id=FIXTURE_BRIDGE)
        r.run_cloud_mutation_orchestration(
            ports,
            r.MutationCloudConfig(
                bridge_id=FIXTURE_BRIDGE,
                require_canonical_observability=False,
                required_sha="95b26f9",
            ),
            url=url,
            observability=_obs_ok(r),
        )
        ev = r.evaluate_reserved_bridge_marker(
            consume3.read_text(encoding="utf-8"), expected_bridge_id=FIXTURE_BRIDGE
        )
        results.append(_check("40_bridge_permanently_consumed", ev.get("consumed") is True and ev.get("eligible") is False))

        # 41–44 labels not auto-issued / stage1b off
        rep = _run(r, tmp)
        results.append(_check("41_queue1c3a2f4_not_auto", rep.get("QUEUE1C3A2F4_RESOLVED") is False))
        results.append(_check("42_queue_seed_not_auto", rep.get("QUEUE_SEED_RESOLVED") is False))
        results.append(_check("43_stage1a_queue_pass_false", rep.get("stage_1a_queue_passed") is False))
        results.append(_check("44_stage_1b_disabled", rep.get("stage_1b") is False))

        # Product gap assessment — now expect READY (dual-queue diagnostic present)
        obs = r.assess_d664924_unlatched_queue_observability()
        results.append(
            _check(
                "45_product_gap_closed_canonical_observable",
                obs.get("ok") is True
                and obs.get("canonical_queue_observable_without_latch") is True
                and obs.get("session_queue_observable_without_latch") is True
                and obs.get("classification") is None,
            )
        )

        # Real 709269b3 permanently CONSUMED (production mutation attempt; do not reuse)
        real_marker = ROOT / "data" / "709269b3_reserved_bridge.txt"
        real_consumed = ROOT / "data" / "709269b3_consumed_bridge.txt"
        real_text = real_marker.read_text(encoding="utf-8") if real_marker.is_file() else ""
        real_g = r.evaluate_reserved_bridge_marker(real_text, expected_bridge_id=REAL_BRIDGE)
        results.append(
            _check(
                "46_real_709269b3_permanently_consumed",
                real_g.get("eligible") is False
                and real_g.get("consumed") is True
                and real_consumed.is_file()
                and ("CONSUMED" in real_text or "consumed" in real_text.lower()),
            )
        )

        # When require_obs uses real assess (now ok), orchestration may proceed under fixtures
        # with require_canonical_observability=True and forced ok observability.
        # Keep a dedicated fail-closed check via missing canonical in baseline collector.
        st = {}
        rep = _run(
            r,
            tmp,
            baseline={"canonical_unavailable": True, "session_queue": [], "canonical_queue": None},
            state=st,
            require_obs=False,
        )
        results.append(
            _check(
                "47_missing_canonical_still_fail_closed",
                rep.get("classification") == r.CLASSIFICATION_PRODUCT_GAP
                and int(st.get("click_invocations") or 0) == 0,
            )
        )

        # NOT_IMPLEMENTED removed
        results.append(
            _check(
                "48_not_implemented_abort_removed",
                "CLOUD_PATH_NOT_IMPLEMENTED_IN_THIS_TURN" not in src,
            )
        )

        # cloud authorize still required in main
        results.append(
            _check(
                "49_authorize_cloud_still_gated",
                "FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD" in src
                and "cloud_authorization_present" in src,
            )
        )

        # no latch in mutation URL builder
        results.append(
            _check(
                "50_url_builder_strips_latch",
                r.FRANCISCO_LATCH_PARAM not in url
                and "stage1_host_query_roundtrip_probe" not in url,
            )
        )

    failed = [x for x in results if not x.get("ok")]
    by = {x["name"]: x["ok"] for x in results}
    classifications = {
        "FRANCISCO_QUEUE_MUTATION_CLOUD_EXECUTION_PATH_RUNNER_READY": bool(
            by.get("48_not_implemented_abort_removed")
            and by.get("2_auth_true_valid_bridge_launches")
            and by.get("5_browser_boundary_consumes_once")
            and by.get("49_authorize_cloud_still_gated")
        ),
        "FRANCISCO_QUEUE_MUTATION_CLOUD_AUTH_STAGE_A_ORCHESTRATION_RUNNER_READY": bool(
            by.get("7_auth_fail_no_click")
            and by.get("8_production_sid_not_context_a")
            and by.get("9_stage_a_fail_no_click")
            and by.get("10_stage_a_pass_continues")
            and by.get("6_runtime_mismatch_no_click")
        ),
        "FRANCISCO_QUEUE_MUTATION_CLOUD_QUEUE_STATE_OBSERVABILITY_RUNNER_READY": bool(
            by.get("45_product_gap_closed_canonical_observable")
            and by.get("47_missing_canonical_still_fail_closed")
            and by.get("19_canonical_unavailable_fail_closed")
        ),
        "FRANCISCO_QUEUE_MUTATION_CLOUD_OBSERVABILITY_PRODUCT_GAP_CONFIRMED": False,
        "FRANCISCO_QUEUE_MUTATION_CLOUD_SINGLE_CLICK_EVIDENCE_PIPELINE_RUNNER_READY": bool(
            by.get("23_one_click_maximum")
            and by.get("26_helper_added_plus1_membership")
            and by.get("33_ledger_gap_membership_still_pass")
            and by.get("35_membership_pass_player_a_unissued_without_ui")
            and by.get("38_failure_no_second_click")
        ),
    }
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "classifications": classifications,
        "production_main_executed_against_cloud": False,
        "browser_network": False,
        "real_bridge_709269b3_consumed": bool(by.get("46_real_709269b3_permanently_consumed")),
        "real_bridge_709269b3_still_reserved": False,
        "francisco_click": False,
        "queue_mutation": False,
        "stage_1b": False,
    }
    print(json.dumps(summary, indent=2, default=str))
    # cleanup env
    os.environ.pop("FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD", None)
    os.environ.pop("FRANCISCO_MUTATION_PROOF_BRIDGE_ID", None)
    os.environ.pop("STAGE1_BRIDGE_SUITE_SID", None)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
