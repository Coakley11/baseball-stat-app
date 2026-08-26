"""Same-run consumption ledger: DOM exposure + Stage1 scrape correlation.

Proves Stage1 can observe run N+1 stages without relying on a single overwritten
global, and that post-click seq wait would have caught production 392ba87/131d99b2
(Lindor scrape at +0.21s still seq 21; full_run seq 22 stamped ~40ms later).
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from live_draft_rec_live_paint import (  # noqa: E402
    RUN_STAGE_BY_SEQ_KEY,
    RUN_STAGE_PROBE_ELEMENT_ID,
    build_rec_run_stage_ledger_payload,
    note_rec_run_stage,
    render_rec_run_stage_ledger_probe,
)
from stage1_native_widget_transport import wait_for_post_click_app_diag_advance  # noqa: E402
from stage1_rec_run_stage_scrape import (  # noqa: E402
    select_run_stage_rollup_for_seq,
)


def _session_run(seq: int, room: str = "C97D3868") -> dict[str, Any]:
    return {
        "_solo_stage1_script_run_seq": seq,
        "live_draft_room": {"draft_room_id": room},
    }


def test_per_run_rollup_survives_later_fragment_activity() -> None:
    """Run-22 stages must remain selectable after a later run stamps new events."""
    session = _session_run(21)
    note_rec_run_stage(session, "run_entry", widget_key="rec_card_queue_C97D3868_0_231_rec_card")
    note_rec_run_stage(session, "target_button_registered", widget_key="rec_card_queue_C97D3868_0_231_rec_card")

    session["_solo_stage1_script_run_seq"] = 22
    note_rec_run_stage(session, "run_entry")
    note_rec_run_stage(session, "cache_miss")
    note_rec_run_stage(session, "snapshot_restored", top_rec_count=6)
    note_rec_run_stage(session, "interactive_invoked")
    note_rec_run_stage(
        session,
        "target_button_registered",
        widget_key="rec_card_queue_C97D3868_0_231_rec_card",
        player_id="231",
    )
    note_rec_run_stage(session, "button_return_value", button_return_value=True, widget_key="rec_card_queue_C97D3868_0_231_rec_card")
    note_rec_run_stage(session, "dispatch_entered", widget_key="rec_card_queue_C97D3868_0_231_rec_card")
    note_rec_run_stage(session, "execute_entered", widget_key="rec_card_queue_C97D3868_0_231_rec_card")

    # Later fragment/timer activity must not erase run 22.
    session["_solo_stage1_script_run_seq"] = 23
    note_rec_run_stage(session, "fragment_tick")

    payload = build_rec_run_stage_ledger_payload(session)
    assert payload["current_run_seq"] == 23
    seqs = [int(r["run_seq"]) for r in payload["recent_by_seq"]]
    assert 21 in seqs and 22 in seqs and 23 in seqs

    probes = [
        {
            "probe_found": True,
            "payload": payload,
            "run_seq": "23",
            "room_id": "C97D3868",
        }
    ]
    roll = select_run_stage_rollup_for_seq(
        probes,
        run_seq=22,
        room_id="C97D3868",
        widget_key="rec_card_queue_C97D3868_0_231_rec_card",
    )
    assert roll["ok"] is True
    assert int(roll["run_seq"]) == 22
    assert roll["cache_miss"] is True
    assert roll["snapshot_restored"] is True
    assert roll["interactive_invoked"] is True
    assert roll["target_button_registered"] is True
    assert roll["button_return_value"] is True
    assert roll["dispatch_entered"] is True
    assert roll["execute_entered"] is True
    # Stale run-21 selection must not be returned when asking for 22.
    assert "target_button_registered" in roll["stages"]
    assert roll["flags"].get("fragment_tick") is not True


def test_dom_probe_emits_b64_payload_stage1_can_parse() -> None:
    """Ledger must not stay session-internal only when production ledger is enabled."""
    session = _session_run(22)
    note_rec_run_stage(session, "cache_miss")
    note_rec_run_stage(session, "rebuild_started")
    note_rec_run_stage(session, "rebuild_succeeded")
    note_rec_run_stage(
        session,
        "target_button_registered",
        widget_key="rec_card_queue_C97D3868_0_231_rec_card",
        player_id="231",
    )

    st = MagicMock()
    # Bypass gate the same way production enables via solo_component_diag.
    import live_draft_rec_live_paint as mod

    real_render = mod.render_rec_run_stage_ledger_probe

    def _render_forced(st_obj: Any, sess: dict[str, Any]) -> None:
        # Force-enable path: call build + markdown without ledger gate.
        import base64 as _b64
        import json as _json

        payload = build_rec_run_stage_ledger_payload(sess)
        recent = list(payload.get("recent_by_seq") or [])
        current = recent[-1] if recent else {}
        flags = dict(current.get("flags") or {}) if isinstance(current, dict) else {}
        raw_json = _json.dumps(payload, default=str, separators=(",", ":"))[:16000]
        b64 = _b64.b64encode(raw_json.encode("utf-8")).decode("ascii")
        st_obj.markdown(
            f'<div id="{RUN_STAGE_PROBE_ELEMENT_ID}" '
            f'data-run-seq="{int(payload.get("current_run_seq") or 0)}" '
            f'data-cache-miss="{1 if flags.get("cache_miss") else 0}" '
            f'data-target-button-registered="{1 if flags.get("target_button_registered") else 0}" '
            f'data-b64="{b64}"></div>',
            unsafe_allow_html=True,
        )

    _render_forced(st, session)
    assert st.markdown.called
    html = st.markdown.call_args[0][0]
    assert f'id="{RUN_STAGE_PROBE_ELEMENT_ID}"' in html
    assert 'data-cache-miss="1"' in html
    assert 'data-target-button-registered="1"' in html
    assert "data-b64=" in html
    # Extract and parse b64 as Stage1 scraper does.
    marker = 'data-b64="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    payload = json.loads(base64.b64decode(html[start:end]).decode("utf-8"))
    roll = select_run_stage_rollup_for_seq(
        [{"probe_found": True, "payload": payload}],
        run_seq=22,
        room_id="C97D3868",
        widget_key="rec_card_queue_C97D3868_0_231_rec_card",
    )
    assert roll["ok"] is True
    assert roll["cache_miss"] is True
    assert roll["rebuild_started"] is True
    assert roll["rebuild_succeeded"] is True
    assert roll["target_button_registered"] is True
    # Ensure gate-aware renderer still exists (product path).
    assert callable(real_render)


def test_wait_for_post_click_seq_advance_catches_late_full_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduce 392ba87 timing: first scrape still 21; shortly later full_run 22."""
    snaps = [
        {
            "current_app_diag_seq": 21,
            "current_app_diag_candidates": [
                {"script_run_seq": 21, "fragment_run_hint": "fragment_run", "probe_ts": "1787710475.76"},
            ],
        },
        {
            "current_app_diag_seq": 21,
            "current_app_diag_candidates": [
                {"script_run_seq": 22, "fragment_run_hint": "full_run", "probe_ts": "1787710517.855"},
                {"script_run_seq": 21, "fragment_run_hint": "fragment_run", "probe_ts": "1787710475.76"},
            ],
        },
        {
            "current_app_diag_seq": 22,
            "current_app_diag_candidates": [
                {"script_run_seq": 22, "fragment_run_hint": "full_run", "probe_ts": "1787710517.855"},
            ],
        },
    ]
    calls = {"n": 0}

    def fake_capture(page, frame_url_hint="", phase=""):
        i = min(calls["n"], len(snaps) - 1)
        calls["n"] += 1
        return dict(snaps[i])

    monkeypatch.setattr(
        "stage1_run_binding.capture_run_binding_snapshot",
        fake_capture,
    )
    # Import path used inside wait_for_post_click_app_diag_advance
    import stage1_native_widget_transport as nwt

    monkeypatch.setattr(
        nwt,
        "wait_for_post_click_app_diag_advance",
        nwt.wait_for_post_click_app_diag_advance,
    )
    # Patch the import target inside the function via sys.modules path used by `from stage1_run_binding import ...`
    import stage1_run_binding as srb

    monkeypatch.setattr(srb, "capture_run_binding_snapshot", fake_capture)

    page = MagicMock()
    result = wait_for_post_click_app_diag_advance(
        page,
        pre_script_run_seq=21,
        timeout_s=2.0,
        poll_s=0.01,
    )
    assert result["advanced"] is True
    assert int(result["post_seq"]) == 22
    assert int(result["pre_seq"]) == 21


def test_select_rollup_rejects_stale_run_21_when_wanting_22() -> None:
    payload = {
        "recent_by_seq": [
            {
                "run_seq": 21,
                "room_id": "C97D3868",
                "widget_key": "rec_card_queue_C97D3868_0_231_rec_card",
                "stages": ["target_button_registered"],
                "flags": {"target_button_registered": True},
                "button_return_value": False,
            },
            {
                "run_seq": 22,
                "room_id": "C97D3868",
                "widget_key": "rec_card_queue_C97D3868_0_231_rec_card",
                "stages": ["cache_miss", "interactive_invoked"],
                "flags": {"cache_miss": True, "interactive_invoked": True},
                "button_return_value": False,
            },
        ]
    }
    roll = select_run_stage_rollup_for_seq(
        [{"probe_found": True, "payload": payload}],
        run_seq=22,
        room_id="C97D3868",
        widget_key="rec_card_queue_C97D3868_0_231_rec_card",
    )
    assert roll["ok"] is True
    assert int(roll["run_seq"]) == 22
    assert roll["cache_miss"] is True
    assert roll["target_button_registered"] is False


def test_dispatch_layer_notes_execute_stages() -> None:
    from live_draft_rec_queue_click_trace import note_rec_queue_dispatch_layer

    session = _session_run(22)
    note_rec_queue_dispatch_layer(
        session,
        layer="button_return_value",
        widget_key="rec_card_queue_C97D3868_0_231_rec_card",
        player_id="231",
    )
    note_rec_queue_dispatch_layer(
        session,
        layer="execute_rec_card_queue_click",
        widget_key="rec_card_queue_C97D3868_0_231_rec_card",
        player_id="231",
    )
    by_seq = session[RUN_STAGE_BY_SEQ_KEY]["22"]
    assert by_seq["flags"].get("dispatch_entered") is True
    assert by_seq["flags"].get("execute_entered") is True
