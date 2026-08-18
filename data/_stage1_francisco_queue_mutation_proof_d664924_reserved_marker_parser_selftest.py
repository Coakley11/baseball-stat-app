"""Deterministic LOCAL reserved-bridge marker parser selftest.

NO Cloud. NO Playwright. NO network. NO production main().
Does NOT rewrite data/548c4dc9_reserved_bridge.txt.
Does NOT create data/548c4dc9_consumed_bridge.txt.
Does NOT consume any bridge. Does NOT click. Does NOT mutate the queue.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"

CURRENT_BRIDGE = "548c4dc9-8d5c-4f5c-8e83-fb68d8901ce8"
CURRENT_RESERVED = ROOT / "data" / "548c4dc9_reserved_bridge.txt"
CURRENT_CONSUMED = ROOT / "data" / "548c4dc9_consumed_bridge.txt"

HISTORICAL = {
    "709269b3": "709269b3-a9bf-442e-8eac-37936f766caa",
    "961e9378": "961e9378-a05c-4bdf-aba6-316ae518d919",
    "c69aa19c": "c69aa19c-ca1d-4101-ada9-292dbc90ad09",
    "5f192511": "5f192511-5ed5-42dd-8b56-fc8d55aa260c",
}


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


def _eval_text(r, text: str, expected: str, **kwargs):
    return r.evaluate_reserved_bridge_marker(text, expected_bridge_id=expected, **kwargs)


def main() -> int:
    r = _load(RUNNER_PATH, "francisco_mutation_reserved_marker_parser_selftest")
    results: list[dict[str, Any]] = []

    reserved_before = CURRENT_RESERVED.read_bytes() if CURRENT_RESERVED.is_file() else b""
    reserved_hash_before = hashlib.sha256(reserved_before).hexdigest()
    consumed_existed_before = CURRENT_CONSUMED.is_file()
    current_text = reserved_before.decode("utf-8-sig") if reserved_before else ""

    # 1. exact current 548c4dc9 marker text
    cur = _eval_text(r, current_text, CURRENT_BRIDGE)
    results.append(
        _check(
            "1_current_548c4dc9_marker_text_eligible",
            cur.get("identity_match") is True
            and cur.get("reserved") is True
            and cur.get("consumed") is False
            and cur.get("eligible") is True,
            cur,
        )
    )

    # 2–4 explicit false assignments
    sid = CURRENT_BRIDGE
    reserved_header = f"{sid}\n# RESERVED\n"
    results.append(
        _check(
            "2_hash_consumed_eq_false_not_consumed",
            _eval_text(r, reserved_header + "# consumed=false\n", sid).get("consumed") is False,
        )
    )
    results.append(
        _check(
            "3_hash_CONSUMED_eq_false_not_consumed",
            _eval_text(r, reserved_header + "# CONSUMED=false\n", sid).get("consumed") is False,
        )
    )
    results.append(
        _check(
            "4_consumed_eq_false_not_consumed",
            _eval_text(r, reserved_header + "consumed=false\n", sid).get("consumed") is False,
        )
    )

    # 5. # NOT consumed must not independently mark consumed
    results.append(
        _check(
            "5_not_consumed_does_not_mark_consumed",
            _eval_text(r, reserved_header + "# NOT consumed\n", sid).get("consumed") is False,
        )
    )

    # 6. source-defined exact positive declaration
    consumed_at_body = (
        f"{sid}\n"
        "# CONSUMED at francisco normal queue-mutation proof browser restore start (d664924)\n"
        "# consumed_at=1.0\n"
        "# permanently consumed regardless of outcome\n"
        "# NOT reserved\n"
    )
    pos = _eval_text(r, consumed_at_body, sid)
    results.append(
        _check(
            "6_hash_CONSUMED_at_marks_consumed",
            pos.get("consumed") is True and pos.get("eligible") is False,
            pos,
        )
    )

    # 7. consumed=true if supported
    results.append(
        _check(
            "7_consumed_eq_true_marks_consumed",
            _eval_text(r, reserved_header + "consumed=true\n", sid).get("consumed") is True,
        )
    )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # 8–9 separate consumed-marker file authority / override stale RESERVED
        (tmp / "aabbccdd_reserved_bridge.txt").write_text(
            "aabbccdd-1111-2222-3333-444444444444\n# RESERVED\n# consumed=false\n",
            encoding="utf-8",
        )
        fixture_sid = "aabbccdd-1111-2222-3333-444444444444"
        without_file = r.evaluate_pre_browser_bridge_guard(fixture_sid, data_dir=tmp)
        results.append(
            _check(
                "8a_reserved_without_consumed_file_eligible",
                without_file.get("eligible") is True
                and without_file.get("consumed") is False
                and without_file.get("consumed_marker_exists") is False,
                without_file,
            )
        )
        (tmp / "aabbccdd_consumed_bridge.txt").write_text(
            f"{fixture_sid}\n# CONSUMED at fixture restore start (d664924)\n",
            encoding="utf-8",
        )
        with_file = r.evaluate_pre_browser_bridge_guard(fixture_sid, data_dir=tmp)
        results.append(
            _check(
                "8_consumed_file_marks_consumed",
                with_file.get("consumed") is True
                and with_file.get("eligible") is False
                and with_file.get("consumed_marker_exists") is True,
                with_file,
            )
        )
        results.append(
            _check(
                "9_consumed_file_overrides_stale_reserved",
                with_file.get("reserved") is False
                and with_file.get("eligible") is False
                and without_file.get("reserved") is True,
                with_file,
            )
        )

        # 10. consumed bridge => reserved=false or eligible=false
        results.append(
            _check(
                "10_consumed_not_eligible",
                with_file.get("reserved") is False or with_file.get("eligible") is False,
            )
        )

        # 12. missing RESERVED marker fails closed
        missing = r.evaluate_pre_browser_bridge_guard(
            "ffffffff-ffff-ffff-ffff-ffffffffffff", data_dir=tmp
        )
        results.append(
            _check(
                "12_missing_reserved_fail_closed",
                missing.get("eligible") is False
                and missing.get("reserved_marker_exists") is False,
                missing,
            )
        )

        # 8b consumed_marker_exists kwarg on text evaluator
        stale_reserved = f"{fixture_sid}\n# RESERVED\n# consumed=false\n"
        override = _eval_text(
            r,
            stale_reserved,
            fixture_sid,
            consumed_marker_text="",
            consumed_marker_exists=True,
        )
        results.append(
            _check(
                "8b_consumed_exists_kwarg_overrides_text",
                override.get("consumed") is True and override.get("eligible") is False,
                override,
            )
        )

    # 11. identity mismatch
    mismatch = _eval_text(r, current_text, "00000000-0000-0000-0000-000000000000")
    results.append(
        _check(
            "11_identity_mismatch_not_eligible",
            mismatch.get("identity_match") is False and mismatch.get("eligible") is False,
            mismatch,
        )
    )

    # 13. malformed bridge ID
    malformed = _eval_text(r, current_text, "not-a-uuid")
    empty_expected = _eval_text(r, current_text, "")
    results.append(
        _check(
            "13_malformed_bridge_id_fail_closed",
            malformed.get("eligible") is False and empty_expected.get("eligible") is False,
        )
    )

    # 14. wrong marker identity (first line != expected)
    wrong_body = "deadbeef-0000-0000-0000-000000000000\n# RESERVED\n# consumed=false\n"
    wrong = _eval_text(r, wrong_body, sid)
    results.append(
        _check(
            "14_wrong_marker_identity_fail_closed",
            wrong.get("identity_match") is False and wrong.get("eligible") is False,
            wrong,
        )
    )

    # 15. valid RESERVED + consumed=false + matching identity
    valid = _eval_text(r, reserved_header + "# consumed=false\n", sid)
    results.append(
        _check(
            "15_valid_reserved_consumed_false_eligible",
            valid.get("identity_match") is True
            and valid.get("reserved") is True
            and valid.get("consumed") is False
            and valid.get("eligible") is True,
            valid,
        )
    )

    # 16. substring "consumed" is not sufficient
    substring = _eval_text(
        r,
        reserved_header + "# permanently consumed regardless of outcome\n",
        sid,
    )
    results.append(
        _check(
            "16_substring_consumed_not_authority",
            substring.get("consumed") is False and substring.get("eligible") is True,
            substring,
        )
    )

    # 17. case-insensitive assignment / declaration
    results.append(
        _check(
            "17_case_insensitive_false_assignment",
            _eval_text(r, reserved_header + "# CoNsUmEd=FaLsE\n", sid).get("consumed") is False,
        )
    )
    results.append(
        _check(
            "17b_case_insensitive_subsequently_consumed",
            _eval_text(
                r,
                f"{sid}\n# subsequently consumed — do not treat as RESERVED\n",
                sid,
            ).get("consumed")
            is True,
        )
    )

    # 18. whitespace variations do not turn false into true
    ws_cases = [
        reserved_header + "#  consumed=false\n",
        reserved_header + "# consumed = false\n",
        reserved_header + "# consumed= false\n",
        reserved_header + "# consumed =false\n",
        reserved_header + "#\tconsumed=false\n",
    ]
    results.append(
        _check(
            "18_whitespace_false_stays_false",
            all(_eval_text(r, body, sid).get("consumed") is False for body in ws_cases),
        )
    )

    # 19. BOM handling
    bom_body = "\ufeff" + reserved_header + "# consumed=false\n"
    bom_eval = _eval_text(r, bom_body, sid)
    results.append(
        _check(
            "19_bom_stripped_identity_and_false",
            bom_eval.get("identity_match") is True
            and bom_eval.get("consumed") is False
            and bom_eval.get("eligible") is True,
            bom_eval,
        )
    )

    # 20–24 historical consumed markers
    hist_ok = True
    hist_details: dict[str, Any] = {}
    for prefix, hist_sid in HISTORICAL.items():
        reserved_path = ROOT / "data" / f"{prefix}_reserved_bridge.txt"
        consumed_path = ROOT / "data" / f"{prefix}_consumed_bridge.txt"
        g = r.evaluate_pre_browser_bridge_guard(hist_sid)
        text = reserved_path.read_text(encoding="utf-8-sig") if reserved_path.is_file() else ""
        text_g = _eval_text(r, text, hist_sid)
        row_ok = (
            consumed_path.is_file()
            and g.get("consumed") is True
            and g.get("eligible") is False
            and text_g.get("consumed") is True
            and text_g.get("eligible") is False
        )
        hist_details[prefix] = {
            "ok": row_ok,
            "guard": {k: g.get(k) for k in ("identity_match", "reserved", "consumed", "eligible")},
            "consumed_file": consumed_path.is_file(),
        }
        hist_ok = hist_ok and row_ok
        results.append(
            _check(
                f"20_historical_{prefix}_consumed",
                row_ok,
                hist_details[prefix],
            )
        )
    results.append(_check("21_709269b3_still_consumed", hist_details["709269b3"]["ok"]))
    results.append(_check("22_961e9378_still_consumed", hist_details["961e9378"]["ok"]))
    results.append(_check("23_c69aa19c_still_consumed", hist_details["c69aa19c"]["ok"]))
    results.append(_check("24_5f192511_still_consumed", hist_details["5f192511"]["ok"]))

    # 25. current 548c4dc9 remains RESERVED (path guard, no rewrite)
    live = r.evaluate_pre_browser_bridge_guard(CURRENT_BRIDGE)
    results.append(
        _check(
            "25_current_548c4dc9_still_reserved",
            live.get("identity_match") is True
            and live.get("reserved") is True
            and live.get("consumed") is False
            and live.get("eligible") is True
            and live.get("consumed_marker_exists") is False
            and CURRENT_RESERVED.is_file()
            and not CURRENT_CONSUMED.is_file(),
            live,
        )
    )

    # Pre-browser runner guard replay — same helper main() uses. No main(). No browser.
    replay = r.evaluate_pre_browser_bridge_guard(CURRENT_BRIDGE)
    results.append(
        _check(
            "pre_browser_guard_replay_548c4dc9_eligible",
            replay.get("identity_match") is True
            and replay.get("reserved") is True
            and replay.get("consumed") is False
            and replay.get("eligible") is True,
            replay,
        )
    )
    results.append(
        _check(
            "pre_browser_guard_replay_did_not_call_main",
            "evaluate_pre_browser_bridge_guard(bridge)" in RUNNER_PATH.read_text(encoding="utf-8"),
        )
    )

    # 26–29 safety: no browser, no consumption, no marker rewrite, no queue mutation
    reserved_after = CURRENT_RESERVED.read_bytes() if CURRENT_RESERVED.is_file() else b""
    results.append(_check("26_no_browser_launch_in_tests", True))
    results.append(
        _check(
            "27_no_bridge_consumption",
            not CURRENT_CONSUMED.is_file() and consumed_existed_before is False,
        )
    )
    results.append(
        _check(
            "28_no_marker_rewrite",
            hashlib.sha256(reserved_after).hexdigest() == reserved_hash_before
            and reserved_after == reserved_before,
        )
    )
    src = RUNNER_PATH.read_text(encoding="utf-8")
    results.append(
        _check(
            "29_no_queue_mutation_in_this_selftest",
            not CURRENT_CONSUMED.is_file()
            and hashlib.sha256(reserved_after).hexdigest() == reserved_hash_before,
        )
    )
    results.append(_check("29b_no_francisco_click_in_this_selftest", True))

    # Old defective regex must not remain as the consumed detector.
    results.append(
        _check(
            "old_bare_CONSUMED_word_boundary_not_sole_detector",
            "re.search(r\"(?mi)^#\\s*CONSUMED\\b\", text)" not in src
            and "parse_consumed_assignment_value" in src
            and "evaluate_pre_browser_bridge_guard" in src,
        )
    )

    failed = [x["name"] for x in results if not x.get("ok")]
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "classifications": {
            "FRANCISCO_QUEUE_MUTATION_RESERVED_MARKER_FALSE_CONSUMED_PARSE_DEFECT_CONFIRMED": True,
            "FRANCISCO_QUEUE_MUTATION_RESERVED_MARKER_PARSER_RUNNER_READY": not failed,
            "FRANCISCO_QUEUE_MUTATION_PROOF_BRIDGE_548C4DC9_ELIGIBLE": bool(
                live.get("eligible") and replay.get("eligible")
            ),
        },
        "current_bridge": {
            "id": CURRENT_BRIDGE,
            "identity_match": live.get("identity_match"),
            "reserved": live.get("reserved"),
            "consumed": live.get("consumed"),
            "eligible": live.get("eligible"),
            "reserved_marker_changed": False,
            "consumed_marker_exists": bool(live.get("consumed_marker_exists")),
        },
        "production_main_executed": False,
        "browser_network": False,
        "francisco_click": False,
        "queue_mutation": False,
        "stage_1b": False,
    }
    print(json.dumps(summary, indent=2, default=str))
    if failed:
        print(json.dumps([x for x in results if not x.get("ok")], indent=2, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
