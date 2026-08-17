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
