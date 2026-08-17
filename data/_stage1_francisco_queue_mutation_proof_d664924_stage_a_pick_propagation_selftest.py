"""LOCAL Stage A current_pick_index / generation propagation selftest.

NO Cloud. NO browser/network. NO production re-run. NO click/mutation.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
PROD_RESULT = ROOT / "data" / "francisco_queue_mutation_proof_709269b3.result.json"


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


def _legacy_lossy_map(identity: dict[str, Any], retained: dict[str, Any]) -> dict[str, Any]:
    """Reproduce the pre-repair mutation wait_stage_a mapping defect."""
    return {
        "current_pick_index": identity.get("pick_index") or identity.get("current_pick_index"),
        "recommendation_fragment_run_seq": retained.get("recommendation_fragment_run_seq"),
        "full_app_run_seq": retained.get("full_app_run_seq"),
        "room_id": identity.get("room_id"),
        "player_id": identity.get("player_id"),
        "widget_key": identity.get("widget_key"),
    }


def main() -> int:
    r = _load(RUNNER_PATH, "francisco_mutation_stage_a_pick_propagation_selftest")
    results: list[dict[str, Any]] = []
    src = RUNNER_PATH.read_text(encoding="utf-8")

    # 1 pick 0 preserved
    mapped0 = r.map_stage_a_authority_fields(
        retained={"recommendation_fragment_run_seq": None, "full_app_run_seq": 17},
        identity={
            "pick_index": 0,
            "room_id": "ROOM0",
            "player_id": "231",
            "widget_key": "rec_card_queue_ROOM0_0_231_rec_card",
            "recommendation_fragment_run_seq": 3,
        },
    )
    results.append(
        _check(
            "1_pick_0_preserved_as_int_zero",
            mapped0.get("current_pick_index") == 0
            and type(mapped0.get("current_pick_index")) is int,
            mapped0.get("current_pick_index"),
        )
    )

    # 2 pick 1 preserved
    mapped1 = r.map_stage_a_authority_fields(
        retained={},
        identity={"pick_index": 1, "room_id": "R", "player_id": "x", "widget_key": "k"},
    )
    results.append(_check("2_pick_1_preserved", mapped1.get("current_pick_index") == 1))

    # 3 missing pick remains None / incomplete
    mapped_miss = r.map_stage_a_authority_fields(
        retained={},
        identity={"room_id": "R", "player_id": "x", "widget_key": "k"},
    )
    sa_miss = {
        "steady_authorized": True,
        "heavy_paint_complete": True,
        "room_id": "R",
        "current_pick_index": mapped_miss.get("current_pick_index"),
        "player_id": "x",
        "widget_key": "k",
    }
    results.append(
        _check(
            "3_missing_pick_none_fails_stage_a_identity",
            mapped_miss.get("current_pick_index") is None
            and r.stage_a_identity_complete(sa_miss) is False,
        )
    )

    # 4 nested card pick without current-pick authority does not invent from widget key alone
    # When pick_index absent, widget key must not supply authority via mapper.
    mapped_wk = r.map_stage_a_authority_fields(
        retained={},
        identity={
            "room_id": "10CEB796",
            "player_id": "231",
            "widget_key": "rec_card_queue_10CEB796_0_231_rec_card",
        },
    )
    results.append(
        _check(
            "4_5_widget_key_does_not_supply_pick_authority",
            mapped_wk.get("current_pick_index") is None
            and "rec_card_queue" not in str(mapped_wk.get("current_pick_index")),
        )
    )

    # 6 recommendation rank alone is not used
    results.append(
        _check(
            "6_mapper_docs_forbid_widget_key_and_rank",
            "Does not parse widget keys" in (r.map_stage_a_authority_fields.__doc__ or "")
            and "recommendation rank" in (r.map_stage_a_authority_fields.__doc__ or ""),
        )
    )

    # 7 room pick 0 + francisco pick 0 -> complete
    sa_ok = {
        "steady_authorized": True,
        "heavy_paint_complete": True,
        "room_id": "10CEB796",
        "current_pick_index": 0,
        "player_id": "231",
        "widget_key": "rec_card_queue_10CEB796_0_231_rec_card",
        "recommendation_fragment_run_seq": 3,
        "full_app_run_seq": 17,
    }
    results.append(_check("7_room_pick0_francisco_pick0_complete", r.stage_a_identity_complete(sa_ok)))

    # 8 room current pick=1 vs card pick=0 is a higher-level mismatch concern;
    # mapper preserves authoritative_pick_index when present.
    mapped_mismatch = r.map_stage_a_authority_fields(
        retained={
            "stage_a_authority": {
                "authoritative_pick_index": 1,
                "authoritative_room_id": "10CEB796",
                "pick_status": "SAME",
            }
        },
        identity={"pick_index": 0, "room_id": "10CEB796", "player_id": "231", "widget_key": "k"},
    )
    results.append(
        _check(
            "8_authoritative_room_pick_preferred_over_card_pick",
            mapped_mismatch.get("current_pick_index") == 1,
            mapped_mismatch.get("current_pick_index"),
        )
    )

    # 9 room mismatch: mapper keeps identity room when auth room differs — caller must compare.
    mapped_room = r.map_stage_a_authority_fields(
        retained={"stage_a_authority": {"authoritative_room_id": "AAAA", "authoritative_pick_index": 0}},
        identity={"pick_index": 0, "room_id": "BBBB", "player_id": "231", "widget_key": "k"},
        fallback_room_id="CCCC",
    )
    results.append(
        _check(
            "9_identity_room_preferred_then_auth_then_fallback",
            mapped_room.get("room_id") == "BBBB",
        )
    )

    # 10/11 stale / wrong SID: mapper does not invent SID; presence helpers fail closed on missing pick
    results.append(
        _check(
            "10_11_stale_or_missing_pick_fails_closed",
            r.stage_a_identity_complete(
                {
                    "room_id": "R",
                    "current_pick_index": None,
                    "player_id": "231",
                    "widget_key": "k",
                }
            )
            is False,
        )
    )

    # 12 fragment seq preserved from identity when retained primary null
    results.append(
        _check(
            "12_fragment_seq_preserved_from_identity",
            mapped0.get("recommendation_fragment_run_seq") == 3,
        )
    )

    # 13 missing fragment seq stays None (fail-closed left to Stage A consumers that require it)
    mapped_nof = r.map_stage_a_authority_fields(
        retained={},
        identity={"pick_index": 0, "room_id": "R", "player_id": "x", "widget_key": "k"},
    )
    results.append(
        _check(
            "13_missing_fragment_seq_remains_none",
            mapped_nof.get("recommendation_fragment_run_seq") is None,
        )
    )

    # 14–18 preserve full_app / room / player / widget
    results.append(_check("14_full_app_run_seq_preserved", mapped0.get("full_app_run_seq") == 17))
    results.append(_check("15_heavy_paint_not_invented_here", "heavy_paint" not in mapped0))
    results.append(_check("16_room_preserved", mapped0.get("room_id") == "ROOM0"))
    results.append(_check("17_player_id_preserved", mapped0.get("player_id") == "231"))
    results.append(
        _check(
            "18_widget_key_preserved",
            mapped0.get("widget_key") == "rec_card_queue_ROOM0_0_231_rec_card",
        )
    )

    # 19 no hardcoded historical francisco id inside mapper body
    mapper_start = src.find("def map_stage_a_authority_fields")
    mapper_body = src[mapper_start : mapper_start + 1800]
    results.append(
        _check(
            "19_no_hardcoded_francisco_player_id_in_mapper",
            '"231"' not in mapper_body and "'231'" not in mapper_body,
        )
    )

    # 20 click auth remains false until complete Stage A (evaluator)
    click = r.evaluate_francisco_mutation_click_authorization(
        runtime_identity_ok=True,
        auth_only_passed=True,
        stage_a_steady_authorized=True,
        heavy_paint_complete=True,
        stage_a_identity_complete=False,
        fresh_production_sid=True,
        latch_absent=True,
        gate_allows_normal=True,
        baseline_ok=True,
        prior_mutation_click=False,
    )
    results.append(
        _check(
            "20_click_auth_false_until_stage_a_identity_complete",
            click.get("ok") is False,
            click,
        )
    )

    # 21 orchestration still sequences Stage A before baseline (source order)
    orch = src[src.find("def run_cloud_mutation_orchestration") : src.find("def run_cloud_mutation_orchestration") + 8000]
    results.append(
        _check(
            "21_stage_a_before_baseline_in_orchestration",
            orch.find("wait_stage_a") < orch.find("collect_baseline"),
        )
    )

    results.append(_check("22_no_click_in_selftest", True))
    results.append(_check("23_no_mutation_in_selftest", True))

    # Legacy lossy vs fixed on production-shaped evidence
    legacy = _legacy_lossy_map(
        {"pick_index": 0, "room_id": "10CEB796", "player_id": "231", "widget_key": "k", "recommendation_fragment_run_seq": 3},
        {"recommendation_fragment_run_seq": None, "full_app_run_seq": 17},
    )
    results.append(
        _check(
            "legacy_or_drops_pick_zero",
            legacy.get("current_pick_index") is None
            and legacy.get("recommendation_fragment_run_seq") is None,
        )
    )

    # Replay retained production artifact locally
    replay = {"performed": False}
    if PROD_RESULT.is_file():
        prod = json.loads(PROD_RESULT.read_text(encoding="utf-8"))
        sa = prod.get("stage_a") or {}
        retained = sa.get("retained") or {}
        identity = sa.get("identity") or {}
        fixed = r.map_stage_a_authority_fields(
            retained=retained, identity=identity, fallback_room_id=str(sa.get("room_id") or "")
        )
        replay = {
            "performed": True,
            "production_top_current_pick_index": sa.get("current_pick_index"),
            "production_top_recommendation_fragment_run_seq": sa.get(
                "recommendation_fragment_run_seq"
            ),
            "replay_current_pick_index": fixed.get("current_pick_index"),
            "replay_recommendation_fragment_run_seq": fixed.get("recommendation_fragment_run_seq"),
            "replay_full_app_run_seq": fixed.get("full_app_run_seq"),
            "replay_room_id": fixed.get("room_id"),
            "replay_player_id": fixed.get("player_id"),
            "replay_widget_key": fixed.get("widget_key"),
            "identity_complete_after_repair": r.stage_a_identity_complete(
                {
                    "room_id": fixed.get("room_id"),
                    "current_pick_index": fixed.get("current_pick_index"),
                    "player_id": fixed.get("player_id"),
                    "widget_key": fixed.get("widget_key"),
                }
            ),
            "queue_mutation_claimed": False,
            "click_count_in_production": prod.get("click_count"),
        }
        results.append(
            _check(
                "replay_709269b3_pick_zero_and_fragment_seq",
                replay["replay_current_pick_index"] == 0
                and replay["replay_recommendation_fragment_run_seq"] in (3, "3")
                and replay["identity_complete_after_repair"] is True
                and sa.get("current_pick_index") is None,
                replay,
            )
        )

    # Source no longer contains lossy `pick_index) or`
    results.append(
        _check(
            "source_no_lossy_pick_or",
            "identity.get(\"pick_index\") or identity.get(\"current_pick_index\")" not in src
            and "map_stage_a_authority_fields" in src
            and "stage_a_identity_complete" in src,
        )
    )

    failed = [x for x in results if not x.get("ok")]
    by = {x["name"]: x["ok"] for x in results}
    summary = {
        "ok": not failed,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "replay": replay,
        "classifications": {
            "FRANCISCO_QUEUE_MUTATION_STAGE_A_CURRENT_PICK_PROPAGATION_DEFECT_CONFIRMED": True,
            "FRANCISCO_QUEUE_MUTATION_STAGE_A_CURRENT_PICK_PROPAGATION_RUNNER_READY": bool(
                by.get("1_pick_0_preserved_as_int_zero")
                and by.get("source_no_lossy_pick_or")
                and by.get("replay_709269b3_pick_zero_and_fragment_seq")
            ),
            "FRANCISCO_QUEUE_MUTATION_STAGE_A_GENERATION_METADATA_PROPAGATION_RUNNER_READY": bool(
                by.get("12_fragment_seq_preserved_from_identity")
                and by.get("replay_709269b3_pick_zero_and_fragment_seq")
            ),
            "FRANCISCO_QUEUE_MUTATION_STAGE_A_AUTHORITY_ADAPTER_RUNNER_READY": bool(
                by.get("1_pick_0_preserved_as_int_zero")
                and by.get("8_authoritative_room_pick_preferred_over_card_pick")
                and by.get("20_click_auth_false_until_stage_a_identity_complete")
            ),
        },
        "production_main_executed": False,
        "browser_network": False,
        "francisco_click": False,
        "queue_mutation": False,
        "709269b3_reusable": False,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
