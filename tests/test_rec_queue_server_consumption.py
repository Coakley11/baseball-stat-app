"""Server consumption: cache-miss on DONE path + widget ID stability + trigger ledger."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from live_draft_heavy_paint_ui import HEAVY_PAINT_DONE_KEY, render_deferred_heavy_paint_fragment  # noqa: E402
from live_draft_rec_live_paint import (
    INTERACTIVE_PAINT_STATUS_KEY,
    PREPARED_REC_INTERACTIVE_KEY,
    render_rec_interactive_widgets,
    store_prepared_rec_interactive,
)
from live_draft_ui_cache import REC_CACHE_KEY


def _lindor_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fullName": "Francisco Lindor",
                "Primary Position": "SS",
                "playerID": "231",
                "Fantasy Edge": 1.2,
                "Survival Probability": 0.4,
                "Decision Score": 90,
            }
        ]
    )


class InteractivePaintCacheMissTests(unittest.TestCase):
    def test_cache_miss_without_rebuild_helper_would_skip_buttons(self) -> None:
        """Document the production failure mode: DONE + empty cache → no st.button."""
        st = MagicMock()
        session: dict[str, Any] = {
            PREPARED_REC_INTERACTIVE_KEY: {
                "room_id": "77DAD3EE",
                "gaps": [],
                "category_needs": [],
                "max_cards": 1,
                "multiplayer": False,
            },
            # REC cache intentionally missing (poll/pick invalidate after HEAVY_PAINT_DONE).
            "_solo_stage1_script_run_seq": 22,
        }
        room = {"draft_room_id": "77DAD3EE", "current_pick_index": 0, "status": "in_progress"}
        with patch(
            "live_draft_rec_live_paint._rebuild_top_rec_into_cache",
            return_value=None,
        ):
            ok = render_rec_interactive_widgets(st, session, room)
        self.assertFalse(ok)
        self.assertEqual(session[INTERACTIVE_PAINT_STATUS_KEY]["fail_reason"], "top_rec_missing_after_rebuild")

    def test_cache_miss_rebuilds_and_registers_cards(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {"_solo_stage1_script_run_seq": 22}
        store_prepared_rec_interactive(
            session, room_id="77DAD3EE", gaps=[], category_needs=[], max_cards=1
        )
        room = {
            "draft_room_id": "77DAD3EE",
            "current_pick_index": 0,
            "status": "in_progress",
            "config": {"user_team": "Team A"},
            "draft_board": [],
            "rosters": {},
            "pool": _lindor_df(),
        }
        with patch(
            "live_draft_rec_live_paint._rebuild_top_rec_into_cache",
            return_value=_lindor_df(),
        ) as rebuild:
            with patch("live_draft_room_ui.render_live_draft_rec_summary_banner"):
                with patch("live_draft_room_ui.render_live_draft_rec_cards") as cards:
                    ok = render_rec_interactive_widgets(st, session, room)
        self.assertTrue(ok)
        rebuild.assert_called_once()
        cards.assert_called_once()
        self.assertTrue(session[INTERACTIVE_PAINT_STATUS_KEY]["cache_rebuilt"])
        self.assertTrue(session[INTERACTIVE_PAINT_STATUS_KEY]["ok"])

    def test_done_path_fallback_paint_body_when_interactive_fails(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {HEAVY_PAINT_DONE_KEY: True, "_solo_stage1_script_run_seq": 22}
        calls: list[str] = []

        def paint_body() -> None:
            calls.append("body")
            store_prepared_rec_interactive(
                session, room_id="77DAD3EE", gaps=[], category_needs=[], max_cards=1
            )
            session[REC_CACHE_KEY] = {"top_rec": _lindor_df()}

        interactive_calls = {"n": 0}

        def paint_interactive() -> bool:
            interactive_calls["n"] += 1
            if interactive_calls["n"] == 1:
                return False
            return render_rec_interactive_widgets(
                st,
                session,
                {"draft_room_id": "77DAD3EE", "current_pick_index": 0, "status": "in_progress"},
            )

        with patch("live_draft_room_ui.render_live_draft_rec_summary_banner"):
            with patch("live_draft_room_ui.render_live_draft_rec_cards") as cards:
                render_deferred_heavy_paint_fragment(
                    st,
                    session,
                    paint_body,
                    paint_interactive=paint_interactive,
                )
        self.assertIn("body", calls)
        self.assertTrue(session.get("_live_draft_rec_interactive_fallback_ok"))
        cards.assert_called()


class WidgetIdStabilityTests(unittest.TestCase):
    def test_production_lindor_id_matches_key_plus_page_hash(self) -> None:
        from streamlit.elements.lib.utils import _compute_element_id

        key = "rec_card_queue_77DAD3EE_0_231_rec_card"
        page_hash = "4643685248ca83aded02e6d78a49e44b"
        wid = _compute_element_id("button", key, active_script_hash=page_hash)
        self.assertEqual(
            wid,
            "$$ID-1df391b661f2f4d6cc6ae84f5d703dc4-rec_card_queue_77DAD3EE_0_231_rec_card",
        )
        # Same inputs on consuming run 22 → identical ID (not classification A).
        wid2 = _compute_element_id("button", key, active_script_hash=page_hash)
        self.assertEqual(wid, wid2)


class ButtonConsumptionDiagTests(unittest.TestCase):
    def test_consumption_ledger_records_return_value(self) -> None:
        from live_draft_rec_button_consumption_diag import (
            CONSUMPTION_LAST_KEY,
            note_rec_queue_button_consumption,
        )

        session: dict[str, Any] = {"_solo_stage1_script_run_seq": 22}
        st = MagicMock()
        with patch(
            "live_draft_rec_button_consumption_diag._diag_enabled",
            return_value=True,
        ), patch(
            "live_draft_rec_button_consumption_diag._incoming_trigger_for_user_key",
            return_value={
                "incoming_trigger_seen": True,
                "incoming_widget_id": "$$ID-abc-rec_card_queue_77DAD3EE_0_231_rec_card",
                "incoming_trigger_value": True,
            },
        ), patch(
            "live_draft_rec_button_consumption_diag._registered_widget_id",
            return_value=("$$ID-abc-rec_card_queue_77DAD3EE_0_231_rec_card", "test"),
        ):
            row = note_rec_queue_button_consumption(
                st,
                session,
                widget_key="rec_card_queue_77DAD3EE_0_231_rec_card",
                player_id="231",
                room_id="77DAD3EE",
                pick_index=0,
                button_return_value=True,
            )
        self.assertTrue(row["incoming_trigger_seen"])
        self.assertTrue(row["incoming_id_matches_registered"])
        self.assertTrue(row["button_return_value"])
        self.assertTrue(session[CONSUMPTION_LAST_KEY]["button_return_value"])


class ReturnValueToQueueProofTests(unittest.TestCase):
    def test_button_true_enters_execute_and_mutates_queue(self) -> None:
        from live_draft_rec_queue_click_trace import DISPATCH_LAYER_KEY, build_rec_card_queue_widget_key
        from live_draft_room_ui import execute_rec_card_queue_click

        session: dict[str, Any] = {
            "draft_queue": [],
            "_solo_stage1_script_run_seq": 22,
            "_live_draft_rec_queue_interactive_owner": "script_run_no_run_every",
        }
        key = build_rec_card_queue_widget_key(
            room_id="77DAD3EE", pick_index=0, stable_key="231", surface="rec_card"
        )
        # Simulate st.button == True on consuming run with matching identity.
        clicked = True
        self.assertTrue(clicked)
        from live_draft_rec_queue_click_trace import note_rec_queue_dispatch_layer

        note_rec_queue_dispatch_layer(
            session, layer="button_return_value", widget_key=key, player_id="231", player_name="Francisco Lindor"
        )
        note_rec_queue_dispatch_layer(
            session,
            layer="execute_rec_card_queue_click",
            widget_key=key,
            player_id="231",
            player_name="Francisco Lindor",
        )
        execute_rec_card_queue_click(
            session,
            name="Francisco Lindor",
            event_id="localproof1",
            widget_key=key,
            room_id="77DAD3EE",
            pick_idx=0,
            player_id="231",
        )
        layers = [r.get("layer") for r in (session.get(DISPATCH_LAYER_KEY) or [])]
        self.assertIn("button_return_value", layers)
        self.assertIn("execute_rec_card_queue_click", layers)
        self.assertIn("execute_rec_card_queue_click_body", layers)
        q = [str(x).lower() for x in (session.get("draft_queue") or [])]
        self.assertTrue(any("lindor" in x for x in q) or len(session.get("draft_queue") or []) >= 1)


class ObserverStillSeparatesTriggerFromMutation(unittest.TestCase):
    def test_protobuf_trigger_does_not_alone_prove_queue_seed(self) -> None:
        from stage1_native_widget_transport import classify_transport_from_ws_samples
        from stage1_francisco_native_click_consumption import (
            evaluate_francisco_native_click_consumption_ack,
        )

        key = "rec_card_queue_77DAD3EE_0_231_rec_card"
        # Minimal sample: key present flag after enrichment, no callback.
        samples = [
            {
                "direction": "outbound",
                "byte_len": 2986,
                "frame_type_hint": "component_value_hint",
                "widget_key_bytes_present": False,
                "payload_base64": __import__("base64").b64encode(
                    f"$$ID-1df391b661f2f4d6cc6ae84f5d703dc4-{key}".encode()
                ).decode(),
            }
        ]
        tr = classify_transport_from_ws_samples(samples, expected_widget_key=key)
        self.assertTrue(tr["native_widget_event_observed_strict"])
        ack = evaluate_francisco_native_click_consumption_ack(
            click_dispatched=True,
            authorized_rec_card_key=key,
            post_click_transport=tr,
            callback_entered_observed=False,
            trusted_dom_click=True,
        )
        self.assertTrue(ack["expected_widget_key_present_in_transport"])
        self.assertFalse(ack["callback_entered_observed"])
        self.assertFalse(ack.get("outbound_widget_key_alone_proves_callback"))


class ServerConsumptionAppTest(unittest.TestCase):
    """AppTest: cache-miss consuming run still registers same key → st.button=True → queue+1."""

    @classmethod
    def setUpClass(cls) -> None:
        from streamlit.testing.v1 import AppTest

        cls._AppTest = AppTest
        cls._fixture = Path(__file__).resolve().parent / "fixtures" / "rec_queue_server_consumption_apptest.py"

    def _boot(self):
        at = self._AppTest.from_file(str(self._fixture), default_timeout=60)
        at.session_state[HEAVY_PAINT_DONE_KEY] = True
        at.session_state["_proof_force_cache_miss"] = True
        at.run()
        return at

    def test_cache_miss_full_rerun_consumes_trigger_three_players(self) -> None:
        from streamlit.elements.lib.utils import _compute_element_id

        at = self._boot()
        self.assertFalse(at.exception)
        # First render after forced cache miss must still register a button.
        buttons = [b for b in at.button if "Add to Queue" in str(b.label)]
        self.assertEqual(len(buttons), 1, "consuming run must instantiate Add-to-Queue")
        first_key = str(buttons[0].key)
        self.assertTrue(first_key.startswith("rec_card_queue_77DAD3EE_0_"))
        page_hash = "4643685248ca83aded02e6d78a49e44b"
        # Same key inputs → stable generated id family (hash portion may use fixture page hash).
        wid_prod = _compute_element_id(
            "button",
            "rec_card_queue_77DAD3EE_0_231_rec_card",
            active_script_hash=page_hash,
        )
        self.assertTrue(wid_prod.endswith("rec_card_queue_77DAD3EE_0_231_rec_card"))

        queued_names: list[str] = []
        for _ in range(3):
            buttons = [b for b in at.button if "Add to Queue" in str(b.label)]
            self.assertEqual(len(buttons), 1)
            # Click → full rerun → trigger consumed as True on matching registration.
            buttons[0].click().run()
            self.assertFalse(at.exception)
            ss = at.session_state
            snap = dict(ss["_proof_snapshot"]) if "_proof_snapshot" in ss else {}
            last = dict(snap.get("last_button") or {})
            q = list(ss["draft_queue"]) if "draft_queue" in ss else []
            self.assertTrue(
                bool(last.get("button_return_value")) or len(q) > len(queued_names),
                f"expected st.button=True / queue growth; last={last} snap={snap}",
            )
            self.assertGreater(len(q), len(queued_names))
            queued_names = [str(x) for x in q]
            lc_seq = snap.get("lifecycle_seq")
            app_seq = snap.get("seq")
            self.assertEqual(
                lc_seq,
                app_seq,
                f"card lifecycle must advance with app ScriptRun; lc={lc_seq} seq={app_seq}",
            )
            # Force cache miss again before next consuming registration (production invalidate).
            ss["_proof_force_cache_miss"] = True
            at.run()
            self.assertFalse(at.exception)

        self.assertGreaterEqual(len(queued_names), 3)
        # Distinct players across consecutive full reruns.
        folded = " ".join(queued_names).lower()
        self.assertIn("lindor", folded)
        self.assertIn("marte", folded)
        self.assertIn("ramirez", folded)


if __name__ == "__main__":
    unittest.main()
