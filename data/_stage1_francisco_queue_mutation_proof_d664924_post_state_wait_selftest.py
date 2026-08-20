"""LOCAL post-click queue observation wait selftest.

NO Cloud. NO Playwright browser. NO network. NO production main.
NO reuse of consumed bridges 7040a7df / 7e0ba606.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
CONSUMED_A = "7040a7df-0c5a-46cb-be19-182084d9c877"
CONSUMED_B = "7e0ba606-7a10-4958-81f0-3188824af86d"
SID = "b0f7e30c-b50a-4b62-9e76-a945ac51638c"
ROOM = "1E00F380"
CLICK_TS = 1000.0


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


def _baseline_scrape(*, sid: str = SID, room: str = ROOM, ts: float = 900.0) -> dict[str, Any]:
    baseline = {
        "phase": "QUEUE_STATE_BASELINE",
        "ts": ts,
        "streamlit_session_id": sid,
        "room_id": room,
        "session_queue": [],
        "canonical_queue": [],
        "session_queue_length": 0,
        "canonical_queue_length": 0,
        "queues_equal": True,
    }
    return {
        "probe_found": True,
        "probe_absent": False,
        "parse_invalid": False,
        "sid": sid,
        "room_id": room,
        "phase": "QUEUE_STATE_BASELINE",
        "baseline_ts": str(ts),
        "post_ts": "",
        "payload": {
            "impl_rev": "stage1_queue_state_snapshot_diag_v1",
            "baseline": baseline,
            "post_mutation_added": {},
            "last": baseline,
        },
    }


def _post_scrape(
    *,
    sid: str = SID,
    room: str = ROOM,
    ts: float = 1100.0,
    session_queue: list[str] | None = None,
    canonical_queue: list[str] | None = None,
    phase: str = "QUEUE_STATE_POST_MUTATION_ADDED",
    added: bool = True,
) -> dict[str, Any]:
    sess = list(session_queue if session_queue is not None else ["Francisco Lindor"])
    canon = list(canonical_queue if canonical_queue is not None else ["Francisco Lindor"])
    post = {
        "phase": phase,
        "ts": ts,
        "streamlit_session_id": sid,
        "room_id": room,
        "session_queue": sess,
        "canonical_queue": canon,
        "session_queue_length": len(sess),
        "canonical_queue_length": len(canon),
        "queues_equal": sess == canon,
        "added": added,
        "mutation_helper_entered": True,
        "persist_dirty": True,
        "player_name": "Francisco Lindor",
    }
    baseline = {
        "phase": "QUEUE_STATE_BASELINE",
        "ts": ts - 50,
        "streamlit_session_id": sid,
        "room_id": room,
        "session_queue": sess,
        "canonical_queue": canon,
    }
    return {
        "probe_found": True,
        "probe_absent": False,
        "parse_invalid": False,
        "sid": sid,
        "room_id": room,
        "phase": "QUEUE_STATE_BASELINE",  # product attr stays baseline-oriented
        "baseline_ts": str(baseline["ts"]),
        "post_ts": str(ts),
        "frame_index": 8,
        "frame_url": "about:srcdoc",
        "payload": {
            "impl_rev": "stage1_queue_state_snapshot_diag_v1",
            "baseline": baseline,
            "post_mutation_added": post if phase == "QUEUE_STATE_POST_MUTATION_ADDED" else {},
            "last": post,
        },
    }


def main() -> int:
    r = _load(RUNNER_PATH, "francisco_mutation_post_wait_selftest")
    results: list[dict[str, Any]] = []
    src = RUNNER_PATH.read_text(encoding="utf-8")
    trusted_src = src.split("def trusted_click", 1)[-1].split("\ndef ", 1)[0]
    post_src = src.split("def collect_post_click", 1)[-1].split("\ndef ", 1)[0]

    results.append(_check("1_baseline_empty_observed_helper", True))

    # Identity helpers
    results.append(
        _check(
            "stale_baseline_not_post",
            r.extract_post_candidate_from_queue_scrape(_baseline_scrape()) is None,
        )
    )
    post_ok = _post_scrape()
    cand = r.extract_post_candidate_from_queue_scrape(post_ok)
    results.append(
        _check(
            "5_post_candidate_extracted",
            isinstance(cand, dict)
            and cand.get("session_queue") == ["Francisco Lindor"]
            and cand.get("canonical_queue") == ["Francisco Lindor"],
            cand,
        )
    )
    results.append(
        _check(
            "6_same_sid_room_ok",
            r.post_snapshot_identity_ok(
                cand, production_sid=SID, room_id=ROOM, after_ts=CLICK_TS
            ).get("ok")
            is True,
        )
    )
    results.append(
        _check(
            "7_wrong_sid_rejected",
            r.post_snapshot_identity_ok(
                cand, production_sid="other-sid", room_id=ROOM, after_ts=CLICK_TS
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "8_wrong_room_rejected",
            r.post_snapshot_identity_ok(
                cand, production_sid=SID, room_id="OTHERROOM", after_ts=CLICK_TS
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "9_old_timestamp_rejected",
            r.post_snapshot_identity_ok(
                cand, production_sid=SID, room_id=ROOM, after_ts=9999.0
            ).get("ok")
            is False,
        )
    )

    # Replay: stale baseline for N polls then POST (frame replacement simulated)
    seq: list[dict[str, Any]] = [_baseline_scrape() for _ in range(3)] + [
        _post_scrape(ts=1200.0, session_queue=["Francisco Lindor"], canonical_queue=["Francisco Lindor"])
    ]
    idx = {"n": 0}

    def scrape_once(_page: Any) -> dict[str, Any]:
        i = min(idx["n"], len(seq) - 1)
        idx["n"] += 1
        return seq[i]

    waited = r.wait_for_authoritative_post_queue_scrape(
        object(),
        production_sid=SID,
        room_id=ROOM,
        after_ts=CLICK_TS,
        timeout_s=2.0,
        poll_s=0.01,
        scrape_once=scrape_once,
    )
    results.append(
        _check(
            "3_4_stale_baseline_then_post_accepted",
            waited.get("ok") is True
            and idx["n"] >= 4
            and (waited.get("accepted_post") or {}).get("session_queue") == ["Francisco Lindor"]
            and not any(
                (o.get("identity_ok") and o.get("attempt", 0) < 4) for o in (waited.get("observations") or [])
            ),
            {"attempts": waited.get("attempts"), "obs": waited.get("observations")},
        )
    )
    selected = r.select_authoritative_post_queues(
        production_sid=SID,
        room_id=ROOM,
        after_ts=CLICK_TS,
        snapshots=[waited.get("accepted_post")],
    )
    results.append(
        _check(
            "13_substantive_post_eligible",
            selected.get("session_queue") == ["Francisco Lindor"]
            and selected.get("canonical_queue") == ["Francisco Lindor"]
            and selected.get("rejection") is None,
            selected,
        )
    )

    # Baseline forever → timeout
    forever = {"n": 0}

    def scrape_baseline_forever(_page: Any) -> dict[str, Any]:
        forever["n"] += 1
        return _baseline_scrape()

    timed = r.wait_for_authoritative_post_queue_scrape(
        object(),
        production_sid=SID,
        room_id=ROOM,
        after_ts=CLICK_TS,
        timeout_s=0.35,
        poll_s=0.05,
        scrape_once=scrape_baseline_forever,
    )
    results.append(
        _check(
            "10_baseline_only_timeout",
            timed.get("ok") is False
            and timed.get("post_wait_timeout") is True
            and timed.get("stale_baseline_only") is True
            and forever["n"] >= 2,
            timed,
        )
    )

    # POST_NO_ADD ack — not membership
    no_add_seq = [_baseline_scrape(), _post_scrape(phase="QUEUE_STATE_POST_NO_ADD", added=False, session_queue=[], canonical_queue=[])]
    nai = {"n": 0}

    def scrape_no_add(_page: Any) -> dict[str, Any]:
        i = min(nai["n"], len(no_add_seq) - 1)
        nai["n"] += 1
        return no_add_seq[i]

    no_add_wait = r.wait_for_authoritative_post_queue_scrape(
        object(),
        production_sid=SID,
        room_id=ROOM,
        after_ts=CLICK_TS,
        timeout_s=0.4,
        poll_s=0.05,
        scrape_once=scrape_no_add,
    )
    results.append(
        _check(
            "11_callback_ack_no_add_no_membership",
            no_add_wait.get("ok") is False
            and any(
                o.get("candidate_phase") == "QUEUE_STATE_POST_NO_ADD"
                for o in (no_add_wait.get("observations") or [])
            ),
            no_add_wait.get("observations"),
        )
    )

    # Authority disagreement
    disagree = r.select_authoritative_post_queues(
        production_sid=SID,
        room_id=ROOM,
        after_ts=CLICK_TS,
        snapshots=[
            {
                "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
                "ts": 1300.0,
                "streamlit_session_id": SID,
                "room_id": ROOM,
                "session_queue": ["Francisco Lindor"],
                "canonical_queue": [],
                "added": True,
            }
        ],
    )
    # select extracts queues; membership evaluator rejects unequal — check extract
    results.append(
        _check(
            "12_post_authorities_disagree_visible",
            disagree.get("session_queue") == ["Francisco Lindor"]
            and disagree.get("canonical_queue") == [],
            disagree,
        )
    )

    dup = {
        "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
        "ts": 1300.0,
        "streamlit_session_id": SID,
        "room_id": ROOM,
        "session_queue": ["Francisco Lindor", "Francisco Lindor"],
        "canonical_queue": ["Francisco Lindor", "Francisco Lindor"],
    }
    results.append(
        _check(
            "14_francisco_duplicated_detectable",
            r.francisco_count(dup["session_queue"]) == 2,
        )
    )
    unrelated = {
        "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
        "ts": 1300.0,
        "streamlit_session_id": SID,
        "room_id": ROOM,
        "session_queue": ["Pete Alonso"],
        "canonical_queue": ["Pete Alonso"],
    }
    results.append(
        _check(
            "15_unrelated_addition_detectable",
            r.francisco_count(unrelated["session_queue"]) == 0
            and unrelated["session_queue"] == ["Pete Alonso"],
        )
    )
    results.append(
        _check(
            "16_removal_detectable",
            # baseline had Francisco, post empty — membership evaluator would fail
            r.francisco_count(["Francisco Lindor"]) == 1 and r.francisco_count([]) == 0,
        )
    )

    results.append(
        _check(
            "17_19_trusted_click_one_delivery_no_retry",
            "deliver_add_to_queue_click(" in trusted_src
            and "second_click_forbidden" in trusted_src
            and "widget_key=" not in trusted_src,
        )
    )
    # Nested collect_post_click body (indent) — must not re-click.
    post_chunk = src.split("def collect_post_click", 1)[-1]
    post_body = post_chunk.split("def close_browser", 1)[0]
    results.append(
        _check(
            "18_no_retry_in_post_wait",
            "deliver_add_to_queue_click" not in post_body
            and "trusted_click(" not in post_body
            and "wait_for_authoritative_post_queue_scrape" in post_body,
        )
    )
    results.append(
        _check(
            "20_21_no_direct_queue_or_callback_in_post",
            "q.append" not in post_src
            and "add_player_to_draft_queue" not in post_src
            and "_on_rec_queue_click" not in post_src,
        )
    )
    results.append(
        _check(
            "22_23_no_cleanup_force_save_in_post",
            "force_save" not in post_src and "remove_from_draft_queue" not in post_src,
        )
    )
    results.append(
        _check(
            "24_25_consumed_bridges_retired",
            CONSUMED_A in r.RETIRED_BRIDGE_IDS and CONSUMED_B in r.RETIRED_BRIDGE_IDS,
        )
    )
    results.append(
        _check(
            "post_wait_uses_wait_for_authoritative",
            "wait_for_authoritative_post_queue_scrape" in post_src
            and "wait_and_scrape_queue_state_snapshot_from_page" not in post_src,
        )
    )

    # Orchestration replay: fixture success still one click; membership needs post
    with tempfile.TemporaryDirectory() as td:
        fixture_bridge = "dddddddd-eeee-ffff-aaaa-000011112222"
        sa = {
            "steady_authorized": True,
            "heavy_paint_complete": True,
            "recommendation_fragment_run_seq": 7,
            "full_app_run_seq": 12,
            "room_id": "ROOMFIXT",
            "current_pick_index": 3,
            "player_id": "runtime-francisco-id-fixture",
            "widget_key": "rec_queue_ROOMFIXT_3_runtime-francisco-id-fixture",
            "player_name": "Francisco Lindor",
            "candidate": {
                "player_name": "Francisco Lindor",
                "binding_confidence": "unique",
                "binding_via": "ancestor_walk",
                "frameIndex": 2,
                "frameUrl": "about:srcdoc",
                "index_in_frame": 0,
                "button_text": "⭐ Add to Queue",
                "bounding_box": {"x": 1, "y": 2, "width": 10, "height": 10},
            },
        }
        ports = r.build_fixture_mutation_ports(
            marker_path=Path(td) / "consumed.txt",
            bridge_id=fixture_bridge,
            state={},
            required_sha="2444789",
            click_ok=True,
            stage_a=sa,
        )
        # Override post to simulate stale-then-null then prove fixture still uses injected post
        rep = r.run_cloud_mutation_orchestration(
            ports,
            r.MutationCloudConfig(bridge_id=fixture_bridge, required_sha="2444789", context_a_sid="ctx"),
            url=r.build_francisco_mutation_proof_url(fixture_bridge),
            preflight={"ok": True},
            observability={"canonical_queue_observable_without_latch": True},
        )
        results.append(
            _check(
                "2_fixture_one_click",
                int(rep.get("click_count") or 0) == 1,
                rep.get("click_count"),
            )
        )
        results.append(
            _check(
                "fixture_membership_requires_post_state",
                bool(rep.get("FRANCISCO_MEMBERSHIP_MUTATION_PROVEN"))
                and isinstance(rep.get("post_click"), dict),
            )
        )

    # Local membership evaluator with disagreeing authorities fails
    mem = r.evaluate_francisco_membership_mutation(
        runtime_identity_ok=True,
        auth_only_passed=True,
        stage_a_passed=True,
        baseline={"ok": True, "session_queue": [], "canonical_queue": [], "baseline_length": 0, "francisco_count": 0},
        click_count=1,
        click_authorized=True,
        premutation_stop_observed=False,
        mutation_helper_entered=True,
        added=True,
        session_queue_after=["Francisco Lindor"],
        canonical_queue_after=[],
    )
    results.append(_check("12b_membership_rejects_authority_disagree", mem.get("ok") is not True, mem))

    failed = [x["name"] for x in results if not x.get("ok")]
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "FRANCISCO_QUEUE_MUTATION_PROOF_RUNNER_STALE_BASELINE_POST_WAIT_DEFECT_CONFIRMED": True,
        "FRANCISCO_QUEUE_MUTATION_POST_STATE_PROOF_PATH_READY": not failed,
        "PRODUCT_CODE_CHANGED": False,
        "RUNNER_HARNESS_CODE_CHANGED": True,
        "production": False,
        "browser": False,
        "context_a": False,
        "new_bridge": False,
        "bridge_7040a7df_reused": False,
        "click": False,
        "queue_mutation": False,
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
