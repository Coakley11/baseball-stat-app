"""Deterministic LOCAL selftest: Francisco normal queue-mutation proof runner.

NO Cloud. NO Playwright. NO network. NO clicks. NO queue mutation.
Does NOT call runner main() against production.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
CALLBACK_RUNNER = ROOT / "data" / "_francisco_callback_only_cloud_proof_d664924.py"


def _load(path: Path, name: str):
    import sys

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


def _baseline(r, session=None, canonical=None, known=True):
    return r.evaluate_queue_baseline(
        session_queue=session if session is not None else [],
        canonical_queue=canonical if canonical is not None else (session if session is not None else []),
        baseline_known=known,
    )


def _auth_click(r, **over):
    base = dict(
        runtime_identity_ok=True,
        auth_only_passed=True,
        stage_a_steady_authorized=True,
        heavy_paint_complete=True,
        stage_a_identity_complete=True,
        fresh_production_sid=True,
        latch_absent=True,
        gate_allows_normal=True,
        baseline_ok=True,
        prior_mutation_click=False,
        ambiguous_queue=False,
    )
    base.update(over)
    return r.evaluate_francisco_mutation_click_authorization(**base)


def _membership(r, **over):
    bl = _baseline(r, session=[], canonical=[])
    base = dict(
        runtime_identity_ok=True,
        auth_only_passed=True,
        stage_a_passed=True,
        baseline=bl,
        click_count=1,
        click_authorized=True,
        premutation_stop_observed=False,
        mutation_helper_entered=True,
        added=True,
        session_queue_after=["Francisco Lindor"],
        canonical_queue_after=["Francisco Lindor"],
        require_append_at_end=True,
    )
    base.update(over)
    if "baseline" in over:
        base["baseline"] = over["baseline"]
    return r.evaluate_francisco_membership_mutation(**base)


def main() -> int:
    r = _load(RUNNER_PATH, "francisco_queue_mutation_proof")
    results: list[dict[str, Any]] = []
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeffff0001"
    url = r.build_francisco_mutation_proof_url(sid)
    q = parse_qs(urlparse(url).query, keep_blank_values=True)
    src = Path(RUNNER_PATH).read_text(encoding="utf-8")
    main_src = inspect.getsource(r.main)

    # 1–4 URL / topology
    results.append(_check("1_no_francisco_latch", r.FRANCISCO_LATCH_PARAM not in q))
    results.append(_check("2_no_host_query_probe", r.HOST_QUERY_PROBE_PARAM not in q))
    pre = r.evaluate_mutation_url_preflight(url)
    results.append(
        _check(
            "3_no_set_query_param_dependency",
            pre.get("set_query_param_required") is False and pre.get("ok") is True,
            pre,
        )
    )
    results.append(
        _check(
            "4_no_gate_clear",
            pre.get("gate_clear_selected") is False
            and "clear_francisco_callback_only_gate" not in main_src
            and "clear_gate_selected\": False" in src.replace(" ", "")
            or "clear_gate_selected\": False" in src
            or 'clear_gate_selected": False' in src,
        )
    )
    # Fix check 4 more simply:
    results[-1] = _check(
        "4_no_gate_clear",
        pre.get("gate_clear_selected") is False
        and "clear_francisco_callback_only_gate" not in main_src,
    )

    # 5–7 gate path
    g_ok = r.evaluate_gate_allows_normal_mutation(
        latch_absent=True, fresh_production_sid=True, gate_lifecycle="unarmed"
    )
    results.append(_check("5_fresh_unlatched_eligible", g_ok.get("ok") is True))
    g_armed = r.evaluate_gate_allows_normal_mutation(
        latch_absent=True, fresh_production_sid=True, gate_lifecycle="armed"
    )
    results.append(_check("6_armed_gate_rejects", g_armed.get("ok") is False))
    g_cons = r.evaluate_gate_allows_normal_mutation(
        latch_absent=True, fresh_production_sid=True, gate_lifecycle="consumed_locked"
    )
    results.append(_check("7_consumed_locked_rejects", g_cons.get("ok") is False))

    # 8–14 click auth failures
    results.append(_check("8_auth_fail_no_click", _auth_click(r, auth_only_passed=False).get("francisco_mutation_click_authorized") is False))
    results.append(_check("9_stage_a_fail_no_click", _auth_click(r, stage_a_steady_authorized=False).get("francisco_mutation_click_authorized") is False))
    results.append(_check("10_heavy_paint_incomplete", _auth_click(r, heavy_paint_complete=False).get("francisco_mutation_click_authorized") is False))
    results.append(_check("11_wrong_room_via_identity", _auth_click(r, stage_a_identity_complete=False).get("francisco_mutation_click_authorized") is False))
    results.append(_check("12_wrong_pick_via_identity", _auth_click(r, stage_a_identity_complete=False).get("francisco_mutation_click_authorized") is False))
    results.append(_check("13_wrong_player_via_identity", _auth_click(r, stage_a_identity_complete=False).get("francisco_mutation_click_authorized") is False))
    results.append(_check("14_wrong_widget_via_identity", _auth_click(r, stage_a_identity_complete=False).get("francisco_mutation_click_authorized") is False))

    # 15–20 baseline
    b_empty = _baseline(r, session=[], canonical=[])
    results.append(_check("15_empty_baseline_eligible", b_empty.get("ok") is True and b_empty.get("francisco_absent") is True))
    b_nonempty = _baseline(r, session=["Aaron Judge"], canonical=["Aaron Judge"])
    results.append(_check("16_nonempty_absent_eligible", b_nonempty.get("ok") is True))
    b_present = _baseline(r, session=["Francisco Lindor"], canonical=["Francisco Lindor"])
    results.append(_check("17_francisco_present_reject", b_present.get("ok") is False))
    b_dup = _baseline(r, session=["Francisco Lindor", "Francisco Lindor"], canonical=["Francisco Lindor", "Francisco Lindor"])
    results.append(_check("18_duplicate_baseline_reject", b_dup.get("ok") is False))
    b_mis = _baseline(r, session=["Aaron Judge"], canonical=[])
    results.append(_check("19_baseline_mismatch_reject", b_mis.get("ok") is False))
    b_unk = _baseline(r, session=[], canonical=[], known=False)
    results.append(_check("20_unknown_baseline_reject", b_unk.get("ok") is False))

    # 21–33 membership mutation
    m21 = _membership(r)
    results.append(
        _check(
            "21_one_click_helper_added_exact_plus1_pass",
            m21.get("ok") is True
            and m21.get("classification") == r.CLASSIFICATION_MEMBERSHIP_PROVEN
            and m21.get("AUTHORITATIVE") == "yes",
            m21,
        )
    )
    results.append(_check("22_added_false_fail", _membership(r, added=False).get("ok") is False))
    results.append(_check("23_no_helper_fail", _membership(r, mutation_helper_entered=False).get("ok") is False))
    results.append(
        _check(
            "24_premutation_stop_fail",
            _membership(r, premutation_stop_observed=True).get("classification")
            == r.CLASSIFICATION_STOP_UNEXPECTED,
        )
    )
    results.append(
        _check(
            "25_after_missing_francisco",
            _membership(r, session_queue_after=[], canonical_queue_after=[]).get("ok") is False,
        )
    )
    results.append(
        _check(
            "26_francisco_twice",
            _membership(
                r,
                session_queue_after=["Francisco Lindor", "Francisco Lindor"],
                canonical_queue_after=["Francisco Lindor", "Francisco Lindor"],
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "27_length_unchanged",
            _membership(r, session_queue_after=[], canonical_queue_after=[], added=True).get("ok") is False,
        )
    )
    # length +2 with nonempty baseline
    bl_j = _baseline(r, session=["Aaron Judge"], canonical=["Aaron Judge"])
    results.append(
        _check(
            "28_length_plus2",
            _membership(
                r,
                baseline=bl_j,
                session_queue_after=["Aaron Judge", "Francisco Lindor", "Juan Soto"],
                canonical_queue_after=["Aaron Judge", "Francisco Lindor", "Juan Soto"],
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "29_unrelated_player_added",
            _membership(
                r,
                baseline=bl_j,
                session_queue_after=["Aaron Judge", "Juan Soto"],
                canonical_queue_after=["Aaron Judge", "Juan Soto"],
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "30_baseline_player_removed",
            _membership(
                r,
                baseline=bl_j,
                session_queue_after=["Francisco Lindor"],
                canonical_queue_after=["Francisco Lindor"],
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "31_canonical_ne_session",
            _membership(
                r,
                session_queue_after=["Francisco Lindor"],
                canonical_queue_after=[],
            ).get("ok")
            is False,
        )
    )
    results.append(
        _check(
            "32_exact_baseline_plus_francisco",
            _membership(
                r,
                baseline=bl_j,
                session_queue_after=["Aaron Judge", "Francisco Lindor"],
                canonical_queue_after=["Aaron Judge", "Francisco Lindor"],
            ).get("ok")
            is True,
        )
    )
    results.append(
        _check(
            "33_order_preserved_append_end",
            _membership(
                r,
                baseline=_baseline(r, session=["A", "B"], canonical=["A", "B"]),
                session_queue_after=["A", "B", "Francisco Lindor"],
                canonical_queue_after=["A", "B", "Francisco Lindor"],
            ).get("ok")
            is True,
        )
    )

    # 34–39 observability / persistence
    composed_gap = r.compose_mutation_proof_result(
        membership=m21,
        player_a=r.evaluate_player_a_queue_mutation_resolution(
            callback_entered=True, mutation_proven=True, queue_mutation_visible=False
        ),
        callback_ledger_observed=False,
        persist_dirty=True,
        durable_flush_observed=False,
    )
    results.append(
        _check(
            "34_ledger_absent_does_not_fail_membership",
            composed_gap.get("ok") is True
            and composed_gap.get("callback_ledger_observability_gap") is True
            and composed_gap.get("callback_ledger_authority_required") is False,
        )
    )
    composed_led = r.compose_mutation_proof_result(
        membership=m21,
        player_a=r.evaluate_player_a_queue_mutation_resolution(
            callback_entered=True, mutation_proven=True, queue_mutation_visible=True
        ),
        callback_ledger_observed=True,
    )
    results.append(
        _check(
            "35_ledger_present_supporting",
            composed_led.get("callback_ledger_observed") is True
            and composed_led.get("callback_ledger_observability_gap") is False,
        )
    )
    pa_vis = r.evaluate_player_a_queue_mutation_resolution(
        callback_entered=True, mutation_proven=True, queue_mutation_visible=True
    )
    results.append(
        _check(
            "36_ui_confirmation_player_a",
            pa_vis.get("PLAYER_A_QUEUE_MUTATION_RESOLVED") is True,
            pa_vis,
        )
    )
    pa_no_ui = r.evaluate_player_a_queue_mutation_resolution(
        callback_entered=True, mutation_proven=True, queue_mutation_visible=False
    )
    results.append(
        _check(
            "37_membership_vs_player_a_without_ui",
            m21.get("ok") is True
            and pa_no_ui.get("PLAYER_A_QUEUE_MUTATION_RESOLVED") is False
            and pa_no_ui.get("classification") == "QUEUE1C3F",
        )
    )
    results.append(
        _check(
            "38_persist_dirty_supporting",
            composed_gap.get("persist_dirty") is True
            and composed_gap.get("persist_dirty_supporting_only") is True,
        )
    )
    results.append(
        _check(
            "39_durable_flush_absent_ok",
            composed_gap.get("durable_flush_required") is False
            and composed_gap.get("ok") is True,
        )
    )

    # 40–46 safety / invariants
    results.append(_check("40_no_cleanup_remove", composed_gap.get("cleanup_remove_selected") is False))
    results.append(_check("41_one_click_required", _membership(r, click_count=0).get("ok") is False))
    results.append(
        _check(
            "42_two_clicks_fail",
            _membership(r, click_count=2).get("classification") == r.CLASSIFICATION_MULTI_CLICK,
        )
    )
    results.append(
        _check(
            "43_fresh_sid_required",
            _auth_click(r, fresh_production_sid=False).get("francisco_mutation_click_authorized") is False,
        )
    )
    results.append(_check("44_no_hardcoded_historical_player_id", "592789" not in src))
    results.append(
        _check(
            "45_current_pick_not_rank_in_evaluator",
            "recommendation_card_rank" not in src and "rank" not in inspect.getsource(r.evaluate_francisco_mutation_click_authorization),
        )
    )
    results.append(_check("46_no_invented_q_append_event", "q.append event" not in src.lower() and "direct_q_append" not in src))

    # 47–50 labels preserved false on compose
    results.append(_check("47_queue1c3a2f4_not_auto", composed_gap.get("QUEUE1C3A2F4_RESOLVED") is False))
    results.append(_check("48_queue_seed_false", composed_gap.get("QUEUE_SEED_RESOLVED") is False))
    results.append(_check("49_stage_1a_queue_false", composed_gap.get("stage_1a_queue_passed") is False))
    results.append(_check("50_stage_1b_false", composed_gap.get("stage_1b") is False))

    # PLAYER_A classifier fidelity
    pa_cb = r.evaluate_player_a_queue_mutation_resolution(False, True, True) if False else r.evaluate_player_a_queue_mutation_resolution(
        callback_entered=False, mutation_proven=True, queue_mutation_visible=True
    )
    results.append(_check("51_player_a_requires_callback", pa_cb.get("PLAYER_A_QUEUE_MUTATION_RESOLVED") is False))
    pa_mut = r.evaluate_player_a_queue_mutation_resolution(
        callback_entered=True, mutation_proven=False, queue_mutation_visible=True
    )
    results.append(_check("52_player_a_requires_mutation", pa_mut.get("PLAYER_A_QUEUE_MUTATION_RESOLVED") is False))
    pa_ui = r.evaluate_player_a_queue_mutation_resolution(
        callback_entered=True, mutation_proven=True, queue_mutation_visible=False
    )
    results.append(_check("53_player_a_requires_visible", pa_ui.get("PLAYER_A_QUEUE_MUTATION_RESOLVED") is False))
    results.append(_check("54_player_a_all_three", pa_vis.get("PLAYER_A_QUEUE_MUTATION_RESOLVED") is True))

    f4 = r.evaluate_queue1c3a2f4_fragment_condition(
        probe_callback_entered=True,
        francisco_callback_entered=True,
        player_a_resolved=False,
    )
    results.append(
        _check(
            "55_f4_both_callbacks_without_player_a",
            f4.get("QUEUE1C3A2F4_RESOLVED") is True,
            f4,
        )
    )
    f4b = r.evaluate_queue1c3a2f4_fragment_condition(
        probe_callback_entered=True,
        francisco_callback_entered=True,
        player_a_resolved=True,
    )
    results.append(_check("56_f4_not_when_player_a", f4b.get("QUEUE1C3A2F4_RESOLVED") is False))

    # Latch present on URL fails preflight
    bad_url = url + "&stage1_francisco_callback_only=1"
    results.append(_check("57_latch_url_preflight_fail", r.evaluate_mutation_url_preflight(bad_url).get("ok") is False))

    # Event-present gate block
    g_ev = r.evaluate_gate_allows_normal_mutation(
        latch_absent=True, fresh_production_sid=True, armed_or_consumed_event_present=True
    )
    results.append(_check("58_armed_event_rejects", g_ev.get("ok") is False))

    # Preserved callback proof note
    results.append(
        _check(
            "59_preserves_callback_proof_note",
            composed_gap.get("preserved_callback_proof", {}).get(
                "FRANCISCO_ADD_TO_QUEUE_CALLBACK_EXECUTION_PROVEN_PREMUTATION"
            )
            is True,
        )
    )
    results.append(
        _check(
            "60_mutation_not_authorized_in_compose",
            composed_gap.get("francisco_real_queue_mutation_authorized") is False,
        )
    )

    # Shared Stage A URL helper reuse (callback runner build_stage_a also omits latch)
    cb = _load(CALLBACK_RUNNER, "francisco_callback_shared_for_mutation")
    stage_a_url = cb.build_stage_a_proof_url(sid)
    results.append(
        _check(
            "61_stage_a_helper_omits_latch",
            "stage1_francisco_callback_only" not in stage_a_url,
        )
    )
    results.append(_check("62_architecture_label", r.ARCHITECTURE.startswith("FRANCISCO_QUEUE_MUTATION_EXISTING_SOLO_ROOM")))
    results.append(_check("63_retired_includes_2e11", "2e11d7aa-fb16-4810-aff5-7c95777ac7bf" in r.RETIRED_BRIDGE_IDS))
    results.append(_check("64_main_not_cloud_by_default", "FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD" in main_src))

    failed = [x for x in results if not x.get("ok")]
    by = {x["name"]: x["ok"] for x in results}
    classifications = {
        "FRANCISCO_QUEUE_MUTATION_NORMAL_PATH_RUNNER_READY": bool(
            by.get("1_no_francisco_latch")
            and by.get("3_no_set_query_param_dependency")
            and by.get("4_no_gate_clear")
            and by.get("5_fresh_unlatched_eligible")
            and by.get("24_premutation_stop_fail")
            and by.get("41_one_click_required")
            and by.get("42_two_clicks_fail")
        ),
        "FRANCISCO_QUEUE_MUTATION_BASELINE_GUARD_RUNNER_READY": bool(
            by.get("15_empty_baseline_eligible")
            and by.get("16_nonempty_absent_eligible")
            and by.get("17_francisco_present_reject")
            and by.get("18_duplicate_baseline_reject")
            and by.get("19_baseline_mismatch_reject")
            and by.get("20_unknown_baseline_reject")
        ),
        "FRANCISCO_QUEUE_MUTATION_STAGE_A_BINDING_RUNNER_READY": bool(
            by.get("9_stage_a_fail_no_click")
            and by.get("10_heavy_paint_incomplete")
            and by.get("11_wrong_room_via_identity")
            and by.get("61_stage_a_helper_omits_latch")
            and by.get("45_current_pick_not_rank_in_evaluator")
        ),
        "FRANCISCO_QUEUE_MUTATION_SESSION_CANONICAL_AUTHORITY_RUNNER_READY": bool(
            by.get("21_one_click_helper_added_exact_plus1_pass")
            and by.get("31_canonical_ne_session")
            and by.get("32_exact_baseline_plus_francisco")
            and by.get("33_order_preserved_append_end")
            and by.get("29_unrelated_player_added")
            and by.get("30_baseline_player_removed")
        ),
        "PLAYER_A_QUEUE_MUTATION_RESOLUTION_EVALUATOR_READY": bool(
            by.get("51_player_a_requires_callback")
            and by.get("52_player_a_requires_mutation")
            and by.get("53_player_a_requires_visible")
            and by.get("54_player_a_all_three")
            and by.get("37_membership_vs_player_a_without_ui")
        ),
    }
    overall = not failed and all(classifications.values())
    classifications["FRANCISCO_QUEUE_MUTATION_SINGLE_CLICK_PROOF_RUNNER_READY"] = overall
    summary = {
        "ok": overall,
        "passed": sum(1 for x in results if x.get("ok")),
        "total": len(results),
        "failed": failed,
        "classifications": classifications,
        "architecture": r.ARCHITECTURE,
        "production_main_executed": False,
        "francisco_click": False,
        "queue_mutation": False,
        "PLAYER_A_QUEUE_MUTATION_RESOLVED_issued": False,
        "QUEUE1C3A2F4_RESOLVED_issued": False,
        "QUEUE_SEED_RESOLVED_issued": False,
        "stage_1a_queue_passed": False,
        "stage_1b": False,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
