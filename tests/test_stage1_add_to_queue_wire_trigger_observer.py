"""Production 5b0e93c / 1b98f30a: Add-to-Queue wire trigger vs harness observer.

Proves offline from ``data/production_stage1a_queue_auth.json`` that:
1. Stage1 clicked the native ``stBaseButton-secondary`` (not a wrapper-only target).
2. Outbound BackMsg is ``rerun_script`` with ``trigger_value=true`` for the card key.
3. Hook flag ``widget_key_bytes_present=false`` was a wrong-default-key observer defect.
4. Fixed classifier + protobuf authority report strict native for that frame.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_native_widget_transport import (  # noqa: E402
    apply_strict_backmsg_authority,
    classify_transport_from_ws_samples,
)
from stage1_strict_backmsg_decode import widget_id_matches_expected  # noqa: E402

AUTH = ROOT / "data" / "production_stage1a_queue_auth.json"
PAUSE_GATE = ROOT / "data" / "production_bridge_s3_server_registry_gate.json"


@pytest.mark.skipif(not AUTH.is_file(), reason="production Stage1A queue auth artifact missing")
def test_lindor_production_wire_has_trigger_and_observer_fix() -> None:
    q = json.loads(AUTH.read_text(encoding="utf-8"))
    step = (q.get("queue_seed") or {}).get("seed_steps")[0]
    assert str(step.get("pre_click_record", {}).get("player_id") or "") == "231"
    key = str(step.get("expected_widget_key") or step.get("pre_click_record", {}).get("widget_key") or "")
    assert key.endswith("_231_rec_card")

    insp = (step.get("delivery_detail") or {}).get("pre_click_dom_inspection") or {}
    rec = insp.get("recommended_click") or {}
    assert rec.get("is_st_base_button") is True
    assert rec.get("test_id") == "stBaseButton-secondary"
    assert insp.get("native_st_base_button_count") == 1
    assert insp.get("visible_button_count_in_card") == 1

    dom = (step.get("delivery_detail") or {}).get("dom_click_capture") or {}
    assert dom.get("trusted_dom_click") is True
    click_ev = next(e for e in (dom.get("browser_dom_click_events") or []) if e.get("type") == "click")
    assert click_ev.get("current_target_tag") == "button"
    assert click_ev.get("is_trusted") is True

    samples = list(((step.get("delivery_detail") or {}).get("post_click_transport") or {}).get("ws_log_sample") or [])
    assert samples, "expected captured outbound WS samples"
    # Hook flags on the raw artifact are false (solo countdown default key).
    assert any(s.get("widget_key_bytes_present") is False for s in samples)

    broken = classify_transport_from_ws_samples(samples)  # no expected key → hook flags win
    assert broken["native_widget_event_observed_strict"] is False

    fixed = classify_transport_from_ws_samples(samples, expected_widget_key=key)
    assert fixed["native_widget_event_observed_strict"] is True
    assert any(e.get("widget_key_bytes_present") for e in fixed["ws_log_sample"])

    click_end = float((step.get("delivery_detail") or {}).get("click_end_ts") or 0)
    auth = apply_strict_backmsg_authority(
        fixed,
        click_ts=click_end,
        expected_widget_key=key,
    )
    strict = auth.get("strict_backmsg") or {}
    assert strict.get("rerun_script_backmsg_seen") is True
    assert strict.get("target_trigger_backmsg_seen") is True
    assert auth.get("native_widget_event_observed_strict") is True
    assert auth.get("protobuf_target_trigger_observed") is True

    activated = list(strict.get("activated_widget_ids") or [])
    assert any(widget_id_matches_expected(i, key) for i in activated)
    # App-scope button: empty fragment_id on the trigger frame (unlike Pause).
    assert strict.get("target_trigger_fragment_id") in ("", None) or strict.get("target_trigger_fragment_id") == ""


@pytest.mark.skipif(not PAUSE_GATE.is_file(), reason="pause registry gate artifact missing")
def test_pause_trigger_has_fragment_id_same_encoding() -> None:
    d = json.loads(PAUSE_GATE.read_text(encoding="utf-8"))
    samples = list(
        ((d.get("pause_positive_control") or {}).get("streamlit_transport") or {}).get("ws_log_sample") or []
    )
    assert samples
    key = "live_draft_pause"
    fixed = classify_transport_from_ws_samples(samples, expected_widget_key=key)
    auth = apply_strict_backmsg_authority(fixed, click_ts=0.0, expected_widget_key=key)
    strict = auth.get("strict_backmsg") or {}
    assert strict.get("activated_widget_state_present") or strict.get("target_trigger_backmsg_seen")
    frag = str(strict.get("target_trigger_fragment_id") or strict.get("wire_rerun_target_fragment_id") or "")
    # Working Pause is fragment-scoped; this is the first concrete wire difference vs Add-to-Queue.
    assert frag, "Pause positive control must carry a non-empty fragment_id"


def test_widget_id_suffix_match() -> None:
    wid = "$$ID-1df391b661f2f4d6cc6ae84f5d703dc4-rec_card_queue_77DAD3EE_0_231_rec_card"
    assert widget_id_matches_expected(wid, "rec_card_queue_77DAD3EE_0_231_rec_card")
    assert widget_id_matches_expected(wid, wid)
    assert not widget_id_matches_expected(wid, "rec_card_queue_77DAD3EE_0_414_rec_card")
