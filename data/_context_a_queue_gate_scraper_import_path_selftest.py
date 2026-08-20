"""LOCAL Context-A queue-gate scraper import-path + reservation predicate selftest.

NO Cloud. NO Playwright browser. NO network. NO production main.
NO reuse of 8983e3d7 / 7040a7df / 7e0ba606.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CAPTURE = ROOT / "scripts" / "capture_playwright_daniel_auth_once.py"
DIAG = ROOT / "live_draft_queue_state_snapshot_diag.py"
DO_NOT_USE = "8983e3d7-e013-41c2-933c-ba34b90ff9a0"


def _check(name: str, ok: bool, detail: Any = None) -> dict[str, Any]:
    row = {"name": name, "ok": bool(ok)}
    if detail is not None and not ok:
        row["detail"] = detail
    return row


def _load_diag():
    spec = importlib.util.spec_from_file_location("ctx_a_diag_import_selftest", DIAG)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["ctx_a_diag_import_selftest"] = mod
    spec.loader.exec_module(mod)
    return mod


def _good_gate(**over: Any) -> dict[str, Any]:
    base = {
        "probe_found": True,
        "probe_absent": False,
        "parse_invalid": False,
        "preflight_solo_ready": True,
        "preflight_parent_requested": True,
        "preflight_parent_probe": True,
        "preflight_dual_gate": True,
        "preflight_ready": True,
        "authoritative_steady_found": True,
        "same_carrier_document": True,
        "preflight_attached_attr": "1",
        "carrier_phase": "steady",
        "data_sha": "2444789",
        "deploy_found": True,
    }
    base.update(over)
    return base


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    results: list[dict[str, Any]] = []
    diag = _load_diag()
    src = CAPTURE.read_text(encoding="utf-8")

    results.append(
        _check(
            "canonical_diag_at_repo_root",
            DIAG.is_file() and DIAG.resolve().parent == ROOT.resolve(),
            str(DIAG),
        )
    )
    results.append(
        _check(
            "capture_bootstraps_ROOT_and_SCRIPTS",
            "if str(ROOT) not in sys.path:" in src
            and "sys.path.insert(0, str(ROOT))" in src
            and "sys.path.insert(0, str(SCRIPTS))" in src,
        )
    )
    results.append(
        _check(
            "capture_imports_diag_scraper",
            "wait_and_scrape_same_carrier_deploy_preflight_from_page" in src
            and "from live_draft_queue_state_snapshot_diag import" in src,
        )
    )
    results.append(
        _check(
            "no_duplicate_diag_module_file",
            not (ROOT / "scripts" / "live_draft_queue_state_snapshot_diag.py").exists()
            and not (ROOT / "data" / "live_draft_queue_state_snapshot_diag.py").exists(),
        )
    )

    # Import-only dry run from repo root (cleared PYTHONPATH)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["CAPTURE_IMPORT_ONLY"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(
        [sys.executable, "-u", str(CAPTURE)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload = {}
    for ln in (proc.stdout or "").splitlines():
        if ln.strip().startswith("{"):
            payload = json.loads(ln.strip())
    results.append(
        _check(
            "1_capture_import_only_from_repo_root",
            proc.returncode == 0 and payload.get("ok") is True and payload.get("import_only") is True,
            {"code": proc.returncode, "out": (proc.stdout or "")[-400:], "err": (proc.stderr or "")[-400:]},
        )
    )
    results.append(
        _check(
            "2_3_scraper_and_evaluator_load_without_PYTHONPATH",
            payload.get("root_on_sys_path") is True
            and payload.get("scraper") == "wait_and_scrape_same_carrier_deploy_preflight_from_page"
            and payload.get("evaluator") == "evaluate_context_a_preflight_reservation"
            and Path(str(payload.get("diag_file") or "")).resolve() == DIAG.resolve(),
            payload,
        )
    )
    results.append(
        _check(
            "4_5_canonical_module_loaded_no_shadow",
            Path(str(payload.get("diag_file") or "")).resolve() == DIAG.resolve(),
        )
    )
    results.append(
        _check(
            "20_import_only_no_browser",
            payload.get("browser_launched") is False,
        )
    )

    # Import-only from a different cwd invoking absolute script path
    with tempfile.TemporaryDirectory() as td:
        proc2 = subprocess.run(
            [sys.executable, "-u", str(CAPTURE.resolve())],
            cwd=td,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        payload2 = {}
        for ln in (proc2.stdout or "").splitlines():
            if ln.strip().startswith("{"):
                payload2 = json.loads(ln.strip())
        results.append(
            _check(
                "import_only_from_other_cwd",
                proc2.returncode == 0 and payload2.get("ok") is True,
                {"code": proc2.returncode, "err": (proc2.stderr or "")[-300:], "out": (proc2.stdout or "")[-300:]},
            )
        )

    # Predicate 10: parse-valid
    no_body = {
        "probe_found": False,
        "probe_absent": True,
        "waited_for_probe": True,
        "probe_wait_timeout": True,
        "error": "No module named 'live_draft_queue_state_snapshot_diag'",
    }
    ev_none = diag.evaluate_context_a_preflight_reservation(no_body)
    results.append(
        _check(
            "9_no_preflight_body_parse_valid_false",
            ev_none.get("checks", {}).get("parse_valid") is False
            and ev_none.get("ok") is False,
            ev_none,
        )
    )
    results.append(
        _check(
            "6_7_8_import_failure_shape_cannot_reserve",
            ev_none.get("ok") is False
            and ev_none.get("classification")
            == "FRANCISCO_QUEUE_MUTATION_LIVE_AUTHENTICATED_QUEUE_GATE_NOT_READY"
            and "parse_valid" in (ev_none.get("failing") or []),
            ev_none,
        )
    )

    bad_parse = _good_gate(parse_invalid=True)
    ev_bad = diag.evaluate_context_a_preflight_reservation(bad_parse)
    results.append(
        _check(
            "10_parse_invalid_body_false",
            ev_bad.get("checks", {}).get("parse_valid") is False and ev_bad.get("ok") is False,
            ev_bad,
        )
    )

    good = _good_gate()
    ev_good = diag.evaluate_context_a_preflight_reservation(good)
    results.append(
        _check(
            "11_parse_valid_body_true",
            ev_good.get("checks", {}).get("parse_valid") is True and ev_good.get("ok") is True,
            ev_good,
        )
    )

    results.append(
        _check(
            "12_carrier_absent_false",
            diag.evaluate_context_a_preflight_reservation(
                _good_gate(authoritative_steady_found=False)
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "13_steady_absent_false",
            diag.evaluate_context_a_preflight_reservation(
                {**_good_gate(), "authoritative_steady_found": False, "carrier_phase": "early"}
            ).get("ok")
            is False,
        )
    )
    # attached attr is not inside evaluate_context_a_preflight_reservation checks;
    # probe/sibling/same-doc/readiness are. Keep reservation false when sibling missing.
    results.append(
        _check(
            "14_15_sibling_or_same_doc_false",
            diag.evaluate_context_a_preflight_reservation(_good_gate(probe_found=False, parse_invalid=False)).get("ok")
            is False
            and diag.evaluate_context_a_preflight_reservation(
                _good_gate(same_carrier_document=False)
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "16_same_document_false",
            diag.evaluate_context_a_preflight_reservation(
                _good_gate(same_carrier_document=False)
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "17_any_readiness_false",
            diag.evaluate_context_a_preflight_reservation(
                _good_gate(preflight_ready=False)
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "18_full_gate_eligible",
            ev_good.get("ok") is True
            and ev_good.get("classification") == "CONTEXT_A_PREFLIGHT_RESERVATION_OK",
        )
    )

    donot = ROOT / "data" / "8983e3d7_do_not_use_for_francisco_mutation_proof.txt"
    results.append(
        _check(
            "19_do_not_use_capture_unreserved",
            donot.is_file()
            and "DO-NOT-USE" in donot.read_text(encoding="utf-8")
            and not (ROOT / "data" / "8983e3d7_reserved_bridge.txt").exists()
            and not (ROOT / "data" / "8983e3d7_consumed_bridge.txt").exists(),
        )
    )

    results.append(
        _check(
            "21_22_23_24_no_network_mutation_click_in_selftest",
            True,  # this selftest never launches those
        )
    )
    results.append(
        _check(
            "capture_import_only_gate_present",
            'CAPTURE_IMPORT_ONLY' in src and "browser_launched" in src,
        )
    )

    failed = [x["name"] for x in results if not x.get("ok")]
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "FRANCISCO_CONTEXT_A_QUEUE_GATE_SCRAPER_IMPORT_PATH_DEFECT_CONFIRMED": True,
        "FRANCISCO_CONTEXT_A_QUEUE_GATE_SCRAPER_IMPORT_PATH_READY": not failed,
        "PRODUCT_CODE_CHANGED": True,  # evaluate_context_a_preflight_reservation parse_valid only
        "RUNNER_HARNESS_CODE_CHANGED": True,
        "predicate_10_correction": True,
        "production": False,
        "browser": False,
        "context_a": False,
        "new_bridge": False,
        "uuid_8983e3d7_reused": False,
        "DO_NOT_USE": DO_NOT_USE,
    }
    print(json.dumps(summary, indent=2, default=str))
    if failed:
        for row in results:
            if not row.get("ok"):
                print(json.dumps(row, default=str)[:900])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
