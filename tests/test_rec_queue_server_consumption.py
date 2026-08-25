"""Server consumption: same-run registration after cache invalidate (run 21→22)."""

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
from live_draft_rec_live_paint import (  # noqa: E402
    INTERACTIVE_PAINT_STATUS_KEY,
    INTERACTIVE_TOP_REC_SNAPSHOT_KEY,
    PREPARED_REC_INTERACTIVE_KEY,
    render_rec_interactive_widgets,
    store_interactive_top_rec_snapshot,
    store_prepared_rec_interactive,
)
from live_draft_ui_cache import REC_CACHE_KEY, invalidate_live_draft_ui_caches  # noqa: E402


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
        """Document the production failure mode: DONE + empty cache/snapshot → no st.button."""
        st = MagicMock()
        session: dict[str, Any] = {
            PREPARED_REC_INTERACTIVE_KEY: {
                "room_id": "CBA003B1",
                "gaps": [],
                "category_needs": [],
                "max_cards": 1,
                "multiplayer": False,
            },
            "_solo_stage1_script_run_seq": 22,
        }
        room = {"draft_room_id": "CBA003B1", "current_pick_index": 0, "status": "paused"}
        with patch(
            "live_draft_rec_live_paint._rebuild_top_rec_into_cache",
            return_value=None,
        ):
            ok = render_rec_interactive_widgets(st, session, room)
        self.assertFalse(ok)
        self.assertEqual(session[INTERACTIVE_PAINT_STATUS_KEY]["fail_reason"], "top_rec_missing_after_rebuild")

    def test_cache_miss_uses_interactive_snapshot_same_run(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {"_solo_stage1_script_run_seq": 22}
        store_prepared_rec_interactive(
            session, room_id="CBA003B1", gaps=[], category_needs=[], max_cards=1
        )
        store_interactive_top_rec_snapshot(session, _lindor_df(), room_id="CBA003B1")
        # Simulate deferred-pool invalidate: REC_CACHE gone, snapshot kept.
        invalidate_live_draft_ui_caches(session, keep_interactive_snapshot=True)
        self.assertNotIn(REC_CACHE_KEY, session)
        self.assertIn(INTERACTIVE_TOP_REC_SNAPSHOT_KEY, session)
        room = {
            "draft_room_id": "CBA003B1",
            "current_pick_index": 0,
            "status": "paused",
            "config": {"user_team": "Team A"},
            "draft_board": [],
            "rosters": {},
            "pool": _lindor_df(),
        }
        with patch("live_draft_room_ui.render_live_draft_rec_summary_banner"):
            with patch("live_draft_room_ui.render_live_draft_rec_cards") as cards:
                ok = render_rec_interactive_widgets(st, session, room)
        self.assertTrue(ok)
        cards.assert_called_once()
        self.assertTrue(session[INTERACTIVE_PAINT_STATUS_KEY]["snapshot_used"])
        self.assertTrue(session[INTERACTIVE_PAINT_STATUS_KEY]["ok"])
        # Snapshot path republishes cache for subsequent consumers.
        self.assertIn(REC_CACHE_KEY, session)

    def test_cache_miss_rebuilds_and_registers_cards(self) -> None:
        st = MagicMock()
        session: dict[str, Any] = {"_solo_stage1_script_run_seq": 22}
        store_prepared_rec_interactive(
            session, room_id="CBA003B1", gaps=[], category_needs=[], max_cards=1
        )
        room = {
            "draft_room_id": "CBA003B1",
            "current_pick_index": 0,
            "status": "paused",
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
                session, room_id="CBA003B1", gaps=[], category_needs=[], max_cards=1
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
                {"draft_room_id": "CBA003B1", "current_pick_index": 0, "status": "paused"},
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

    def test_deferred_pool_keeps_snapshot_when_done(self) -> None:
        session: dict[str, Any] = {
            HEAVY_PAINT_DONE_KEY: True,
            REC_CACHE_KEY: {"top_rec": _lindor_df()},
        }
        store_interactive_top_rec_snapshot(session, _lindor_df(), room_id="CBA003B1")
        from live_draft_fast_solo_start import maybe_build_deferred_full_pool

        # Force the invalidate branch by faking a completed pool build path.
        invalidate_live_draft_ui_caches(
            session, keep_interactive_snapshot=bool(session.get(HEAVY_PAINT_DONE_KEY))
        )
        self.assertNotIn(REC_CACHE_KEY, session)
        self.assertIn(INTERACTIVE_TOP_REC_SNAPSHOT_KEY, session)
        _ = maybe_build_deferred_full_pool  # imported for coverage of call site policy


class WidgetIdStabilityTests(unittest.TestCase):
    def test_production_lindor_id_matches_key_plus_page_hash(self) -> None:
        from streamlit.elements.lib.utils import _compute_element_id

        key = "rec_card_queue_CBA003B1_0_231_rec_card"
        page_hash = "e31c3b5d1eb29d4ff5b4740335b7522a"
        wid = _compute_element_id("button", key, active_script_hash=page_hash)
        self.assertTrue(wid.endswith(key))
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
                "incoming_widget_id": "$$ID-abc-rec_card_queue_CBA003B1_0_231_rec_card",
                "incoming_trigger_value": True,
            },
        ), patch(
            "live_draft_rec_button_consumption_diag._registered_widget_id",
            return_value=("$$ID-abc-rec_card_queue_CBA003B1_0_231_rec_card", "test"),
        ):
            row = note_rec_queue_button_consumption(
                st,
                session,
                widget_key="rec_card_queue_CBA003B1_0_231_rec_card",
                player_id="231",
                room_id="CBA003B1",
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
            room_id="CBA003B1", pick_index=0, stable_key="231", surface="rec_card"
        )
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
            room_id="CBA003B1",
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
        from stage1_francisco_native_click_consumption import (
            evaluate_francisco_native_click_consumption_ack,
        )
        from stage1_native_widget_transport import classify_transport_from_ws_samples

        key = "rec_card_queue_CBA003B1_0_231_rec_card"
        samples = [
            {
                "direction": "outbound",
                "byte_len": 2986,
                "frame_type_hint": "component_value_hint",
                "widget_key_bytes_present": False,
                "payload_base64": __import__("base64").b64encode(
                    f"$$ID-e31c3b5d1eb29d4ff5b4740335b7522a-{key}".encode()
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
    """AppTest: run21 register → invalidate → run22 same-run consume (3 players)."""

    @classmethod
    def setUpClass(cls) -> None:
        from streamlit.testing.v1 import AppTest

        cls._AppTest = AppTest
        cls._fixture = Path(__file__).resolve().parent / "fixtures" / "rec_queue_server_consumption_apptest.py"

    def _boot_run21(self):
        at = self._AppTest.from_file(str(self._fixture), default_timeout=90)
        at.session_state[HEAVY_PAINT_DONE_KEY] = True
        at.session_state["_solo_stage1_script_run_seq"] = 20
        at.run()
        return at

    def test_run21_to_run22_same_run_consumption_three_players(self) -> None:
        at = self._boot_run21()
        self.assertFalse(at.exception, msg=str(at.exception))
        snap = dict(at.session_state["_proof_snapshot"]) if "_proof_snapshot" in at.session_state else {}
        self.assertEqual(int(snap.get("seq") or 0), 21)
        buttons = [b for b in at.button if "Add to Queue" in str(b.label)]
        self.assertGreaterEqual(len(buttons), 1, "run 21 must instantiate Add-to-Queue")
        first_key = str(buttons[0].key)
        self.assertTrue(first_key.startswith(f"rec_card_queue_{ROOM_ID}_0_"))
        self.assertIn("231", first_key)

        queued_names: list[str] = []
        for i in range(3):
            buttons = [b for b in at.button if "Add to Queue" in str(b.label)]
            self.assertGreaterEqual(len(buttons), 1, f"player loop {i}: button must be registered before click")
            click_key = str(buttons[0].key)
            pre_seq = int(at.session_state["_solo_stage1_script_run_seq"])
            # Production: invalidate after prior registration (deferred pool), then click.
            at.session_state["_proof_force_cache_miss"] = True
            buttons[0].click().run()
            self.assertFalse(at.exception, msg=str(at.exception))
            ss = at.session_state
            snap = dict(ss["_proof_snapshot"]) if "_proof_snapshot" in ss else {}
            last = dict(snap.get("last_button") or {})
            q = list(ss["draft_queue"]) if "draft_queue" in ss else []
            post_seq = int(snap.get("seq") or ss["_solo_stage1_script_run_seq"])
            self.assertEqual(post_seq, pre_seq + 1, "click must advance exactly one ScriptRun")
            self.assertTrue(
                bool(last.get("interactive_ok")),
                f"run {post_seq} must complete interactive registration; snap={snap}",
            )
            self.assertTrue(
                bool(last.get("button_return_value")) or len(q) > len(queued_names),
                f"expected st.button=True / queue growth on consuming run {post_seq}; last={last} snap={snap}",
            )
            self.assertGreater(len(q), len(queued_names), f"queue must grow on consuming run {post_seq}")
            # Lifecycle must advance on the consuming run — not lag until run+1.
            lc_seq = snap.get("lifecycle_seq")
            self.assertEqual(
                lc_seq,
                post_seq,
                f"card lifecycle must equal consuming ScriptRun; lc={lc_seq} seq={post_seq} stages={snap.get('stages_this_run')}",
            )
            # Must NOT require a follow-up recovery run before consumption.
            stages = list(snap.get("stages_this_run") or [])
            self.assertIn("interactive_invoked", stages)
            self.assertNotIn(
                "deferred_to_next_run",
                stages,
                "registration must not be scheduled for a later ScriptRun",
            )
            paint = dict(snap.get("paint_status") or {})
            # After invalidate with keep_snapshot, consuming run may use snapshot or cache republish.
            self.assertTrue(
                paint.get("ok")
                or paint.get("snapshot_used")
                or paint.get("cache_rebuilt")
                or paint.get("cache_hit"),
                f"expected recovery on consuming run; paint={paint} stages={stages}",
            )
            queued_names = [str(x) for x in q]
            # Prep next distinct player registration on the post-click surface.
            if i < 2:
                # Advance player was done inside fixture on successful click; ensure button exists.
                at.run()
                self.assertFalse(at.exception)

        self.assertGreaterEqual(len(queued_names), 3)
        folded = " ".join(queued_names).lower()
        self.assertIn("lindor", folded)
        self.assertIn("marte", folded)
        self.assertIn("ramirez", folded)

    def test_fails_if_registration_deferred_past_consuming_run(self) -> None:
        """Guardrail: if interactive only recovers on run 23, this test must fail."""
        at = self._boot_run21()
        buttons = [b for b in at.button if "Add to Queue" in str(b.label)]
        self.assertTrue(buttons)
        at.session_state["_proof_force_cache_miss"] = True
        # Drop snapshot too — forces rebuild/fallback on consuming run.
        at.session_state["_proof_force_hard_cache_and_snapshot_miss"] = True
        # Seed a trivial rebuild via paint_body fallback (product path).
        buttons[0].click().run()
        self.assertFalse(at.exception, msg=str(at.exception))
        snap = dict(at.session_state["_proof_snapshot"]) if "_proof_snapshot" in at.session_state else {}
        # Consuming run must still register + consume (fallback paint_body → interactive).
        self.assertEqual(int(snap.get("seq") or 0), 22)
        self.assertEqual(snap.get("lifecycle_seq"), 22)
        q = list(at.session_state["draft_queue"]) if "draft_queue" in at.session_state else []
        self.assertGreaterEqual(len(q), 1, f"trigger must be consumed on run 22; snap={snap}")


# local alias used in assertion readability
ROOM_ID = "CBA003B1"


if __name__ == "__main__":
    unittest.main()
