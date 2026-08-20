"""LOCAL Francisco native-click consumption / st.button binding selftest.

NO Cloud. NO Playwright browser. NO network. NO production main.
NO bridge reuse. Temp/fixture only.
"""
from __future__ import annotations

import base64
import importlib.util
import py_compile
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "data"))

WIDGET = "rec_card_queue_D55BC3FB_0_231_rec_card"
OTHER = "rec_card_queue_D55BC3FB_0_999_rec_card"


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


def _ws_sample_with_key(widget_key: str) -> dict[str, Any]:
    raw = f"noise::{widget_key}::tail".encode("utf-8")
    return {
        "direction": "outbound",
        "byte_len": len(raw) + 2000,
        "frame_type_hint": "component_value_hint",
        "widget_key_bytes_present": True,
        "payload_base64": base64.b64encode(raw).decode("ascii"),
    }


def _ws_sample_generic() -> dict[str, Any]:
    raw = b"x" * 2200 + b"$$ID-sidebar-live_draft_my_team"
    return {
        "direction": "outbound",
        "byte_len": len(raw),
        "frame_type_hint": "component_value_hint",
        "widget_key_bytes_present": True,
        "payload_base64": base64.b64encode(raw).decode("ascii"),
    }


def _live_dom_ok(**over: Any) -> dict[str, Any]:
    base = {
        "player_name": "Francisco Lindor",
        "ld_rec_card_meta_found": True,
        "st_button_wrapper_count": 1,
        "button_count_in_card": 1,
        "visible_button_count_in_card": 1,
        "native_st_base_button_count": 1,
        "recommended_click": {
            "tag": "button",
            "text": "⭐ Add to Queue",
            "test_id": "stBaseButton-secondary",
            "inside_st_tooltip": True,
            "inside_st_button": True,
            "is_st_base_button": True,
            "click_non_native_element": False,
            "visible": True,
        },
    }
    base.update(over)
    return base


def main() -> int:
    cons = _load(
        SCRIPTS / "stage1_francisco_native_click_consumption.py",
        "stage1_francisco_native_click_consumption",
    )
    delivery_src = (SCRIPTS / "stage1_add_to_queue_delivery.py").read_text(encoding="utf-8")
    runner_src = (
        ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
    ).read_text(encoding="utf-8")
    results: list[dict[str, Any]] = []

    # 1 live st.button fixture accepted
    live_ok = cons.evaluate_live_stbutton_target_binding(
        _live_dom_ok(),
        player_name="Francisco Lindor",
        expected_widget_key=WIDGET,
        probe_widget_key=WIDGET,
        binding_confidence="unique",
    )
    results.append(_check("01_live_stbutton_accepted", live_ok.get("ok") is True and live_ok.get("maps_ld_rec_card_meta_to_st_button") is True, live_ok))

    # 2 metadata/proxy-only rejected
    proxy = cons.evaluate_live_stbutton_target_binding(
        {"ld_rec_card_meta_found": True, "native_st_base_button_count": 0, "visible_button_count_in_card": 0},
        player_name="Francisco Lindor",
        binding_confidence="unique",
        proxy_only=True,
    )
    results.append(_check("02_proxy_only_rejected", proxy.get("ok") is False, proxy))

    # 3 duplicate visible text requires unique binding
    dup = cons.evaluate_live_stbutton_target_binding(
        _live_dom_ok(visible_button_count_in_card=2),
        player_name="Francisco Lindor",
        binding_confidence="ambiguous",
    )
    results.append(_check("03_duplicate_requires_unique", dup.get("ok") is False and "duplicate_visible_add_without_unique_binding" in (dup.get("failures") or []), dup))

    # 4 stale generation rejected
    stale = cons.evaluate_live_stbutton_target_binding(
        _live_dom_ok(),
        player_name="Francisco Lindor",
        binding_confidence="unique",
        stale_generation=True,
    )
    results.append(_check("04_stale_generation_rejected", stale.get("ok") is False, stale))

    # 5-8 identity mismatches
    for name, kwargs in (
        ("05_room_mismatch", {"room_match": False}),
        ("06_pick_mismatch", {"pick_match": False}),
        ("07_player_id_mismatch", {"player_id_match": False}),
        ("08_widget_key_mismatch", {"widget_key_match": False}),
    ):
        row = cons.evaluate_live_stbutton_target_binding(
            _live_dom_ok(),
            player_name="Francisco Lindor",
            binding_confidence="unique",
            **kwargs,
        )
        results.append(_check(name, row.get("ok") is False, row))

    # 9 unique live accepted
    results.append(_check("09_unique_live_accepted", live_ok.get("ok") is True))

    # parity: metadata only → no dispatch
    meta_only = cons.parity_replay_dispatch_once(
        stage_a_authorized=True,
        metadata_candidate={"player_name": "Francisco Lindor", "binding_via": "ld_rec_card_meta"},
        live_target=None,
        live_binding_eval=None,
        streamlit_ack=None,
    )
    results.append(_check("10_metadata_only_no_dispatch", meta_only.get("dispatched") is False and meta_only.get("browser_clicks") == 0, meta_only))

    # stale → reacquire then one click
    live_target = {
        "player_name": "Francisco Lindor",
        "widget_key": WIDGET,
        "binding_confidence": "unique",
        "frameIndex": 1,
        "index_in_frame": 0,
        "reacquisition_source": "live_dom",
    }
    binding = cons.evaluate_live_stbutton_target_binding(
        _live_dom_ok(),
        player_name="Francisco Lindor",
        expected_widget_key=WIDGET,
        probe_widget_key=WIDGET,
        binding_confidence="unique",
    )
    ack_ok = cons.evaluate_francisco_native_click_consumption_ack(
        click_dispatched=True,
        authorized_rec_card_key=WIDGET,
        post_click_transport={
            "ws_log_sample": [_ws_sample_with_key(WIDGET)],
            "native_widget_event_observed_strict": True,
            "script_run_seq_changed": True,
        },
        callback_entered_observed=True,
        trusted_dom_click=True,
    )
    replay_ok = cons.parity_replay_dispatch_once(
        stage_a_authorized=True,
        metadata_candidate={"player_name": "Francisco Lindor", "frameIndex": 9, "index_in_frame": 99},
        live_target=live_target,
        live_binding_eval=binding,
        streamlit_ack={**ack_ok, "mutation_proven": False},
    )
    results.append(_check("11_helper_once", replay_ok.get("helper_invocations") == 1, replay_ok))
    results.append(_check("12_browser_click_once", replay_ok.get("browser_clicks") == 1, replay_ok))
    results.append(_check("13_no_js_fallback", replay_ok.get("js_fallback") is False, replay_ok))
    results.append(_check("14_no_retry", replay_ok.get("retry_count") == 0, replay_ok))
    results.append(
        _check(
            "15_dispatch_alone_not_callback",
            cons.evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=WIDGET,
                post_click_transport={"ws_log_sample": [_ws_sample_generic()], "native_widget_event_observed_strict": True, "script_run_seq_changed": True},
                callback_entered_observed=False,
            ).get("callback_entered_from_dispatch_alone")
            is False,
        )
    )
    results.append(
        _check(
            "16_dispatch_alone_not_mutation",
            cons.evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=WIDGET,
                post_click_transport={"native_widget_event_observed_strict": True},
            ).get("mutation_proven_from_dispatch_alone")
            is False,
        )
    )

    # 17 simulated Streamlit rerun generic ≠ widget ack
    generic_ack = cons.evaluate_francisco_native_click_consumption_ack(
        click_dispatched=True,
        authorized_rec_card_key=WIDGET,
        post_click_transport={
            "ws_log_sample": [_ws_sample_generic()],
            "native_widget_event_observed_strict": True,
            "script_run_seq_changed": True,
        },
        callback_entered_observed=False,
        trusted_dom_click=True,
    )
    results.append(
        _check(
            "17_generic_rerun_not_widget_ack",
            generic_ack.get("francisco_widget_consumption_ack") is False
            and generic_ack.get("generic_streamlit_traffic_observed") is True,
            generic_ack,
        )
    )

    # 18 simulated callback ack
    cb_ack = cons.evaluate_francisco_native_click_consumption_ack(
        click_dispatched=True,
        authorized_rec_card_key=WIDGET,
        post_click_transport={"ws_log_sample": [_ws_sample_generic()]},
        callback_entered_observed=True,
        trusted_dom_click=True,
    )
    results.append(_check("18_callback_ack_distinct", cb_ack.get("francisco_widget_consumption_ack") is True and cb_ack.get("ok") is True, cb_ack))

    # 19 successful callback-only delivery method still present in helper
    results.append(
        _check(
            "19_callback_only_delivery_method_preserved",
            "playwright_ld_rec_card_meta_native_stbutton" in delivery_src,
        )
    )

    # 20 normal mutation uses same physical target path + expected_widget_key
    results.append(
        _check(
            "20_normal_path_authorized_rec_card_key",
            "authorized_rec_card_key" in delivery_src and "live_reacquired_before_click" in delivery_src,
        )
    )

    # 21 stale detached → reject before click (no second dispatch)
    stale_replay = cons.parity_replay_dispatch_once(
        stage_a_authorized=True,
        metadata_candidate={"player_name": "Francisco Lindor"},
        live_target=live_target,
        live_binding_eval=cons.evaluate_live_stbutton_target_binding(
            _live_dom_ok(),
            player_name="Francisco Lindor",
            binding_confidence="unique",
            stale_generation=True,
        ),
        streamlit_ack=None,
    )
    results.append(
        _check(
            "21_stale_no_second_dispatch",
            stale_replay.get("dispatched") is False and stale_replay.get("second_dispatch") is not True,
            stale_replay,
        )
    )

    results.append(_check("22_no_direct_callback", replay_ok.get("direct_callback_invocation") is False))
    results.append(_check("23_no_direct_queue_helper", replay_ok.get("direct_queue_helper") is False))
    results.append(_check("24_no_q_append", replay_ok.get("q_append") is False))
    results.append(_check("25_no_cleanup_in_helper", "remove_player_from_user_draft_queue" not in delivery_src))
    results.append(_check("26_no_force_save_in_helper", "force_save" not in delivery_src.lower() or "force_save_selected\": True" not in delivery_src.replace(" ", "")))

    # 27 post-state membership wait still present
    results.append(_check("27_post_wait_preserved", "wait_for_authoritative_post_queue_scrape" in runner_src))
    results.append(_check("28_post_wait_45s", "timeout_s=45.0" in runner_src or "timeout_s = 45" in runner_src))
    results.append(_check("29_premutation_stop_symbol_preserved", "FRANCISCO_QUEUE_CALLBACK_PREMUTATION_STOP" in runner_src))
    results.append(_check("30_stage_a_model_c_symbol", "stage_a_identity_complete" in runner_src))

    # 31-36 suite runners (invoked below in shell); here just compile + import gates
    results.append(
        _check(
            "31_consumption_module_importable",
            hasattr(cons, "evaluate_francisco_native_click_consumption_ack"),
        )
    )
    results.append(_check("32_merge_live_reacquisition", cons.merge_candidate_with_live_reacquisition({"frameIndex": 9}, {"frameIndex": 1}).get("frameIndex") == 1))
    results.append(
        _check(
            "33_wrong_widget_key_in_ws_not_ack",
            cons.evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=WIDGET,
                post_click_transport={"ws_log_sample": [_ws_sample_with_key(OTHER)]},
            ).get("francisco_widget_consumption_ack")
            is False,
        )
    )
    results.append(
        _check(
            "34_exact_widget_key_in_ws_acks",
            cons.evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=WIDGET,
                post_click_transport={"ws_log_sample": [_ws_sample_with_key(WIDGET)]},
            ).get("francisco_widget_consumption_ack")
            is True,
        )
    )

    # Retrospective 729 artifact: dispatch without Francisco-key ack
    art = ROOT / "data" / "francisco_queue_mutation_proof_c8d34a8_729282d9.result.json"
    if art.is_file():
        import json

        report = json.loads(art.read_text(encoding="utf-8"))
        delivery = ((report.get("click") or {}).get("delivery") or {})
        retro = cons.evaluate_francisco_native_click_consumption_ack(
            click_dispatched=bool(delivery.get("click_dispatched")),
            authorized_rec_card_key=str((report.get("click") or {}).get("widget_key") or WIDGET),
            post_click_transport=delivery.get("post_click_transport")
            if isinstance(delivery.get("post_click_transport"), dict)
            else {},
            callback_entered_observed=bool((report.get("post_click") or {}).get("callback_entered")),
            trusted_dom_click=bool(delivery.get("trusted_dom_click")),
        )
        results.append(
            _check(
                "35_729_artifact_dispatch_without_francisco_ack",
                retro.get("click_dispatched") is True
                and retro.get("francisco_widget_consumption_ack") is False
                and retro.get("classification") == "FRANCISCO_NATIVE_CLICK_DISPATCHED_WITHOUT_WIDGET_ACK",
                retro,
            )
        )
    else:
        results.append(_check("35_729_artifact_dispatch_without_francisco_ack", False, "artifact_missing"))

    try:
        py_compile.compile(str(SCRIPTS / "stage1_francisco_native_click_consumption.py"), doraise=True)
        py_compile.compile(str(SCRIPTS / "stage1_add_to_queue_delivery.py"), doraise=True)
        py_compile.compile(str(ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"), doraise=True)
        results.append(_check("36_py_compile", True))
    except Exception as exc:
        results.append(_check("36_py_compile", False, str(exc)[:200]))

    # 37 product still wires on_click=_on_rec_queue_click
    ui_src = (ROOT / "live_draft_room_ui.py").read_text(encoding="utf-8")
    results.append(
        _check(
            "37_product_on_click_wired",
            "on_click=_on_rec_queue_click" in ui_src and "def _on_rec_queue_click" in ui_src,
        )
    )

    failed = [r for r in results if not r.get("ok")]
    print(
        {
            "ok": not failed,
            "passed": sum(1 for r in results if r.get("ok")),
            "total": len(results),
            "failed": failed,
        }
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
