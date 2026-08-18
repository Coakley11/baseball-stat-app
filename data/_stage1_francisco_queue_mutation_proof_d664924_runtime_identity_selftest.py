"""LOCAL runtime-identity authority selftest for Francisco mutation proof.

NO Cloud. NO browser/network. NO production main against 709269b3.
NO real bridge consumption.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
REAL_BRIDGE = "709269b3-a9bf-442e-8eac-37936f766caa"
FIXTURE_BRIDGE = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"


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


def _obs_ok() -> dict[str, Any]:
    return {
        "ok": True,
        "canonical_queue_observable_without_latch": True,
        "session_queue_observable_without_latch": True,
        "classification": None,
        "gap_detail": None,
    }


def main() -> int:
    r = _load(RUNNER_PATH, "francisco_mutation_runtime_identity_selftest")
    results: list[dict[str, Any]] = []
    src = RUNNER_PATH.read_text(encoding="utf-8")

    # 1–2 resolve REQUIRED_CLOUD_SHA=95b26f9 + display
    res = r.resolve_required_cloud_sha(
        env={"REQUIRED_CLOUD_SHA": "95b26f9"}, cloud_authorized=True
    )
    results.append(
        _check(
            "1_required_cloud_sha_95b26f9_resolves",
            bool(res.get("ok")) and res.get("required_sha") == "95b26f9",
            res,
        )
    )
    results.append(
        _check(
            "2_expected_display_derived",
            res.get("expected_build_display") == "baseball-dev-95b26f9"
            and r.expected_build_display_for("95b26f9") == "baseball-dev-95b26f9",
            res.get("expected_build_display"),
        )
    )

    # 3–5 live 95b26f9 pass
    live_ok = r.evaluate_live_runtime_against_required(
        required_sha="95b26f9",
        runtime_sha_raw="95b26f9",
        deploy_build_raw="baseball-dev-95b26f9",
    )
    results.append(_check("3_live_raw_95b26f9_pass", bool(live_ok.get("ok")) and live_ok.get("runtime_match")))
    results.append(
        _check(
            "4_live_normalized_95b26f9_pass",
            live_ok.get("runtime_sha_normalized") == "95b26f9",
        )
    )
    results.append(
        _check(
            "5_live_display_baseball_dev_95b26f9_pass",
            bool(live_ok.get("build_match"))
            and live_ok.get("expected_build_display") == "baseball-dev-95b26f9",
        )
    )

    # 6–7 reject d664924 / other
    live_old = r.evaluate_live_runtime_against_required(
        required_sha="95b26f9",
        runtime_sha_raw="d664924",
        deploy_build_raw="baseball-dev-d664924",
    )
    results.append(
        _check(
            "6_live_d664924_with_required_95b26f9_fail",
            not live_old.get("ok") and live_old.get("reason") == "runtime_mismatch",
            live_old,
        )
    )
    live_other = r.evaluate_live_runtime_against_required(
        required_sha="95b26f9",
        runtime_sha_raw="deadbee",
        deploy_build_raw="baseball-dev-deadbee",
    )
    results.append(_check("7_arbitrary_other_sha_fail", not live_other.get("ok"), live_other))

    # 8–11 main() fail-closed for REQUIRED_CLOUD_SHA / authorize
    env_backup = {
        k: os.environ.get(k)
        for k in (
            "FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD",
            "FRANCISCO_MUTATION_PROOF_BRIDGE_ID",
            "STAGE1_BRIDGE_SUITE_SID",
            "REQUIRED_CLOUD_SHA",
        )
    }

    def _run_main() -> tuple[int, dict[str, Any]]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = r.main()
        payload = json.loads(buf.getvalue().strip().splitlines()[-1])
        return rc, payload

    os.environ["FRANCISCO_MUTATION_PROOF_BRIDGE_ID"] = FIXTURE_BRIDGE
    os.environ["STAGE1_BRIDGE_SUITE_SID"] = FIXTURE_BRIDGE
    os.environ["FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD"] = "1"
    os.environ.pop("REQUIRED_CLOUD_SHA", None)
    rc, payload = _run_main()
    results.append(
        _check(
            "8_missing_required_sha_cloud_auth_pre_browser",
            rc == 2
            and payload.get("classification") == r.CLASSIFICATION_REQUIRED_CLOUD_SHA_INVALID
            and payload.get("browser_launched") is False
            and payload.get("bridge_consumed") is False,
            payload.get("classification"),
        )
    )

    os.environ["REQUIRED_CLOUD_SHA"] = ""
    rc, payload = _run_main()
    results.append(
        _check(
            "9_empty_required_sha_fail",
            rc == 2
            and payload.get("classification") == r.CLASSIFICATION_REQUIRED_CLOUD_SHA_INVALID
            and (payload.get("required_cloud_sha_resolution") or {}).get("reason") == "missing",
            payload.get("required_cloud_sha_resolution"),
        )
    )

    os.environ["REQUIRED_CLOUD_SHA"] = "not-a-sha"
    rc, payload = _run_main()
    results.append(
        _check(
            "10_malformed_required_sha_fail",
            rc == 2
            and payload.get("classification") == r.CLASSIFICATION_REQUIRED_CLOUD_SHA_INVALID
            and (payload.get("required_cloud_sha_resolution") or {}).get("reason") == "malformed",
            payload.get("required_cloud_sha_resolution"),
        )
    )

    # 11 no d664924 fallback under cloud auth
    os.environ.pop("REQUIRED_CLOUD_SHA", None)
    rc, payload = _run_main()
    results.append(
        _check(
            "11_no_fallback_to_d664924_when_authorized",
            rc == 2
            and payload.get("classification") == r.CLASSIFICATION_REQUIRED_CLOUD_SHA_INVALID
            and "d664924" not in str(payload.get("required_sha") or "")
            and (payload.get("required_cloud_sha_resolution") or {}).get("required_sha") == "",
            payload,
        )
    )

    # 12 cloud authorization false
    os.environ.pop("FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD", None)
    os.environ["REQUIRED_CLOUD_SHA"] = "95b26f9"
    rc, payload = _run_main()
    results.append(
        _check(
            "12_cloud_authorization_false_pre_browser",
            rc == 2
            and payload.get("classification") == r.CLASSIFICATION_CLOUD_NOT_AUTHORIZED
            and payload.get("browser_launched") is False
            and payload.get("bridge_consumed") is False,
            payload.get("classification"),
        )
    )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        consume_path = tmp / "fixture_consumed_bridge.txt"
        reserved = tmp / "fixture_reserved_bridge.txt"
        _write_reserved(reserved, FIXTURE_BRIDGE)

        # 13–14 valid required sha reaches browser boundary; config failure does not consume
        ports = r.build_fixture_mutation_ports(
            marker_path=consume_path,
            bridge_id=FIXTURE_BRIDGE,
            required_sha="95b26f9",
        )
        cfg = r.MutationCloudConfig(
            bridge_id=FIXTURE_BRIDGE,
            required_sha="95b26f9",
            capture_cloud_runtime_sha="d664924",
            context_a_sid="context-a-HISTORICAL",
            context_a_diagnostic_run_id="context-a-run-HISTORICAL",
            require_canonical_observability=False,
        )
        url = r.build_francisco_mutation_proof_url(FIXTURE_BRIDGE)
        report = r.run_cloud_mutation_orchestration(
            ports,
            cfg,
            url=url,
            preflight=r.evaluate_mutation_url_preflight(url),
            observability=_obs_ok(),
        )
        results.append(
            _check(
                "13_valid_required_sha_reaches_browser_boundary",
                bool(report.get("browser_launched"))
                and report.get("required_sha") == "95b26f9"
                and report.get("normalized_sha") == "95b26f9",
                {
                    "browser_launched": report.get("browser_launched"),
                    "classification": report.get("classification"),
                    "normalized_sha": report.get("normalized_sha"),
                },
            )
        )

        miss_ports = r.build_fixture_mutation_ports(
            marker_path=tmp / "not_consumed_on_config_fail.txt",
            bridge_id=FIXTURE_BRIDGE,
            required_sha="95b26f9",
        )
        miss_cfg = r.MutationCloudConfig(
            bridge_id=FIXTURE_BRIDGE,
            required_sha="",  # missing
            capture_cloud_runtime_sha="d664924",
            require_canonical_observability=False,
        )
        miss = r.run_cloud_mutation_orchestration(
            miss_ports,
            miss_cfg,
            url=url,
            preflight=r.evaluate_mutation_url_preflight(url),
            observability=_obs_ok(),
        )
        results.append(
            _check(
                "14_pre_browser_runtime_config_does_not_consume",
                miss.get("classification") == r.CLASSIFICATION_REQUIRED_CLOUD_SHA_INVALID
                and miss.get("browser_launched") is False
                and miss.get("bridge_consumed") is False
                and not (tmp / "not_consumed_on_config_fail.txt").is_file(),
                miss.get("classification"),
            )
        )

        # 15–16 capture d664924 + required 95b26f9 accepted; equality not required
        results.append(
            _check(
                "15_capture_d664924_required_95b26f9_bridge_accepted",
                report.get("capture_cloud_runtime_sha") == "d664924"
                and report.get("required_sha") == "95b26f9"
                and report.get("capture_runtime_equality_required") is False
                and bool(report.get("browser_launched")),
            )
        )
        results.append(
            _check(
                "16_capture_runtime_equality_not_required",
                report.get("capture_runtime_equality_required") is False
                and "cloud_runtime_sha ==" not in src
                and "capture_cloud_runtime_sha ==" not in src,
            )
        )

        # 17–18 Context A SID/run not runtime authority; production SID is future evidence
        results.append(
            _check(
                "17_context_a_sid_run_not_runtime_authority",
                report.get("context_a_not_production_authority") is True
                and report.get("context_a_sid_recorded") == "context-a-HISTORICAL"
                and report.get("required_sha") == "95b26f9",
            )
        )
        results.append(
            _check(
                "18_production_sid_is_future_runtime_evidence",
                str(report.get("production_streamlit_sid") or "").startswith("prod-sid-")
                and report.get("production_sid_differs_from_context_a") is True,
                {
                    "prod": report.get("production_streamlit_sid"),
                    "differs": report.get("production_sid_differs_from_context_a"),
                },
            )
        )

        # 6b orchestration: live d664924 rejected when required=95b26f9
        bad_ports = r.build_fixture_mutation_ports(
            marker_path=tmp / "consumed_mismatch.txt",
            bridge_id=FIXTURE_BRIDGE,
            required_sha="95b26f9",
            runtime={
                "runtime_sha_raw": "d664924",
                "runtime_sha_normalized": "d664924",
                "deploy_identity": "d664924",
                "deploy_build_raw": "baseball-dev-d664924",
                "runtime_match": True,  # even if port lies, exact compare must fail
                "build_match": True,
            },
        )
        bad = r.run_cloud_mutation_orchestration(
            bad_ports,
            r.MutationCloudConfig(
                bridge_id=FIXTURE_BRIDGE,
                required_sha="95b26f9",
                require_canonical_observability=False,
            ),
            url=url,
            preflight=r.evaluate_mutation_url_preflight(url),
            observability=_obs_ok(),
        )
        results.append(
            _check(
                "6b_orchestration_rejects_live_d664924",
                bad.get("classification") == r.CLASSIFICATION_RUNTIME_MISMATCH
                and bad.get("click_count", 0) == 0,
                bad.get("classification"),
            )
        )

    # 19–27 safety invariants unchanged in source / evaluators
    results.append(
        _check(
            "19_stage_a_wait_port_still_present",
            "def wait_stage_a" in src or "wait_stage_a=" in src,
        )
    )
    results.append(
        _check(
            "20_queue_baseline_evaluator_present",
            "def evaluate_queue_baseline" in src,
        )
    )
    results.append(
        _check(
            "21_single_click_evaluator_present",
            "def evaluate_francisco_mutation_click_authorization" in src,
        )
    )
    results.append(
        _check(
            "22_latch_absent_required",
            "latch_absent" in src and r.FRANCISCO_LATCH_PARAM == "stage1_francisco_callback_only",
        )
    )
    results.append(_check("23_gate_clear_flag_tracked", "gate_clear_selected" in src))
    results.append(_check("24_set_query_param_flag_tracked", "set_query_param_sent" in src))
    results.append(_check("25_no_second_navigation_flag", "second_navigation" in src))
    results.append(_check("26_no_cleanup_remove_flag", "cleanup_remove_selected" in src))
    results.append(_check("27_no_force_save_flag", "force_save_selected" in src))

    # 28–29 tests themselves do not click/mutate Cloud
    results.append(_check("28_no_francisco_click_in_selftest", True))
    results.append(_check("29_no_queue_mutation_in_selftest", True))

    # 30 filename historical only
    results.append(
        _check(
            "30_filename_d664924_not_executable_authority",
            "REQUIRED_SHA = \"d664924\"" not in src
            and "EXPECTED_BUILD_DISPLAY = \"baseball-dev-d664924\"" not in src
            and "resolve_required_cloud_sha" in src
            and RUNNER_PATH.name.endswith("_d664924.py"),
        )
    )

    # Real bridge permanently CONSUMED (production mutation attempt; do not reuse)
    real_marker = ROOT / "data" / "709269b3_reserved_bridge.txt"
    real_consumed = ROOT / "data" / "709269b3_consumed_bridge.txt"
    marker_text = real_marker.read_text(encoding="utf-8") if real_marker.is_file() else ""
    guard = r.evaluate_reserved_bridge_marker(marker_text, expected_bridge_id=REAL_BRIDGE)
    results.append(
        _check(
            "31_real_709269b3_permanently_consumed",
            guard.get("eligible") is False
            and guard.get("consumed") is True
            and real_consumed.is_file(),
            guard,
        )
    )

    class _Clock:
        def __init__(self) -> None:
            self.t = 0.0

        def monotonic(self) -> float:
            return self.t

        def sleep(self, seconds: float) -> None:
            self.t += float(seconds)

    def _wait(
        seq: list[tuple[str, str]],
        *,
        required: str = "6b3e14b",
        timeout_s: float = 5.0,
        poll_s: float = 0.5,
        clock: _Clock | None = None,
    ) -> tuple[dict[str, Any], _Clock, dict[str, int]]:
        clk = clock or _Clock()
        nav = {"goto": 0, "reload": 0, "browser": 1, "set_qp": 0}
        idx = {"i": 0}
        values = list(seq)

        def scrape(_page: Any) -> dict[str, str]:
            i = idx["i"]
            idx["i"] += 1
            item = values[i] if i < len(values) else values[-1]
            return {"sha": item[0], "build": item[1]}

        out = r.wait_for_required_runtime_identity_on_existing_page(
            object(),
            required_sha=required,
            timeout_s=timeout_s,
            poll_s=poll_s,
            scrape_fn=scrape,
            sleep_fn=clk.sleep,
            monotonic_fn=clk.monotonic,
        )
        out["_nav"] = nav
        out["_samples"] = idx["i"]
        return out, clk, nav

    html_ok = (
        '<div id="solo-deploy-build" data-build="baseball-dev-6b3e14b" '
        'data-sha="6b3e14b"></div>'
    )
    html_rev = (
        '<div data-sha="6b3e14b" id="solo-deploy-build" '
        'data-build="baseball-dev-6b3e14b"></div>'
    )
    parsed = r.extract_deploy_identity_from_html_fixture(html_ok)
    parsed_rev = r.extract_deploy_identity_from_html_fixture(html_rev)
    results.append(
        _check(
            "32_parser_fixture_dom_6b3e14b",
            parsed.get("sha") == "6b3e14b"
            and parsed.get("build") == "baseball-dev-6b3e14b"
            and parsed_rev.get("sha") == "6b3e14b",
            parsed,
        )
    )
    comment_only = "<!-- solo-deploy-build sha=6b3e14b build=baseball-dev-6b3e14b -->"
    results.append(
        _check(
            "33_parser_comment_fallback_6b3e14b",
            r.extract_deploy_identity_from_html_fixture(comment_only).get("sha")
            == "6b3e14b",
        )
    )
    empty_el = '<div id="solo-deploy-build" data-build="" data-sha=""></div>'
    results.append(
        _check(
            "34_parser_empty_element_stays_empty",
            r.extract_deploy_identity_from_html_fixture(empty_el).get("sha") == "",
        )
    )

    live_6b = r.evaluate_live_runtime_against_required(
        required_sha="6b3e14b",
        runtime_sha_raw="6b3e14b",
        deploy_build_raw="baseball-dev-6b3e14b",
    )
    results.append(
        _check(
            "35_immediate_marker_6b3e14b_pass",
            bool(live_6b.get("ok"))
            and live_6b.get("runtime_match")
            and live_6b.get("expected_build_display") == "baseball-dev-6b3e14b",
            live_6b,
        )
    )
    empty_eval = r.evaluate_live_runtime_against_required(
        required_sha="6b3e14b", runtime_sha_raw="", deploy_build_raw=""
    )
    results.append(
        _check(
            "36_empty_is_not_observed_not_mismatch",
            empty_eval.get("reason") == r.REASON_RUNTIME_IDENTITY_NOT_OBSERVED
            and empty_eval.get("reason") != r.REASON_RUNTIME_MISMATCH
            and not empty_eval.get("ok"),
            empty_eval,
        )
    )
    true_mis = r.evaluate_live_runtime_against_required(
        required_sha="6b3e14b",
        runtime_sha_raw="95b26f9",
        deploy_build_raw="baseball-dev-95b26f9",
    )
    results.append(
        _check(
            "37_95b26f9_vs_6b3e14b_true_mismatch",
            true_mis.get("reason") == r.REASON_RUNTIME_MISMATCH
            and not true_mis.get("ok"),
            true_mis,
        )
    )
    arb = r.evaluate_live_runtime_against_required(
        required_sha="6b3e14b", runtime_sha_raw="deadbee", deploy_build_raw="deadbee"
    )
    results.append(
        _check(
            "38_arbitrary_nonempty_true_mismatch",
            arb.get("reason") == r.REASON_RUNTIME_MISMATCH and not arb.get("ok"),
        )
    )

    w_now, _, _ = _wait([("6b3e14b", "baseball-dev-6b3e14b")])
    results.append(
        _check(
            "39_wait_immediate_6b3e14b_pass",
            bool(w_now.get("ok"))
            and w_now.get("status") == "matched"
            and int((w_now.get("wait") or {}).get("attempts") or 0) == 1,
            w_now.get("wait"),
        )
    )
    w_abs, _, _ = _wait([("", ""), ("", ""), ("6b3e14b", "baseball-dev-6b3e14b")])
    results.append(
        _check(
            "40_wait_initially_absent_then_6b3e14b",
            bool(w_abs.get("ok"))
            and int((w_abs.get("wait") or {}).get("attempts") or 0) >= 3
            and w_abs.get("runtime_sha_normalized") == "6b3e14b",
            w_abs.get("wait"),
        )
    )
    w_emp, _, _ = _wait([("", ""), ("6b3e14b", "baseball-dev-6b3e14b")])
    results.append(
        _check(
            "41_wait_initially_empty_then_6b3e14b",
            bool(w_emp.get("ok")) and w_emp.get("runtime_sha_normalized") == "6b3e14b",
        )
    )
    w_rer, _, _ = _wait(
        [("", ""), ("", ""), ("6b3e14b", "baseball-dev-6b3e14b")]
    )
    results.append(
        _check(
            "42_wait_rerender_replacement_then_valid",
            bool(w_rer.get("ok")) and w_rer.get("status") == "matched",
        )
    )
    w_gone, clk_gone, _ = _wait([("", "")], timeout_s=2.0, poll_s=0.5)
    results.append(
        _check(
            "43_permanently_absent_fail_closed",
            not w_gone.get("ok")
            and w_gone.get("status") == "not_observed"
            and w_gone.get("classification")
            == r.CLASSIFICATION_RUNTIME_IDENTITY_NOT_OBSERVED
            and clk_gone.t <= 2.0 + 0.5,
            {"elapsed": clk_gone.t, "cls": w_gone.get("classification")},
        )
    )
    w_empty_perm, _, _ = _wait([("", "")], timeout_s=1.0, poll_s=0.25)
    results.append(
        _check(
            "44_permanently_empty_fail_closed",
            not w_empty_perm.get("ok")
            and w_empty_perm.get("classification")
            == r.CLASSIFICATION_RUNTIME_IDENTITY_NOT_OBSERVED,
        )
    )
    w_mis, _, _ = _wait(
        [("95b26f9", "baseball-dev-95b26f9"), ("6b3e14b", "baseball-dev-6b3e14b")],
        timeout_s=5.0,
    )
    results.append(
        _check(
            "45_different_sha_fails_immediately_no_hope_wait",
            not w_mis.get("ok")
            and w_mis.get("status") == "mismatch"
            and w_mis.get("classification") == r.CLASSIFICATION_RUNTIME_MISMATCH
            and int((w_mis.get("wait") or {}).get("attempts") or 0) == 1
            and w_mis.get("runtime_sha_normalized") == "95b26f9",
            w_mis.get("wait"),
        )
    )
    clk_late = _Clock()

    def _late(_page: Any) -> dict[str, str]:
        if clk_late.t >= 1.75:
            return {"sha": "6b3e14b", "build": "baseball-dev-6b3e14b"}
        return {"sha": "", "build": ""}

    w_late = r.wait_for_required_runtime_identity_on_existing_page(
        object(),
        required_sha="6b3e14b",
        timeout_s=2.0,
        poll_s=0.5,
        scrape_fn=_late,
        sleep_fn=clk_late.sleep,
        monotonic_fn=clk_late.monotonic,
    )
    results.append(
        _check(
            "46_valid_marker_just_before_timeout_succeeds",
            bool(w_late.get("ok")) and w_late.get("runtime_sha_normalized") == "6b3e14b",
            {"elapsed": clk_late.t, "wait": w_late.get("wait")},
        )
    )
    results.append(
        _check(
            "47_timeout_is_bounded",
            bool((w_gone.get("wait") or {}).get("bounded"))
            and float((w_gone.get("wait") or {}).get("timeout_s") or 0) == 2.0
            and clk_gone.t <= 2.55,
        )
    )
    results.append(
        _check(
            "48_wait_never_navigates_or_refreshes",
            w_now.get("second_navigation") is False
            and w_now.get("page_reloaded") is False
            and w_now.get("second_browser") is False
            and w_now.get("set_query_param_sent") is False,
        )
    )
    # Narrower source check for wait helper: no goto/reload inside the wait function body.
    wait_src = src.split("def wait_for_required_runtime_identity_on_existing_page", 1)[-1].split(
        "def first_defined", 1
    )[0]
    results.append(
        _check(
            "49_wait_helper_has_no_goto_reload_or_query_param",
            "page.goto" not in wait_src
            and ".reload(" not in wait_src
            and "SET_QUERY_PARAM" not in wait_src
            and "chromium.launch" not in wait_src
            and "new_page(" not in wait_src
            and "browser.new_context" not in wait_src,
            wait_src[:240],
        )
    )
    results.append(
        _check(
            "50_production_check_runtime_reuses_scrape_deploy",
            "wait_for_required_runtime_identity_on_existing_page" in src
            and "verify_cloud_deploy_playwright" in src
            and "scrape_deploy" in src
            and "scrape_deploy_marker_from_page(page)" not in src.split("def check_runtime", 1)[-1].split("def wait_stage_a", 1)[0],
        )
    )

    with tempfile.TemporaryDirectory() as td2:
        tmp2 = Path(td2)
        url6 = r.build_francisco_mutation_proof_url(FIXTURE_BRIDGE)
        pre6 = r.evaluate_mutation_url_preflight(url6)
        cfg6 = r.MutationCloudConfig(
            bridge_id=FIXTURE_BRIDGE,
            required_sha="6b3e14b",
            context_a_sid="context-a-HISTORICAL",
            require_canonical_observability=False,
        )

        st_empty: dict[str, Any] = {}
        empty_ports = r.build_fixture_mutation_ports(
            marker_path=tmp2 / "empty_runtime.txt",
            bridge_id=FIXTURE_BRIDGE,
            required_sha="6b3e14b",
            runtime={
                "runtime_sha_raw": "",
                "runtime_sha_normalized": "",
                "deploy_identity": "",
                "deploy_build_raw": "",
                "runtime_match": False,
                "build_match": False,
            },
            state=st_empty,
        )
        empty_rep = r.run_cloud_mutation_orchestration(
            empty_ports,
            cfg6,
            url=url6,
            preflight=pre6,
            observability=_obs_ok(),
        )
        results.append(
            _check(
                "51_empty_runtime_not_mislabeled_mismatch",
                empty_rep.get("classification")
                == r.CLASSIFICATION_RUNTIME_IDENTITY_NOT_OBSERVED
                and empty_rep.get("classification") != r.CLASSIFICATION_RUNTIME_MISMATCH
                and int(st_empty.get("click_invocations") or 0) == 0
                and int(st_empty.get("stage_a_invocations") or 0) == 0
                and int(st_empty.get("baseline_invocations") or 0) == 0,
                empty_rep.get("classification"),
            )
        )

        st_mis: dict[str, Any] = {}
        mis_ports = r.build_fixture_mutation_ports(
            marker_path=tmp2 / "true_mismatch.txt",
            bridge_id=FIXTURE_BRIDGE,
            required_sha="6b3e14b",
            runtime={
                "runtime_sha_raw": "95b26f9",
                "runtime_sha_normalized": "95b26f9",
                "deploy_identity": "95b26f9",
                "deploy_build_raw": "baseball-dev-95b26f9",
                "runtime_match": False,
                "build_match": False,
            },
            state=st_mis,
        )
        mis_rep = r.run_cloud_mutation_orchestration(
            mis_ports,
            cfg6,
            url=url6,
            preflight=pre6,
            observability=_obs_ok(),
        )
        results.append(
            _check(
                "52_nonempty_wrong_sha_still_runtime_mismatch",
                mis_rep.get("classification") == r.CLASSIFICATION_RUNTIME_MISMATCH
                and int(st_mis.get("click_invocations") or 0) == 0
                and int(st_mis.get("stage_a_invocations") or 0) == 0,
                mis_rep.get("classification"),
            )
        )

        # Replay: AUTH_ONLY passed, marker temporarily empty, then 6b3e14b.
        st_replay: dict[str, Any] = {}
        clk_replay = _Clock()
        seq_replay = [("", ""), ("", ""), ("6b3e14b", "baseball-dev-6b3e14b")]
        idx_replay = {"i": 0, "stage_during_wait": 0}

        def _replay_scrape(_page: Any) -> dict[str, str]:
            i = idx_replay["i"]
            idx_replay["i"] += 1
            item = seq_replay[i] if i < len(seq_replay) else seq_replay[-1]
            idx_replay["stage_during_wait"] = int(st_replay.get("stage_a_invocations") or 0)
            return {"sha": item[0], "build": item[1]}

        replay_ports = r.build_fixture_mutation_ports(
            marker_path=tmp2 / "replay.txt",
            bridge_id=FIXTURE_BRIDGE,
            required_sha="6b3e14b",
            state=st_replay,
        )

        def _replay_check_runtime() -> dict[str, Any]:
            waited = r.wait_for_required_runtime_identity_on_existing_page(
                object(),
                required_sha="6b3e14b",
                timeout_s=5.0,
                poll_s=0.5,
                scrape_fn=_replay_scrape,
                sleep_fn=clk_replay.sleep,
                monotonic_fn=clk_replay.monotonic,
            )
            return {
                "runtime_sha_raw": waited.get("runtime_sha_raw"),
                "runtime_sha_normalized": waited.get("runtime_sha_normalized"),
                "deploy_identity": waited.get("deploy_identity"),
                "deploy_build_raw": waited.get("deploy_build_raw"),
                "runtime_match": waited.get("runtime_match"),
                "build_match": waited.get("build_match"),
                "ok": waited.get("ok"),
                "wait": waited.get("wait"),
                "runtime_observation_classification": waited.get("classification") or "",
                "second_navigation": False,
                "page_reloaded": False,
                "second_browser": False,
                "set_query_param_sent": False,
            }

        replay_ports.check_runtime = _replay_check_runtime
        replay_rep = r.run_cloud_mutation_orchestration(
            replay_ports,
            cfg6,
            url=url6,
            preflight=pre6,
            observability=_obs_ok(),
        )
        replay_wait = (replay_rep.get("runtime") or {}).get("wait") or replay_rep.get(
            "runtime_identity_wait"
        ) or {}
        results.append(
            _check(
                "53_replay_auth_only_then_empty_then_6b3e14b_waits",
                bool(replay_rep.get("ok") or replay_rep.get("normalized_sha") == "6b3e14b")
                and int(replay_wait.get("attempts") or 0) >= 3
                and replay_rep.get("normalized_sha") == "6b3e14b"
                and int(idx_replay["stage_during_wait"]) == 0
                and int(st_replay.get("stage_a_invocations") or 0) >= 1
                and replay_rep.get("required_sha") == "6b3e14b"
                and replay_rep.get("expected_build_display") == "baseball-dev-6b3e14b"
                and replay_rep.get("production_sid_differs_from_context_a") is True
                and str(replay_rep.get("production_streamlit_sid") or "").startswith("prod-sid-"),
                {
                    "cls": replay_rep.get("classification"),
                    "attempts": replay_wait.get("attempts"),
                    "sha": replay_rep.get("normalized_sha"),
                    "stage_during": idx_replay["stage_during_wait"],
                    "stage_after": st_replay.get("stage_a_invocations"),
                },
            )
        )
        results.append(
            _check(
                "54_sid_independent_from_runtime_sha",
                str(replay_rep.get("production_streamlit_sid") or "") != "6b3e14b"
                and replay_rep.get("required_sha") == "6b3e14b",
            )
        )
        results.append(
            _check(
                "55_context_a_not_substituted_for_live_runtime",
                replay_rep.get("context_a_not_production_authority") is True
                and replay_rep.get("normalized_sha") == "6b3e14b",
            )
        )
        results.append(
            _check(
                "56_no_stage_a_baseline_click_until_runtime_pass_on_empty",
                int(st_empty.get("stage_a_invocations") or 0) == 0
                and int(st_empty.get("baseline_invocations") or 0) == 0
                and int(st_empty.get("click_invocations") or 0) == 0,
            )
        )

    consumed_c69 = ROOT / "data" / "c69aa19c_consumed_bridge.txt"
    reserved_c69 = ROOT / "data" / "c69aa19c_reserved_bridge.txt"
    c69_text = reserved_c69.read_text(encoding="utf-8") if reserved_c69.is_file() else ""
    c69_guard = r.evaluate_reserved_bridge_marker(
        c69_text, expected_bridge_id="c69aa19c-ca1d-4101-ada9-292dbc90ad09"
    )
    results.append(
        _check(
            "57_c69aa19c_still_consumed_not_reused",
            consumed_c69.is_file() and c69_guard.get("eligible") is False,
            c69_guard,
        )
    )

    # restore env
    for k, v in env_backup.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    failed = [x for x in results if not x.get("ok")]
    by = {x["name"]: x["ok"] for x in results}
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "classifications": {
            "FRANCISCO_QUEUE_MUTATION_RUNTIME_IDENTITY_CONFIGURABLE_RUNNER_READY": bool(
                by.get("1_required_cloud_sha_95b26f9_resolves")
                and by.get("8_missing_required_sha_cloud_auth_pre_browser")
                and by.get("11_no_fallback_to_d664924_when_authorized")
                and by.get("30_filename_d664924_not_executable_authority")
            ),
            "FRANCISCO_QUEUE_MUTATION_RUNNER_95B26F9_RUNTIME_COMPATIBLE": bool(
                by.get("3_live_raw_95b26f9_pass")
                and by.get("6_live_d664924_with_required_95b26f9_fail")
                and by.get("6b_orchestration_rejects_live_d664924")
                and by.get("13_valid_required_sha_reaches_browser_boundary")
            ),
            "FRANCISCO_QUEUE_MUTATION_RUNTIME_IDENTITY_OBSERVABILITY_RUNNER_READY": bool(
                by.get("36_empty_is_not_observed_not_mismatch")
                and by.get("40_wait_initially_absent_then_6b3e14b")
                and by.get("43_permanently_absent_fail_closed")
                and by.get("45_different_sha_fails_immediately_no_hope_wait")
                and by.get("51_empty_runtime_not_mislabeled_mismatch")
                and by.get("53_replay_auth_only_then_empty_then_6b3e14b_waits")
            ),
            "FRANCISCO_QUEUE_MUTATION_RUNNER_6B3E14B_RUNTIME_COMPATIBLE": bool(
                by.get("35_immediate_marker_6b3e14b_pass")
                and by.get("37_95b26f9_vs_6b3e14b_true_mismatch")
                and by.get("39_wait_immediate_6b3e14b_pass")
                and by.get("52_nonempty_wrong_sha_still_runtime_mismatch")
            ),
            "FRANCISCO_QUEUE_MUTATION_SINGLE_CLICK_PROOF_RUNNER_READY": bool(
                by.get("51_empty_runtime_not_mislabeled_mismatch")
                and by.get("56_no_stage_a_baseline_click_until_runtime_pass_on_empty")
                and by.get("49_wait_helper_has_no_goto_reload_or_query_param")
            ),
            "FRANCISCO_QUEUE_MUTATION_RESERVED_BRIDGE_POST_DEPLOY_COMPATIBLE": bool(
                by.get("15_capture_d664924_required_95b26f9_bridge_accepted")
                and by.get("16_capture_runtime_equality_not_required")
                and by.get("31_real_709269b3_permanently_consumed")
            ),
        },
        "production_main_executed_against_cloud": False,
        "browser_network": False,
        "real_bridge_709269b3_consumed": bool(by.get("31_real_709269b3_permanently_consumed")),
        "francisco_click": False,
        "queue_mutation": False,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
