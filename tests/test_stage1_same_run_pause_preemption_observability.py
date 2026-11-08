"""Same-run Pause-preemption observability harness regressions."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from live_draft_control_center_ui import render_control_center_with_live_chat
from live_draft_stage1_pause_sibling_callsite_diag import CALLSITE_DOM_ID, CALLSITE_IMPL_REV
from live_draft_stage1_s3_oob_snapshot import publish_oob_snapshot, read_oob_snapshot_file, register_oob_channel
from live_draft_stage1_s3_process_global_diag import (
    CRITICAL_SERVER_PHASES,
    _CRITICAL_EVENTS_PER_PHASE,
    append_module_event,
    critical_ledger_by_phase,
    module_ledger_rows,
)


SID = "pause-preempt-obs-sid"
ROOM_ID = "F8ED6CFD"
RUN_ID = "32fe9df1258c46aa"


class SentinelRerunException(BaseException):
    """Harness stand-in for Streamlit rerun control-flow termination."""


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _FakeSt:
    def __init__(self, *, pause_return: bool = False, rerun_raises: bool = False) -> None:
        self.pause_return = pause_return
        self.rerun_raises = rerun_raises
        self.markdowns: list[str] = []
        self.button_calls: list[tuple[str, dict]] = []
        self.rerun_calls = 0

    def markdown(self, html: str = "", **_k) -> None:
        self.markdowns.append(str(html))

    def caption(self, *_a, **_k) -> None:
        return None

    def button(self, label: str, **kwargs):
        self.button_calls.append((str(label), dict(kwargs)))
        if kwargs.get("key") == "live_draft_pause":
            return bool(self.pause_return)
        return False

    def columns(self, *_a, **_k):
        return [_Ctx(), _Ctx()]

    def container(self, **_k):
        return _Ctx()

    def fragment(self, fn):
        return fn

    def rerun(self) -> None:
        self.rerun_calls += 1
        if self.rerun_raises:
            raise SentinelRerunException()


def _room() -> dict:
    return {
        "draft_room_id": ROOM_ID,
        "room_id": ROOM_ID,
        "status": "in_progress",
        "current_pick_index": 0,
        "timer_seconds": 60,
        "timer_started_at": 1_700_000_000.0,
    }


def _session() -> dict:
    return {
        "_solo_component_diag_enabled": True,
        "_solo_stage1_run_id": RUN_ID,
        "_solo_stage1_script_run_seq": 13,
        "diagnostic_run_id": RUN_ID,
    }


def _clear_ledgers() -> None:
    import live_draft_stage1_s3_process_global_diag as pg

    pg._MODULE_LEDGER_BY_STREAMLIT_SESSION.clear()
    pg._CRITICAL_LEDGER_BY_SESSION.clear()
    pg._UNROUTED_ORPHAN_LEDGER.clear()


def _sid_patches(sid: str):
    return [
        patch("live_draft_stage1_s3_process_global_diag.streamlit_session_id_from_ctx", return_value=sid),
        patch("live_draft_stage1_pause_sibling_callsite_diag._streamlit_session_id", return_value=sid),
        patch("live_draft_stage1_pause_sibling_probe._streamlit_session_id", return_value=sid),
        patch("live_draft_stage1_pause_preemption_diag._streamlit_session_id", return_value=sid),
        patch("live_draft_control_center_ui._resolve_commissioner", return_value=(True, None)),
        patch("live_draft_canonical_snapshot.get_live_draft_paint_snapshot", return_value={"team_on_clock": ""}),
        patch("live_draft_cloud_diagnostics.note_control_center_mount"),
        patch("live_draft_chat_ui.render_live_draft_chat_panel", lambda *_a, **_k: None),
        patch("live_draft_chat_system.maybe_post_draft_system_message"),
    ]


def _phases(sid: str) -> list[str]:
    return [str(r.get("phase") or "") for r in module_ledger_rows(sid)]


def _first_index(phases: list[str], name: str) -> int:
    try:
        return phases.index(name)
    except ValueError:
        return -1


class PausePreemptionObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_ledgers()

    def tearDown(self) -> None:
        _clear_ledgers()

    def _render(self, st: _FakeSt, session: dict, room: dict, persist) -> None:
        with ExitStack() as stack:
            for p in _sid_patches(SID):
                stack.enter_context(p)
            render_control_center_with_live_chat(
                st,
                session,
                room,
                cfg={"timer_seconds": 60},
                persist_room=persist,
            )

    def test_pause_false_reaches_sibling_render(self) -> None:
        st = _FakeSt(pause_return=False)
        room = _room()
        persist_calls: list[str] = []

        def persist(_room, reason: str) -> None:
            persist_calls.append(str(reason))

        self._render(st, _session(), room, persist)
        phases = _phases(SID)
        cc = _first_index(phases, "CONTROL_CENTER_FRAGMENT_ENTRY")
        pause_ret = _first_index(phases, "PAUSE_BUTTON_CALL_RETURNED")
        callsite_idxs = [i for i, p in enumerate(phases) if p == "SIBLING_CALLSITE_ENTRY"]
        render = _first_index(phases, "SIBLING_RENDER_ENTRY")
        self.assertGreaterEqual(cc, 0)
        self.assertGreater(pause_ret, cc)
        self.assertEqual(len(callsite_idxs), 2)
        self.assertGreater(callsite_idxs[0], pause_ret)
        self.assertGreater(callsite_idxs[1], callsite_idxs[0])
        self.assertGreater(render, callsite_idxs[1])
        self.assertNotIn("PAUSE_BRANCH_ENTERED", phases)
        self.assertNotIn("PAUSE_RERUN_REQUEST_ENTRY", phases)
        self.assertNotIn("LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL", phases)
        self.assertEqual(persist_calls, [])
        self.assertEqual(st.rerun_calls, 0)
        pause_row = next(r for r in module_ledger_rows(SID) if r.get("phase") == "PAUSE_BUTTON_CALL_RETURNED")
        self.assertIs(pause_row.get("st_button_returned"), False)
        self.assertEqual(pause_row.get("widget_key"), "live_draft_pause")
        callsite_rows = [r for r in module_ledger_rows(SID) if r.get("phase") == "SIBLING_CALLSITE_ENTRY"]
        self.assertFalse(callsite_rows[0].get("import_attempted"))
        self.assertTrue(callsite_rows[1].get("import_attempted"))
        self.assertTrue(callsite_rows[1].get("import_ok"))
        joined = "\n".join(st.markdowns)
        self.assertIn(f'id="{CALLSITE_DOM_ID}"', joined)
        self.assertIn('data-event="SIBLING_CALLSITE_ENTRY"', joined)
        self.assertIn(f'data-impl-rev="{CALLSITE_IMPL_REV}"', joined)
        self.assertIn("live_draft_pause", [k.get("key") for _, k in st.button_calls])

    def test_pause_true_rerun_preempts_sibling(self) -> None:
        st = _FakeSt(pause_return=True, rerun_raises=True)
        room = _room()
        persist_calls: list[str] = []

        def persist(_room, reason: str) -> None:
            persist_calls.append(str(reason))

        with self.assertRaises(SentinelRerunException):
            self._render(st, _session(), room, persist)
        phases = _phases(SID)
        cc = _first_index(phases, "CONTROL_CENTER_FRAGMENT_ENTRY")
        pause_ret = _first_index(phases, "PAUSE_BUTTON_CALL_RETURNED")
        branch = _first_index(phases, "PAUSE_BRANCH_ENTERED")
        rerun_req = _first_index(phases, "PAUSE_RERUN_REQUEST_ENTRY")
        about = _first_index(phases, "LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL")
        self.assertGreaterEqual(cc, 0)
        self.assertGreater(pause_ret, cc)
        self.assertGreater(branch, pause_ret)
        self.assertGreater(rerun_req, branch)
        self.assertGreater(about, rerun_req)
        self.assertNotIn("SIBLING_CALLSITE_ENTRY", phases)
        self.assertNotIn("SIBLING_RENDER_ENTRY", phases)
        pause_row = next(r for r in module_ledger_rows(SID) if r.get("phase") == "PAUSE_BUTTON_CALL_RETURNED")
        self.assertIs(pause_row.get("st_button_returned"), True)
        about_row = next(r for r in module_ledger_rows(SID) if r.get("phase") == "LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL")
        self.assertEqual(about_row.get("source"), "pause_draft")
        self.assertTrue(about_row.get("rerun_allowed"))
        self.assertEqual(persist_calls, ["pause_draft"])
        self.assertEqual(st.rerun_calls, 1)
        self.assertEqual(room.get("status"), "paused")

    def test_pause_true_rerun_blocked_continues_to_sibling(self) -> None:
        st = _FakeSt(pause_return=True, rerun_raises=True)
        room = _room()

        def _block(_session, source, *, room=None):
            if source == "pause_draft":
                return False, "test_block"
            return True, ""

        with patch("live_draft_safe_mode.is_rerun_allowed", side_effect=_block):
            self._render(st, _session(), room, lambda *_a, **_k: None)
        phases = _phases(SID)
        self.assertIn("PAUSE_BUTTON_CALL_RETURNED", phases)
        self.assertIn("PAUSE_BRANCH_ENTERED", phases)
        self.assertIn("PAUSE_RERUN_REQUEST_ENTRY", phases)
        self.assertIn("LIVE_DRAFT_RERUN_BLOCKED", phases)
        self.assertNotIn("LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL", phases)
        self.assertIn("SIBLING_CALLSITE_ENTRY", phases)
        self.assertIn("SIBLING_RENDER_ENTRY", phases)
        pause_ret = _first_index(phases, "PAUSE_BUTTON_CALL_RETURNED")
        branch = _first_index(phases, "PAUSE_BRANCH_ENTERED")
        rerun_req = _first_index(phases, "PAUSE_RERUN_REQUEST_ENTRY")
        blocked = _first_index(phases, "LIVE_DRAFT_RERUN_BLOCKED")
        callsite = _first_index(phases, "SIBLING_CALLSITE_ENTRY")
        render = _first_index(phases, "SIBLING_RENDER_ENTRY")
        self.assertGreater(branch, pause_ret)
        self.assertGreater(rerun_req, branch)
        self.assertGreater(blocked, rerun_req)
        self.assertGreater(callsite, blocked)
        self.assertGreater(render, callsite)
        self.assertEqual(st.rerun_calls, 0)
        pause_row = next(r for r in module_ledger_rows(SID) if r.get("phase") == "PAUSE_BUTTON_CALL_RETURNED")
        self.assertIs(pause_row.get("st_button_returned"), True)

    def test_callsite_and_pause_survive_yield_ready_flood(self) -> None:
        for ph, extra in (
            ("PAUSE_BUTTON_CALL_RETURNED", {"st_button_returned": True, "widget_key": "live_draft_pause"}),
            ("PAUSE_BRANCH_ENTERED", {"source": "pause_draft", "pause_button_returned": True}),
            ("PAUSE_RERUN_REQUEST_ENTRY", {"source": "pause_draft"}),
            ("LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL", {"source": "pause_draft", "rerun_allowed": True}),
            ("LIVE_DRAFT_RERUN_BLOCKED", {"source": "pause_draft", "rerun_allowed": False}),
            ("SIBLING_CALLSITE_ENTRY", {"import_attempted": False, "room_id": ROOM_ID}),
            ("SIBLING_CALLSITE_ENTRY", {"import_attempted": True, "import_ok": True, "room_id": ROOM_ID}),
        ):
            append_module_event(SID, ph, **extra)
        for i in range(80):
            append_module_event(SID, "SCRIPTREQUESTS_ON_YIELD_ENTRY", fragment_id=f"y-{i}")
            append_module_event(SID, "SCRIPTREQUESTS_ON_YIELD_RESULT", returned_is_rerun=False)
            append_module_event(SID, "SCRIPTREQUESTS_ON_READY_ENTRY", fragment_id=f"r-{i}")
            append_module_event(SID, "SCRIPTREQUESTS_ON_READY_RESULT", returned_is_rerun=False)
        mixed = module_ledger_rows(SID)
        self.assertEqual(len(mixed), 96)
        mixed_phases = {r.get("phase") for r in mixed}
        self.assertTrue({"SCRIPTREQUESTS_ON_YIELD_ENTRY", "SCRIPTREQUESTS_ON_READY_ENTRY"} <= mixed_phases)
        by_phase = critical_ledger_by_phase(SID)
        for ph in (
            "PAUSE_BUTTON_CALL_RETURNED",
            "PAUSE_BRANCH_ENTERED",
            "PAUSE_RERUN_REQUEST_ENTRY",
            "LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL",
            "LIVE_DRAFT_RERUN_BLOCKED",
        ):
            self.assertIn(ph, CRITICAL_SERVER_PHASES)
            self.assertEqual(len(by_phase.get(ph) or []), 1, ph)
        self.assertIn("SIBLING_CALLSITE_ENTRY", CRITICAL_SERVER_PHASES)
        self.assertEqual(len(by_phase.get("SIBLING_CALLSITE_ENTRY") or []), 2)
        self.assertFalse((by_phase["SIBLING_CALLSITE_ENTRY"][0] or {}).get("import_attempted"))
        self.assertTrue((by_phase["SIBLING_CALLSITE_ENTRY"][1] or {}).get("import_attempted"))
        self.assertLessEqual(len(by_phase.get("SCRIPTREQUESTS_ON_YIELD_ENTRY") or []), _CRITICAL_EVENTS_PER_PHASE)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("live_draft_stage1_s3_oob_snapshot.oob_snapshot_root", return_value=Path(tmp)):
                channel = register_oob_channel(SID, {})
                publish_oob_snapshot(
                    SID,
                    publish_source="runtime_handle_backmsg_finally",
                    session={},
                    diagnostic_token=channel["diagnostic_token"],
                )
                snap = read_oob_snapshot_file(channel["diagnostic_token"])
        oob_by_phase = snap.get("critical_ledger_by_phase") or {}
        self.assertTrue(oob_by_phase.get("PAUSE_BUTTON_CALL_RETURNED"))
        self.assertTrue(oob_by_phase.get("PAUSE_BRANCH_ENTERED"))
        self.assertTrue(oob_by_phase.get("PAUSE_RERUN_REQUEST_ENTRY"))
        self.assertTrue(oob_by_phase.get("LIVE_DRAFT_ST_RERUN_ABOUT_TO_CALL"))
        self.assertEqual(len(oob_by_phase.get("SIBLING_CALLSITE_ENTRY") or []), 2)

    def test_pause_widget_key_and_label_unchanged(self) -> None:
        import inspect

        from live_draft_control_center_ui import render_live_draft_control_center

        src = inspect.getsource(render_live_draft_control_center)
        self.assertIn('key="live_draft_pause"', src)
        self.assertIn("⏸ Pause Draft", src)
        self.assertIn("live_draft_pause_timer", src)
        self.assertIn('request_live_draft_rerun(st, session, "pause_draft", room=room)', src)


if __name__ == "__main__":
    unittest.main()
