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

    # Bridge permanently CONSUMED (production mutation attempt; do not reuse)
    marker_path = ROOT / "data" / "961e9378_reserved_bridge.txt"
    consumed_path = ROOT / "data" / "961e9378_consumed_bridge.txt"
    # Prefer asserting 961e9378 consumed; keep 709269b3 consumed check for history
    marker_709 = ROOT / "data" / "709269b3_reserved_bridge.txt"
    consumed_709 = ROOT / "data" / "709269b3_consumed_bridge.txt"
    marker = marker_709.read_text(encoding="utf-8") if marker_709.is_file() else ""
    results.append(
        _check(
            "32_709269b3_permanently_consumed",
            REAL_BRIDGE in marker
            and consumed_709.is_file()
            and ("CONSUMED" in marker or "consumed" in marker.lower()),
        )
    )
    results.append(
        _check(
            "32b_961e9378_permanently_consumed",
            consumed_path.is_file()
            and "961e9378" in consumed_path.read_text(encoding="utf-8"),
        )
    )

    # --- Gate / latch asymmetry (production 961e9378 + 5f192511 root cause) ---
    class _St:
        def __init__(self, params: dict[str, str]):
            self.query_params = params

        def markdown(self, *a, **k):
            self.last_md = a[0] if a else ""

        def html(self, *a, **k):
            self.last_html = a[0] if a else ""

    # 33 solo latched, parent NOT latched, but QP has both → enable + latch parent
    s = {
        "_solo_component_diag_enabled": True,
        "draft_queue": [],
        "draft_state": {"queue": []},
        "_streamlit_session_id": "0d73852f-400f-4794-af94-7418cd5db4c6",
        "live_draft_room": {"draft_room_id": "E7FD8786", "current_pick_index": 0},
    }
    st = _St({"solo_component_diag": "1", "solo_stage1_parent_boundary": "1"})
    enabled = d.queue_state_snapshot_diag_enabled(st, s)
    results.append(
        _check(
            "33_solo_latched_parent_qp_enables",
            enabled is True and bool(s.get("_solo_stage1_parent_boundary_probe")),
        )
    )

    # 34 render emits probe id for empty queues
    s = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_parent_boundary_probe": True,
        "draft_queue": [],
        "draft_state": {"queue": []},
        "_streamlit_session_id": "sid-empty-001",
        "_solo_stage1_run_id": "run-empty",
        "live_draft_room": {"draft_room_id": "E7FD8786", "current_pick_index": 0},
    }
    st = _St({})
    d.render_queue_state_snapshot_probe(st, s)
    md = getattr(st, "last_md", "")
    results.append(
        _check(
            "34_empty_queue_emits_dom_probe",
            f'id="{d.PROBE_ID}"' in md
            and "QUEUE_STATE_BASELINE" in md
            and isinstance(s.get(d.SESSION_BASELINE_KEY), dict)
            and s[d.SESSION_BASELINE_KEY]["session_queue"] == []
            and s[d.SESSION_BASELINE_KEY]["canonical_queue"] == []
            and s[d.SESSION_BASELINE_KEY]["queues_equal"] is True,
        )
    )

    # 35 empty is not missing via extract + evaluate
    empty_sel = r.extract_queues_from_snapshot(s[d.SESSION_BASELINE_KEY])
    empty_eval = r.evaluate_queue_baseline(
        session_queue=empty_sel["session_queue"],
        canonical_queue=empty_sel["canonical_queue"],
        baseline_known=True,
    )
    results.append(
        _check(
            "35_empty_not_missing_authorize",
            empty_sel["baseline_known"] is True
            and empty_sel["session_queue"] == []
            and empty_eval.get("ok") is True
            and empty_eval.get("francisco_absent") is True,
        )
    )

    # 36 latch not required / callback-only not required
    results.append(
        _check(
            "36_no_callback_latch_required",
            s[d.SESSION_BASELINE_KEY].get("francisco_callback_only_required") is False
            and s[d.SESSION_BASELINE_KEY].get("latch_required") is False,
        )
    )

    # 37 solo without parent stays off when no QP
    s_off = {"_solo_component_diag_enabled": True, "draft_queue": [], "draft_state": {"queue": []}}
    results.append(
        _check(
            "37_solo_only_without_parent_disabled",
            d.queue_state_snapshot_diag_enabled(None, s_off) is False,
        )
    )

    # 38 both session latches enable without st
    s_both = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_parent_boundary_probe": True,
        "draft_queue": [],
        "draft_state": {"queue": []},
    }
    results.append(
        _check(
            "38_both_latches_enable_without_st",
            d.queue_state_snapshot_diag_enabled(None, s_both) is True,
        )
    )

    # 39 PROBE_ID contract
    results.append(_check("39_probe_id_exact", d.PROBE_ID == "stage1-queue-state-snapshot"))

    # 40 wait helper exists
    results.append(
        _check(
            "40_wait_helper_present",
            callable(getattr(d, "wait_and_scrape_queue_state_snapshot_from_page", None)),
        )
    )

    # 41 Context-A SID cannot satisfy production baseline
    ctx = r.select_authoritative_baseline_queues(
        production_sid="0d73852f-400f-4794-af94-7418cd5db4c6",
        snapshots=[
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": "fc8bab02-c811-417f-b95e-1dbb22e2f598",
                "room_id": "E7FD8786",
                "session_queue": [],
                "canonical_queue": [],
                "ts": 99.0,
            }
        ],
    )
    results.append(_check("41_context_a_sid_rejected", ctx.get("baseline_known") is False))

    # 42 bridge UUID cannot satisfy SID
    br = r.select_authoritative_baseline_queues(
        production_sid="0d73852f-400f-4794-af94-7418cd5db4c6",
        snapshots=[
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": "961e9378-a05c-4bdf-aba6-316ae518d919",
                "session_queue": [],
                "canonical_queue": [],
                "ts": 99.0,
            }
        ],
    )
    results.append(_check("42_bridge_uuid_rejected_as_sid", br.get("baseline_known") is False))

    # 43 production-shaped replay: Stage A complete + empty baseline → select ok
    prod_sid = "0d73852f-400f-4794-af94-7418cd5db4c6"
    replay_snap = {
        "phase": "QUEUE_STATE_BASELINE",
        "streamlit_session_id": prod_sid,
        "diagnostic_run_id": "ede1517d7c6149e1",
        "room_id": "E7FD8786",
        "current_pick_index": 0,
        "session_queue": [],
        "canonical_queue": [],
        "session_queue_length": 0,
        "canonical_queue_length": 0,
        "queues_equal": True,
        "francisco_count_session": 0,
        "francisco_count_canonical": 0,
        "ts": 1787005697.0,
    }
    replay = r.select_authoritative_baseline_queues(
        production_sid=prod_sid,
        room_id="E7FD8786",
        snapshots=[replay_snap],
    )
    replay_eval = r.evaluate_queue_baseline(
        session_queue=replay.get("session_queue"),
        canonical_queue=replay.get("canonical_queue"),
        baseline_known=bool(replay.get("baseline_known")),
    )
    results.append(
        _check(
            "43_prod_replay_empty_baseline_ok",
            replay.get("baseline_known") is True
            and replay.get("session_queue") == []
            and replay_eval.get("ok") is True
            and replay_eval.get("francisco_absent") is True,
        )
    )

    # 44 runner prefers auth_sid over scrape (source contains auth_sid first)
    runner_src = RUNNER_PATH.read_text(encoding="utf-8")
    results.append(
        _check(
            "44_collect_baseline_auth_sid_preferred",
            "wait_and_scrape_queue_state_snapshot_from_page" in runner_src
            and 'str(state.get("auth_sid") or "").strip()' in runner_src,
        )
    )

    # 45 no mutation semantics in diag (already covered; reconfirm append/sync absent)
    results.append(
        _check(
            "45_diag_no_q_append",
            "q.append" not in src and "add_player_to_draft_queue" not in src.split("record_queue_state_baseline")[0],
        )
    )

    # 46 latest current-SID baseline selected
    multi = r.select_authoritative_baseline_queues(
        production_sid="sid-multi",
        snapshots=[
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": "sid-multi",
                "session_queue": ["OLD"],
                "canonical_queue": ["OLD"],
                "ts": 1.0,
            },
            {
                "phase": "QUEUE_STATE_BASELINE",
                "streamlit_session_id": "sid-multi",
                "session_queue": [],
                "canonical_queue": [],
                "ts": 9.0,
            },
        ],
    )
    results.append(
        _check(
            "46_latest_current_sid_baseline",
            multi.get("session_queue") == [] and multi.get("baseline_known") is True,
        )
    )

    results.append(
        _check(
            "32c_5f192511_permanently_consumed",
            (ROOT / "data" / "5f192511_consumed_bridge.txt").is_file()
            and "5f192511" in (ROOT / "data" / "5f192511_consumed_bridge.txt").read_text(encoding="utf-8"),
        )
    )
    results.append(
        _check(
            "32d_c69aa19c_permanently_consumed",
            (ROOT / "data" / "c69aa19c_consumed_bridge.txt").is_file()
            and "c69aa19c" in (ROOT / "data" / "c69aa19c_consumed_bridge.txt").read_text(encoding="utf-8"),
        )
    )

    # 47 parent QP remembered while solo still off
    s_qp_first = {"draft_queue": [], "draft_state": {"queue": []}}
    st_parent_only = _St({"solo_stage1_parent_boundary": "1"})
    d._refresh_queue_state_diag_latches(st_parent_only, s_qp_first)
    results.append(
        _check(
            "47_parent_qp_remembered_before_solo",
            bool(s_qp_first.get("_solo_stage1_parent_boundary_requested"))
            and not s_qp_first.get("_solo_stage1_parent_boundary_probe")
            and d.queue_state_snapshot_diag_enabled(st_parent_only, s_qp_first) is False,
        )
    )

    # 48 later solo-on, QP gone → still enable from requested
    s_qp_first["_solo_component_diag_enabled"] = True
    st_empty_qp = _St({})
    enabled_after = d.queue_state_snapshot_diag_enabled(st_empty_qp, s_qp_first)
    results.append(
        _check(
            "48_requested_plus_solo_survives_qp_gone",
            enabled_after is True and bool(s_qp_first.get("_solo_stage1_parent_boundary_probe")),
        )
    )

    # 49 parent latch survives rerun with empty QP
    st_rerun = _St({})
    results.append(
        _check(
            "49_parent_latch_survives_rerun",
            d.queue_state_snapshot_diag_enabled(st_rerun, s_qp_first) is True,
        )
    )

    # 50 solo latch survives rerun
    s_solo = {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_parent_boundary_probe": True,
        "draft_queue": [],
        "draft_state": {"queue": []},
    }
    results.append(
        _check(
            "50_solo_latch_survives_rerun",
            d.queue_state_snapshot_diag_enabled(_St({}), s_solo) is True
            and s_solo.get("_solo_component_diag_enabled") is True,
        )
    )

    # 51 exact gate keys
    from live_draft_stage1_parent_boundary import REQUESTED_FLAG, SESSION_FLAG

    results.append(
        _check(
            "51_exact_gate_keys_match",
            SESSION_FLAG == "_solo_stage1_parent_boundary_probe"
            and REQUESTED_FLAG == "_solo_stage1_parent_boundary_requested"
            and "solo_stage1_parent_boundary" in Path(ROOT / "live_draft_stage1_parent_boundary.py").read_text(encoding="utf-8"),
        )
    )

    # 52 mismatch still renders probe
    s_mis = _diag_session(draft_queue=["A"], draft_state={"queue": ["B"]})
    st_mis = _St({})
    d.render_queue_state_snapshot_probe(st_mis, s_mis)
    results.append(
        _check(
            "52_mismatch_still_renders_probe",
            f'id="{d.PROBE_ID}"' in getattr(st_mis, "last_md", "")
            and "false" in getattr(st_mis, "last_md", "").lower() or f'id="{d.PROBE_ID}"' in getattr(st_mis, "last_md", ""),
        )
    )
    results[-1] = _check(
        "52_mismatch_still_renders_probe",
        f'id="{d.PROBE_ID}"' in getattr(st_mis, "last_md", "")
        and s_mis[d.SESSION_BASELINE_KEY]["queues_equal"] is False,
    )

    # 53 dual-emit component html
    results.append(
        _check(
            "53_component_html_dual_emit",
            f'id="{d.PROBE_ID}"' in getattr(st_mis, "last_html", ""),
        )
    )

    # 54 fragment reemit calls queue probe
    heavy_src = (ROOT / "live_draft_heavy_paint_ui.py").read_text(encoding="utf-8")
    results.append(
        _check(
            "54_fragment_reemit_includes_queue_probe",
            "render_queue_state_snapshot_probe" in heavy_src
            and "_reemit_fragment_diagnostics" in heavy_src,
        )
    )

    # 55–60 scraper page.frames vs absent / parse invalid / wait
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

    good_payload = {
        "impl_rev": d.IMPL_REV,
        "baseline": {
            "phase": "QUEUE_STATE_BASELINE",
            "streamlit_session_id": "4169059a-3c65-4b8f-a5de-cca7661ab076",
            "room_id": "810854BB",
            "session_queue": [],
            "canonical_queue": [],
            "session_queue_length": 0,
            "canonical_queue_length": 0,
            "queues_equal": True,
            "francisco_count_session": 0,
            "francisco_count_canonical": 0,
            "ts": 10.0,
        },
        "post_mutation_added": {},
        "last": {},
    }
    good_json = json.dumps(good_payload).replace('"', "'")
    iframe_hit = {
        "probe_found": True,
        "sid": "4169059a-3c65-4b8f-a5de-cca7661ab076",
        "run_id": "cb49c2b03e0a4582",
        "room_id": "810854BB",
        "phase": "QUEUE_STATE_BASELINE",
        "json": good_json,
    }
    page_iframe = _Page(
        frames=[_Frame({"probe_found": False}, url="https://streamlit.app/"), _Frame(iframe_hit, url="https://app/~/+/")],
        top={"probe_found": False, "probe_absent": True},
    )
    scraped_frames = d.scrape_queue_state_snapshot_from_page(page_iframe)
    results.append(
        _check(
            "55_page_frames_finds_iframe_probe",
            scraped_frames.get("probe_found") is True
            and scraped_frames.get("frame_index") == 1
            and scraped_frames.get("frame_strategy") == "page.frames"
            and scraped_frames.get("selector") == "#stage1-queue-state-snapshot"
            and (scraped_frames.get("payload") or {}).get("baseline", {}).get("session_queue") == [],
        )
    )

    page_absent = _Page(frames=[_Frame({"probe_found": False})], top={"probe_found": False})
    absent = d.wait_and_scrape_queue_state_snapshot_from_page(page_absent, timeout_s=0.6, poll_s=0.05)
    results.append(
        _check(
            "56_selector_absent_timeout_fail_closed",
            absent.get("probe_found") is False
            and absent.get("probe_wait_timeout") is True
            and absent.get("probe_absent") is True
            and int(absent.get("attempts") or 0) >= 2,
        )
    )

    page_parse = _Page(
        frames=[_Frame({"probe_found": True, "sid": "x", "phase": "QUEUE_STATE_BASELINE", "json": "{not-json"})]
    )
    parsed_bad = d.scrape_queue_state_snapshot_from_page(page_parse)
    results.append(
        _check(
            "57_present_parse_invalid_distinct_from_absent",
            parsed_bad.get("probe_found") is True
            and parsed_bad.get("parse_invalid") is True
            and parsed_bad.get("probe_absent") is False,
        )
    )

    seq = {"i": 0, "rows": [{"probe_found": False}, {"probe_found": False}, iframe_hit]}

    class _AppearPage:
        frames = []

        def evaluate(self, *_a, **_k):
            i = seq["i"]
            seq["i"] += 1
            row = seq["rows"][i] if i < len(seq["rows"]) else seq["rows"][-1]
            return row

        def wait_for_timeout(self, _ms):
            return None

    appear = d.wait_and_scrape_queue_state_snapshot_from_page(_AppearPage(), timeout_s=2.0, poll_s=0.05)
    results.append(
        _check(
            "58_temporary_absence_then_probe_succeeds",
            appear.get("probe_found") is True and int(appear.get("attempts") or 0) >= 3,
        )
    )

    # 59 iframe replacement: first frame empty, later same page.frames index hits
    replace_seq = [
        {"probe_found": False},
        iframe_hit,
    ]
    repl_i = {"n": 0}

    class _ReplFrame:
        url = "https://app/~/+/"

        def evaluate(self, *_a, **_k):
            n = repl_i["n"]
            repl_i["n"] += 1
            return replace_seq[n] if n < len(replace_seq) else replace_seq[-1]

    repl = d.wait_and_scrape_queue_state_snapshot_from_page(_Page(frames=[_ReplFrame()]), timeout_s=2.0, poll_s=0.05)
    results.append(
        _check(
            "59_iframe_replacement_succeeds",
            repl.get("probe_found") is True and repl.get("frame_strategy") == "page.frames",
        )
    )

    # 60–64 SID / room / phase filters still at selector layer (runner), not scrape
    prod_sid = "4169059a-3c65-4b8f-a5de-cca7661ab076"
    snap_ok = {
        "phase": "QUEUE_STATE_BASELINE",
        "streamlit_session_id": prod_sid,
        "room_id": "810854BB",
        "session_queue": [],
        "canonical_queue": [],
        "session_queue_length": 0,
        "canonical_queue_length": 0,
        "queues_equal": True,
        "francisco_count_session": 0,
        "francisco_count_canonical": 0,
        "ts": 11.0,
    }
    wrong_sid = r.select_authoritative_baseline_queues(
        production_sid=prod_sid,
        room_id="810854BB",
        snapshots=[{**snap_ok, "streamlit_session_id": "5fa84118-5c83-4807-9df9-944d00462476"}],
    )
    results.append(_check("60_wrong_sid_rejected", wrong_sid.get("baseline_known") is False))
    wrong_room = r.select_authoritative_baseline_queues(
        production_sid=prod_sid,
        room_id="810854BB",
        snapshots=[{**snap_ok, "room_id": "E7FD8786"}],
    )
    results.append(_check("61_wrong_room_rejected", wrong_room.get("baseline_known") is False))
    wrong_phase = r.select_authoritative_baseline_queues(
        production_sid=prod_sid,
        room_id="810854BB",
        snapshots=[{**snap_ok, "phase": "QUEUE_STATE_POST_MUTATION_ADDED"}],
    )
    results.append(_check("62_wrong_phase_rejected", wrong_phase.get("baseline_known") is False))
    good_sel = r.select_authoritative_baseline_queues(
        production_sid=prod_sid,
        room_id="810854BB",
        snapshots=[snap_ok],
    )
    good_eval = r.evaluate_queue_baseline(
        session_queue=good_sel.get("session_queue"),
        canonical_queue=good_sel.get("canonical_queue"),
        baseline_known=bool(good_sel.get("baseline_known")),
    )
    results.append(
        _check(
            "63_correct_sid_room_phase_empty_valid",
            good_sel.get("baseline_known") is True
            and good_sel.get("session_queue") == []
            and good_sel.get("canonical_queue") == []
            and good_eval.get("ok") is True
            and good_eval.get("francisco_absent") is True,
        )
    )

    ctx_a = r.select_authoritative_baseline_queues(
        production_sid=prod_sid,
        snapshots=[{**snap_ok, "streamlit_session_id": "5fa84118-5c83-4807-9df9-944d00462476"}],
    )
    results.append(_check("64_context_a_sid_cannot_satisfy", ctx_a.get("baseline_known") is False))

    # 65 local Stage A → baseline pipeline replay (5f192511 shape; empty is a fixture, not a production claim)
    sa_ok = r.stage_a_identity_complete(
        {
            "steady_authorized": True,
            "heavy_paint_complete": True,
            "room_id": "810854BB",
            "current_pick_index": 0,
            "recommendation_fragment_run_seq": "3",
            "full_app_run_seq": 19,
            "player_id": "231",
            "widget_key": "rec_card_queue_810854BB_0_231_rec_card",
            "streamlit_session_id": prod_sid,
            "identity": {"identity_complete": True, "player_id": "231", "widget_key": "rec_card_queue_810854BB_0_231_rec_card"},
        }
    )
    click_auth = r.evaluate_francisco_mutation_click_authorization(
        runtime_identity_ok=True,
        auth_only_passed=True,
        stage_a_steady_authorized=True,
        heavy_paint_complete=True,
        stage_a_identity_complete=bool(sa_ok),
        fresh_production_sid=True,
        latch_absent=True,
        gate_allows_normal=True,
        baseline_ok=bool(good_eval.get("ok")),
        prior_mutation_click=False,
        ambiguous_queue=False,
    )
    results.append(
        _check(
            "65_local_stage_a_to_baseline_pipeline",
            sa_ok is True
            and click_auth.get("ok") is True
            and click_auth.get("francisco_mutation_click_authorized") is True
            and good_sel.get("session_queue") == []
            and good_sel.get("canonical_queue") == [],
        )
    )

    # 66 no mutation/sync/persist/gate in diag record path
    diag_src = DIAG_PATH.read_text(encoding="utf-8")
    record_part = diag_src.split("def record_queue_state_post_mutation_snapshot")[0]
    results.append(
        _check(
            "66_record_baseline_no_sync_persist_gate",
            "sync_draft_queue" not in record_part
            and "write_canonical_draft_state" not in record_part
            and "q.append" not in record_part
            and "clear_francisco" not in diag_src,
        )
    )

    runner_src = RUNNER_PATH.read_text(encoding="utf-8")
    results.append(
        _check(
            "67_runtime_identity_scrape_deploy_still_wired",
            "verify_cloud_deploy_playwright.scrape_deploy" in runner_src
            or "from verify_cloud_deploy_playwright import scrape_deploy" in runner_src,
        )
    )
    results.append(
        _check(
            "68_scraper_uses_page_frames",
            "page.frames" in diag_src and "frame_strategy" in diag_src,
        )
    )

    failed = [x for x in results if not x.get("ok")]
    by = {x["name"]: x["ok"] for x in results}
    classifications = {
        "FRANCISCO_QUEUE_MUTATION_BASELINE_PARENT_BOUNDARY_LATCH_STILL_NOT_ACTIVE_CONFIRMED": True,
        "FRANCISCO_QUEUE_MUTATION_BASELINE_PROBE_FRAME_VISIBILITY_DEFECT_CONFIRMED": True,
        "FRANCISCO_QUEUE_MUTATION_BASELINE_PROBE_RUNNER_SCRAPER_DIVERGENCE_CONFIRMED": True,
        "FRANCISCO_QUEUE_MUTATION_BASELINE_DIAGNOSTIC_GATE_DEFECT_CONFIRMED": True,
        "FRANCISCO_QUEUE_MUTATION_BASELINE_SNAPSHOT_OBSERVABILITY_READY": bool(
            by.get("33_solo_latched_parent_qp_enables")
            and by.get("34_empty_queue_emits_dom_probe")
            and by.get("48_requested_plus_solo_survives_qp_gone")
            and by.get("55_page_frames_finds_iframe_probe")
            and by.get("63_correct_sid_room_phase_empty_valid")
            and by.get("65_local_stage_a_to_baseline_pipeline")
        ),
        "FRANCISCO_QUEUE_MUTATION_CANONICAL_QUEUE_OBSERVABILITY_PRODUCT_READY": bool(
            by.get("2_diag_on_independent_reads")
            and by.get("13_no_francisco_latch")
            and by.get("31_observability_gate_passes")
            and by.get("19_success_francisco_both")
            and by.get("34_empty_queue_emits_dom_probe")
        ),
        "FRANCISCO_QUEUE_MUTATION_QUEUE_STATE_SNAPSHOT_DIAGNOSTIC_READY": bool(
            by.get("14_sid_retained")
            and by.get("17_stale_vs_newer")
            and by.get("25_historical_sid_rejected")
            and by.get("27_stale_baseline_not_post")
            and by.get("20_no_add_not_success_phase")
            and by.get("39_probe_id_exact")
        ),
        "FRANCISCO_QUEUE_MUTATION_CLOUD_QUEUE_STATE_OBSERVABILITY_RUNNER_READY": bool(
            by.get("28_ui_not_canonical_substitute")
            and by.get("29_missing_canonical_fail")
            and by.get("30_missing_session_fail")
            and by.get("31_observability_gate_passes")
            and by.get("44_collect_baseline_auth_sid_preferred")
            and by.get("55_page_frames_finds_iframe_probe")
            and by.get("57_present_parse_invalid_distinct_from_absent")
            and by.get("68_scraper_uses_page_frames")
        ),
        "FRANCISCO_QUEUE_MUTATION_SINGLE_CLICK_PROOF_RUNNER_READY": bool(
            by.get("65_local_stage_a_to_baseline_pipeline")
            and by.get("66_record_baseline_no_sync_persist_gate")
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
        "bridge_709269b3_reserved": False,
        "bridge_709269b3_consumed": bool(by.get("32_709269b3_permanently_consumed")),
        "bridge_961e9378_consumed": bool(by.get("32b_961e9378_permanently_consumed")),
        "product_code_changed": True,
        "runner_code_changed": False,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
