"""Post-Pause OOB settle / quiescence harness tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_oob_readback import wait_for_oob_settled_after  # noqa: E402


def _snap(gen: int, publish_source: str) -> dict:
    return {
        "ok": True,
        "http_ok": True,
        "parse_ok": True,
        "snapshot_present": True,
        "snapshot": {
            "snapshot_generation": gen,
            "snapshot_server_ts": float(gen),
            "streamlit_session_id": "sid-test",
            "diagnostic_token": "tok",
            "publish_source": publish_source,
            "module_ledger_total_count": gen,
            "critical_ledger_total_count": 0,
            "unrouted_event_count": 0,
            "latest_ingress_summaries": {},
        },
    }


class _FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = float(start)

    def time(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += float(seconds)


class _SeqPage:
    def __init__(self, sequence: list[dict], *, hold_last: bool = True) -> None:
        self.sequence = list(sequence)
        self.hold_last = hold_last
        self.idx = 0
        self.wait_calls = 0

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_calls += 1


class OobSettleAfterPauseTests(unittest.TestCase):
    def _run(
        self,
        sequence: list[tuple[int, str]],
        *,
        min_generation: int = 10,
        poll_interval_ms: int = 100,
        stable_polls_required: int = 4,
        min_settle_s: float = 0.4,
        max_wait_s_before_advance: float = 5.0,
        max_settle_s_after_advance: float = 3.0,
        hold_last: bool = True,
        connected_server_uri: str = "https://example.streamlit.app/~/+",
        require_connected_server_uri: bool = True,
    ) -> dict:
        clock = _FakeClock()
        page = _SeqPage([_snap(g, src) for g, src in sequence], hold_last=hold_last)
        fetches = list(page.sequence)

        def fake_fetch(_page, _path, **_kwargs):
            if page.idx < len(fetches):
                out = fetches[page.idx]
                page.idx += 1
                return dict(out)
            if page.hold_last and fetches:
                return dict(fetches[-1])
            return {"ok": False, "http_ok": False, "parse_ok": False, "snapshot_present": False}

        with patch("stage1_s3_oob_readback.fetch_oob_snapshot_via_page", side_effect=fake_fetch):
            return wait_for_oob_settled_after(
                page,
                static_url_path="/app/static/s3_oob/tok.json",
                min_generation=min_generation,
                poll_interval_ms=poll_interval_ms,
                stable_polls_required=stable_polls_required,
                min_settle_s=min_settle_s,
                max_wait_s_before_advance=max_wait_s_before_advance,
                max_settle_s_after_advance=max_settle_s_after_advance,
                connected_server_uri=connected_server_uri,
                require_connected_server_uri=require_connected_server_uri,
                sleep_fn=clock.sleep,
                time_fn=clock.time,
            )

    def test_first_generation_is_not_final(self) -> None:
        # 10 → 11 finally → … → 15 applied → stable 15
        seq = [
            (10, "initial_pre_click"),
            (11, "runtime_handle_backmsg_finally"),
            (12, "scriptrequests_rerun_consumed"),
            (13, "scriptrunner_run_script_entry"),
            (14, "safe_sessionstate_receive"),
            (15, "sessionstate_applied"),
            (15, "sessionstate_applied"),
            (15, "sessionstate_applied"),
            (15, "sessionstate_applied"),
            (15, "sessionstate_applied"),
            (15, "sessionstate_applied"),
        ]
        out = self._run(seq)
        self.assertTrue(out["ok"])
        self.assertEqual(out["settle_reason"], "oob_generation_quiescent")
        self.assertEqual(out["first_advanced_generation"], 11)
        self.assertEqual(out["final_generation"], 15)
        self.assertEqual(out["final_publish_source"], "sessionstate_applied")
        self.assertNotEqual(out["final_generation"], 11)
        self.assertIn(11, out["generations_observed"])
        self.assertIn(15, out["generations_observed"])

    def test_early_real_stop_settles_at_first_advanced(self) -> None:
        seq = [
            (10, "initial_pre_click"),
            (11, "runtime_handle_backmsg_finally"),
            (11, "runtime_handle_backmsg_finally"),
            (11, "runtime_handle_backmsg_finally"),
            (11, "runtime_handle_backmsg_finally"),
            (11, "runtime_handle_backmsg_finally"),
            (11, "runtime_handle_backmsg_finally"),
        ]
        out = self._run(seq)
        self.assertTrue(out["ok"])
        self.assertEqual(out["settle_reason"], "oob_generation_quiescent")
        self.assertEqual(out["final_generation"], 11)
        self.assertEqual(out["final_publish_source"], "runtime_handle_backmsg_finally")

    def test_intermediate_stop_at_consumed(self) -> None:
        seq = [
            (10, "initial_pre_click"),
            (11, "runtime_handle_backmsg_finally"),
            (12, "scriptrequests_rerun_consumed"),
            (12, "scriptrequests_rerun_consumed"),
            (12, "scriptrequests_rerun_consumed"),
            (12, "scriptrequests_rerun_consumed"),
            (12, "scriptrequests_rerun_consumed"),
            (12, "scriptrequests_rerun_consumed"),
        ]
        out = self._run(seq)
        self.assertTrue(out["ok"])
        self.assertEqual(out["final_generation"], 12)
        self.assertEqual(out["final_publish_source"], "scriptrequests_rerun_consumed")
        self.assertEqual(out["settle_reason"], "oob_generation_quiescent")

    def test_no_advancement_fails(self) -> None:
        seq = [(10, "initial_pre_click")] * 20
        out = self._run(seq, max_wait_s_before_advance=0.5, max_settle_s_after_advance=0.5)
        self.assertFalse(out["ok"])
        self.assertEqual(out["settle_reason"], "oob_no_generation_advance")
        self.assertIsNone(out["first_advanced_generation"])

    def test_continuous_advancement_times_out(self) -> None:
        # Keep climbing forever until settle timeout after first advance.
        seq = [(10 + i, f"src-{10 + i}") for i in range(40)]
        out = self._run(
            seq,
            max_wait_s_before_advance=2.0,
            max_settle_s_after_advance=0.5,
            min_settle_s=2.0,
            stable_polls_required=10,
            hold_last=False,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["settle_reason"], "oob_settle_timeout_after_advance")
        self.assertIsNotNone(out["first_advanced_generation"])
        self.assertGreater(int(out["final_generation"] or 0), 10)

    def test_requires_connected_server_uri(self) -> None:
        out = self._run(
            [(11, "runtime_handle_backmsg_finally")],
            connected_server_uri="",
            require_connected_server_uri=True,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["settle_reason"], "oob_connected_server_uri_unresolved")

    def test_gate_wires_settled_helper_for_pause(self) -> None:
        import inspect

        from run_production_bridge_s3_server_registry_gate import main

        src = inspect.getsource(main)
        # Historical generation-quiescence helper retained; Pause path uses target-evidence settle.
        self.assertIn("wait_for_oob_settled_after", src)
        self.assertIn("wait_for_oob_pause_evidence_settled_after", src)
        self.assertIn("s3_oob_settle_after_pause", src)
        self.assertIn("s3_oob_pause_evidence_settle_after_pause", src)
        # Sibling path still uses first-generation helper.
        self.assertIn("wait_for_oob_generation_after", src)


if __name__ == "__main__":
    unittest.main()
