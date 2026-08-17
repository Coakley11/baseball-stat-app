"""Deterministic tests: dual-queue state snapshot diagnostic (unlatched).

NO Cloud. NO Playwright browser. NO production. NO 709269b3 consumption.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DIAG_PATH = ROOT / "live_draft_queue_state_snapshot_diag.py"
RUNNER_PATH = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
REAL_BRIDGE = "709269b3-a9bf-442e-8eac-37936f766caa"


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


def _diag_session(**over: Any) -> dict[str, Any]:
    s: dict[str, Any] = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_parent_boundary_probe": True,
        "_solo_stage1_run_id": "run-fixture-001",
        "_streamlit_session_id": "sid-fixture-001",
        "draft_queue": [],
        "draft_state": {"queue": []},
        "live_draft_room": {"draft_room_id": "ROOM1", "current_pick_index": 2},
        "_solo_stage1_script_run_seq": 5,
        "_solo_stage1_recommendation_fragment_run_seq": 3,
    }
    s.update(over)
    return s


def main() -> int:
    d = _load(DIAG_PATH, "queue_state_snapshot_diag_selftest")
    r = _load(RUNNER_PATH, "mutation_runner_for_obs_selftest")
    results: list[dict[str, Any]] = []

    # 1. diagnostics off -> no event
    off = {"draft_queue": ["A"], "draft_state": {"queue": ["A"]}}
    assert d.record_queue_state_baseline_snapshot(None, off) is None
    results.append(_check("1_diag_off_no_event", off.get(d.SESSION_LEDGER_KEY) is None))

    # 2. diagnostics on -> independent session + canonical
    s = _diag_session(draft_queue=["A"], draft_state={"queue": ["B"]})
    snap = d.record_queue_state_baseline_snapshot(None, s)
    results.append(
        _check(
            "2_diag_on_independent_reads",
            snap is not None
            and snap["session_queue"] == ["A"]
            and snap["canonical_queue"] == ["B"]
            and snap["queues_equal"] is False,
        )
    )

    # 3. empty/empty
    s = _diag_session()
    snap = d.build_queue_state_snapshot(s, phase=d.PHASE_BASELINE)
    results.append(
        _check(
            "3_empty_empty",
            snap["session_queue"] == []
            and snap["canonical_queue"] == []
            and snap["queues_equal"] is True,
        )
    )

    # 4. equal non-empty
    s = _diag_session(draft_queue=["A", "B"], draft_state={"queue": ["A", "B"]})
    snap = d.build_queue_state_snapshot(s, phase=d.PHASE_BASELINE)
    results.append(_check("4_equal_nonempty", snap["queues_equal"] is True and snap["session_queue_length"] == 2))

    # 5. mismatch visible
    results.append(_check("5_mismatch_visible", snap["queues_equal"] is True))  # placeholder fixed below
    s = _diag_session(draft_queue=["A"], draft_state={"queue": ["B"]})
    snap = d.build_queue_state_snapshot(s, phase=d.PHASE_BASELINE)
    results[-1] = _check("5_mismatch_visible", snap["queues_equal"] is False)

    # 6–8 Francisco counts
    s = _diag_session(draft_queue=["A"], draft_state={"queue": ["A"]})
    snap = d.build_queue_state_snapshot(s, phase=d.PHASE_BASELINE)
    results.append(_check("6_francisco_absent_0", snap["francisco_count_session"] == 0 and snap["francisco_count_canonical"] == 0))
    s = _diag_session(draft_queue=["Francisco Lindor"], draft_state={"queue": ["Francisco Lindor"]})
    snap = d.build_queue_state_snapshot(s, phase=d.PHASE_BASELINE)
    results.append(_check("7_francisco_once_1", snap["francisco_count_session"] == 1 and snap["francisco_count_canonical"] == 1))
    s = _diag_session(
        draft_queue=["Francisco Lindor", "Francisco Lindor"],
        draft_state={"queue": ["Francisco Lindor", "Francisco Lindor"]},
    )
    snap = d.build_queue_state_snapshot(s, phase=d.PHASE_BASELINE)
    results.append(_check("8_francisco_dup_2", snap["francisco_count_session"] == 2))

    # 9. lists copied
    orig = ["A"]
    s = _diag_session(draft_queue=orig, draft_state={"queue": list(orig)})
    snap = d.build_queue_state_snapshot(s, phase=d.PHASE_BASELINE)
    snap["session_queue"].append("MUT")
    results.append(_check("9_lists_copied", orig == ["A"] and "MUT" not in s["draft_queue"]))

    # 10–12 baseline no mutation / dirty / sync
    s = _diag_session(draft_queue=["A"], draft_state={"queue": ["A"]})
    before_q = list(s["draft_queue"])
    before_c = list(s["draft_state"]["queue"])
    dirty_before = s.get("_draft_queue_persist_dirty")
    d.record_queue_state_baseline_snapshot(None, s)
    results.append(_check("10_baseline_no_mutation", s["draft_queue"] == before_q))
    results.append(
        _check(
            "11_baseline_no_dirty",
            s.get("_draft_queue_persist_dirty") == dirty_before
            and s.get("draft_state_dirty") is None,
        )
    )
    results.append(_check("12_baseline_no_sync_canonical", s["draft_state"]["queue"] == before_c))

    # 13. works with NO Francisco latch
    s = _diag_session()
    s.pop("stage1_francisco_callback_only", None)
    snap = d.record_queue_state_baseline_snapshot(None, s)
    results.append(
        _check(
            "13_no_francisco_latch",
            snap is not None
            and snap.get("francisco_callback_only_required") is False
            and snap.get("latch_required") is False,
        )
    )

    # 14–16 SID / run / room
    results.append(_check("14_sid_retained", snap.get("streamlit_session_id") == "sid-fixture-001"))
    results.append(_check("15_run_retained", snap.get("diagnostic_run_id") == "run-fixture-001"))
    results.append(_check("16_room_retained", snap.get("room_id") == "ROOM1"))

    # 17. stale vs newer distinguishable
    s = _diag_session()
    a = d.record_queue_state_baseline_snapshot(None, s)
    s["draft_queue"] = ["X"]
    s["draft_state"] = {"queue": ["X"]}
    b = d.record_queue_state_baseline_snapshot(None, s)
    results.append(_check("17_stale_vs_newer", float(b["ts"]) >= float(a["ts"]) and b["session_queue"] == ["X"]))

    # 18. post snapshot after canonical sync (simulate product order)
    s = _diag_session()
    from draft_state import add_player_to_draft_queue

    after, added = add_player_to_draft_queue(s, "Francisco Lindor")
    # Ensure diag flags survive helper
    s["_solo_component_diag_enabled"] = True
    s["_solo_stage1_parent_boundary_probe"] = True
    s["_streamlit_session_id"] = "sid-fixture-001"
    s["_solo_stage1_run_id"] = "run-fixture-001"
    post = d.record_queue_state_post_mutation_snapshot(
        s, added=True, mutation_helper_entered=True, player_name="Francisco Lindor", event_id="e1"
    )
    results.append(
        _check(
            "18_post_after_canonical_sync",
            post is not None
            and post["phase"] == d.PHASE_POST_ADDED
            and post["session_queue"] == after
            and post["canonical_queue"] == list(s["draft_state"]["queue"])
            and post["queues_equal"] is True,
        )
    )

    # 19. successful add sees Francisco in both
    results.append(
        _check(
            "19_success_francisco_both",
            post["francisco_count_session"] == 1 and post["francisco_count_canonical"] == 1,
        )
    )

    # 20. no-add not mislabeled success
    s2 = _diag_session(draft_queue=["Francisco Lindor"], draft_state={"queue": ["Francisco Lindor"]})
    after2, added2 = add_player_to_draft_queue(s2, "Francisco Lindor")
    s2["_solo_component_diag_enabled"] = True
    s2["_solo_stage1_parent_boundary_probe"] = True
    s2["_streamlit_session_id"] = "sid-fixture-001"
    no_add = d.record_queue_state_post_mutation_snapshot(
        s2, added=bool(added2), mutation_helper_entered=True, player_name="Francisco Lindor"
    )
    results.append(
        _check(
            "20_no_add_not_success_phase",
            added2 is False
            and no_add is not None
            and no_add["phase"] == d.PHASE_POST_NO_ADD
            and no_add["phase"] != d.PHASE_POST_ADDED,
        )
    )

    # 21–22 no cleanup / force-save in diag module
    src = DIAG_PATH.read_text(encoding="utf-8")
    results.append(_check("21_no_cleanup_remove", "remove_player_from_user_draft_queue" not in src))
    results.append(_check("22_no_force_save", "flush_draft_queue_persist" not in src))

    # 23–24 Stage A / callback gate unchanged (source fingerprints)
    stage_a_src = (ROOT / "scripts" / "stage1_rec_fragment_exec_gate.py").read_text(encoding="utf-8")
    gate_src = (ROOT / "live_draft_francisco_callback_only_gate.py").read_text(encoding="utf-8")
    results.append(_check("23_stage_a_file_untouched_by_diag_import", "queue_state_snapshot_diag" not in stage_a_src))
    results.append(_check("24_callback_gate_untouched_by_diag_import", "queue_state_snapshot_diag" not in gate_src))

    # 25. historical SID rejected by runner
    bad = r.select_authoritative_baseline_queues(
        production_sid="sid-current",
        snapshots=[
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": "sid-historical",
                "session_queue": [],
                "canonical_queue": [],
                "ts": 1.0,
            }
        ],
    )
    results.append(_check("25_historical_sid_rejected", bad.get("baseline_known") is False and bad.get("rejection")))

    # 26. wrong room rejected where available
    wrong_room = r.select_authoritative_baseline_queues(
        production_sid="sid-fixture-001",
        room_id="OTHER",
        snapshots=[
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": "sid-fixture-001",
                "room_id": "ROOM1",
                "session_queue": ["A"],
                "canonical_queue": ["A"],
                "ts": 2.0,
            }
        ],
    )
    # Implementation keeps room when no match narrows to empty if room_id on snap differs —
    # with only ROOM1 snap and OTHER required, matched becomes empty after narrow.
    results.append(
        _check(
            "26_wrong_room_rejected",
            wrong_room.get("baseline_known") is False,
        )
    )

    # 27. stale baseline cannot act as post
    stale_post = r.select_authoritative_post_queues(
        production_sid="sid-x",
        snapshots=[
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": "sid-x",
                "session_queue": [],
                "canonical_queue": [],
                "ts": 9.0,
            }
        ],
    )
    results.append(
        _check(
            "27_stale_baseline_not_post",
            stale_post.get("rejection") in (
                "post_snapshot_missing_or_wrong_sid",
                "stale_baseline_cannot_act_as_post",
            ),
        )
    )

    # 28. UI cannot substitute for missing canonical
    ui_sub = r.select_authoritative_baseline_queues(
        production_sid="sid-y",
        snapshots=[],
        ui_queue=["Francisco Lindor"],
    )
    results.append(
        _check(
            "28_ui_not_canonical_substitute",
            ui_sub.get("canonical_unavailable") is True
            and ui_sub.get("ui_not_used_as_canonical") is True
            and ui_sub.get("canonical_queue") is None,
        )
    )

    # 29–30 missing canonical / session fail closed
    miss_c = r.extract_queues_from_snapshot({"session_queue": ["A"], "canonical_queue": None})
    miss_s = r.extract_queues_from_snapshot({"session_queue": None, "canonical_queue": ["A"]})
    results.append(_check("29_missing_canonical_fail", miss_c.get("canonical_unavailable") is True))
    results.append(_check("30_missing_session_fail", miss_s.get("session_unavailable") is True))

    # 31. both present/equal -> observability gate passes
    obs = r.assess_d664924_unlatched_queue_observability()
    results.append(
        _check(
            "31_observability_gate_passes",
            obs.get("ok") is True
            and obs.get("canonical_queue_observable_without_latch") is True
            and obs.get("session_queue_observable_without_latch") is True
            and obs.get("classification") is None,
        )
    )

    # Bridge untouched
    marker = (ROOT / "data" / "709269b3_reserved_bridge.txt").read_text(encoding="utf-8")
    results.append(
        _check(
            "32_709269b3_still_reserved",
            REAL_BRIDGE in marker and "NOT consumed" in marker and "RESERVED" in marker,
        )
    )

    failed = [x for x in results if not x.get("ok")]
    by = {x["name"]: x["ok"] for x in results}
    classifications = {
        "FRANCISCO_QUEUE_MUTATION_CANONICAL_QUEUE_OBSERVABILITY_PRODUCT_READY": bool(
            by.get("2_diag_on_independent_reads")
            and by.get("13_no_francisco_latch")
            and by.get("31_observability_gate_passes")
            and by.get("19_success_francisco_both")
        ),
        "FRANCISCO_QUEUE_MUTATION_QUEUE_STATE_SNAPSHOT_DIAGNOSTIC_READY": bool(
            by.get("14_sid_retained")
            and by.get("17_stale_vs_newer")
            and by.get("25_historical_sid_rejected")
            and by.get("27_stale_baseline_not_post")
            and by.get("20_no_add_not_success_phase")
        ),
        "FRANCISCO_QUEUE_MUTATION_CLOUD_QUEUE_STATE_OBSERVABILITY_RUNNER_READY": bool(
            by.get("28_ui_not_canonical_substitute")
            and by.get("29_missing_canonical_fail")
            and by.get("30_missing_session_fail")
            and by.get("31_observability_gate_passes")
        ),
    }
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "classifications": classifications,
        "production": False,
        "browser": False,
        "bridge_709269b3_reserved": bool(by.get("32_709269b3_still_reserved")),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
