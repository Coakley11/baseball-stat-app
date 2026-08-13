"""Post-Pause OOB target Pause-evidence settle harness tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from stage1_s3_oob_readback import (  # noqa: E402
    is_target_pause_scheduler_row,
    merge_oob_snapshot_into_accumulator,
    oob_row_identity,
    wait_for_oob_pause_evidence_settled_after,
)
from stage1_s3_r3_observability_classify import (  # noqa: E402
    classify_s3_with_observability,
    pause_observability_chain,
)

SID = "977d7bdf-c117-4182-be33-634d3e66874b"
OTHER_SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PAUSE_WID = "$$ID-pause-widget"


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

    def wait_for_timeout(self, ms: int) -> None:
        return None


def _row(
    phase: str,
    *,
    event_id: str,
    ts: float,
    sid: str = SID,
    pause_present: bool = True,
    pause_widget_id: str = PAUSE_WID,
    **extra: object,
) -> dict:
    out: dict = {
        "phase": phase,
        "event_id": event_id,
        "ts": ts,
        "streamlit_session_id": sid,
        "pause_present": pause_present,
    }
    if pause_widget_id:
        out["pause_proto"] = {"id": pause_widget_id, "trigger_value": True}
        out["activated_triggers"] = [pause_widget_id]
    out.update(extra)
    return out


def _unrelated_row(phase: str, *, event_id: str, ts: float, sid: str = SID) -> dict:
    return {
        "phase": phase,
        "event_id": event_id,
        "ts": ts,
        "streamlit_session_id": sid,
        "pause_present": False,
    }


def _snap(
    gen: int,
    *,
    publish_source: str = "runtime_handle_backmsg_finally",
    critical: list[dict] | None = None,
    module: list[dict] | None = None,
) -> dict:
    return {
        "ok": True,
        "http_ok": True,
        "parse_ok": True,
        "snapshot_present": True,
        "snapshot": {
            "snapshot_generation": gen,
            "snapshot_server_ts": float(gen),
            "streamlit_session_id": SID,
            "diagnostic_token": "tok",
            "publish_source": publish_source,
            "module_ledger_rows": list(module or []),
            "critical_ledger_rows": list(critical or []),
            "module_ledger_total_count": len(module or []),
            "critical_ledger_total_count": len(critical or []),
            "unrouted_event_count": 0,
            "latest_ingress_summaries": {},
        },
    }


class PauseEvidenceSettleTests(unittest.TestCase):
    def _run(
        self,
        fetches: list[dict],
        *,
        min_generation: int = 80,
        poll_interval_ms: int = 100,
        stable_polls_required: int = 4,
        min_stable_s: float = 0.3,
        max_wait_s_before_first_evidence: float = 5.0,
        max_wait_s_after_first_evidence: float = 2.0,
        hold_last: bool = True,
        pause_widget_id: str = PAUSE_WID,
        streamlit_session_id: str = SID,
        connected_server_uri: str = "https://example.streamlit.app/~/+",
        require_connected_server_uri: bool = True,
    ) -> dict:
        clock = _FakeClock()
        page = _SeqPage(fetches, hold_last=hold_last)
        seq = list(fetches)

        def fake_fetch(_page, _path, **_kwargs):
            if page.idx < len(seq):
                out = seq[page.idx]
                page.idx += 1
                return dict(out)
            if page.hold_last and seq:
                return dict(seq[-1])
            return {"ok": False, "http_ok": False, "parse_ok": False, "snapshot_present": False}

        with patch("stage1_s3_oob_readback.fetch_oob_snapshot_via_page", side_effect=fake_fetch):
            return wait_for_oob_pause_evidence_settled_after(
                page,
                static_url_path="/app/static/s3_oob/tok.json",
                min_generation=min_generation,
                streamlit_session_id=streamlit_session_id,
                pause_widget_id=pause_widget_id,
                poll_interval_ms=poll_interval_ms,
                stable_polls_required=stable_polls_required,
                min_stable_s=min_stable_s,
                max_wait_s_before_first_evidence=max_wait_s_before_first_evidence,
                max_wait_s_after_first_evidence=max_wait_s_after_first_evidence,
                connected_server_uri=connected_server_uri,
                require_connected_server_uri=require_connected_server_uri,
                sleep_fn=clock.sleep,
                time_fn=clock.time,
            )

    def test_a_continuous_unrelated_global_generations_settles(self) -> None:
        # Global gens keep climbing; target Pause evidence stabilizes after gen 93.
        rt = _row("RUNTIME_BACKMSG_ENTRY", event_id="e-rt", ts=1.0)
        app = _row("APPSESSION_BACKMSG_ENTRY", event_id="e-app", ts=1.1)
        req = _row("APPSESSION_REQUEST_RERUN_ENTRY", event_id="e-req", ts=1.2)
        fetches = [
            _snap(80, critical=[], publish_source="pre"),
            _snap(89, critical=[rt], publish_source="runtime_handle_backmsg_finally"),
            _snap(93, critical=[app], publish_source="appsession"),
            _snap(95, critical=[req], publish_source="appsession_req"),
            _snap(98, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg-1", ts=2.0)]),
            _snap(102, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg-2", ts=2.1)]),
            _snap(104, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg-3", ts=2.2)]),
            _snap(107, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg-4", ts=2.3)]),
            _snap(110, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg-5", ts=2.4)]),
            _snap(188, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg-6", ts=2.5)]),
        ]
        out = self._run(
            fetches,
            max_wait_s_after_first_evidence=5.0,
            stable_polls_required=8,
            min_stable_s=0.7,
            poll_interval_ms=100,
            hold_last=True,
        )
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["settle_reason"], "oob_pause_evidence_quiescent")
        self.assertIn(89, out["generations_observed"])
        self.assertIn(188, out["generations_observed"])
        self.assertEqual(out["final_snapshot_generation"], 188)
        self.assertGreaterEqual(out["target_relevant_row_count"], 3)
        self.assertIn("RUNTIME_BACKMSG_ENTRY", out["target_relevant_phases"])
        self.assertIn("APPSESSION_REQUEST_RERUN_ENTRY", out["target_relevant_phases"])
        # Global generation never became quiescent; settle still passed on target evidence.
        self.assertGreater(len(out["generations_observed"]), 5)

    def test_b_early_pause_row_survives_eviction(self) -> None:
        rt = _row("RUNTIME_BACKMSG_ENTRY", event_id="e-rt-early", ts=1.0)
        later = _row("APPSESSION_BACKMSG_ENTRY", event_id="e-app", ts=1.5)
        fetches = [
            _snap(89, critical=[rt]),
            _snap(93, critical=[later]),  # Runtime row evicted from bounded ledger
            _snap(95, critical=[later]),
            _snap(98, critical=[later]),
            _snap(102, critical=[later]),
            _snap(104, critical=[later]),
            _snap(107, critical=[later]),
        ]
        out = self._run(fetches, max_wait_s_after_first_evidence=5.0)
        self.assertTrue(out["ok"], out)
        eids = {oob_row_identity(r) for r in out["accumulated_rows"]}
        self.assertIn(("RUNTIME_BACKMSG_ENTRY", "e-rt-early"), eids)
        self.assertIn("e-rt-early", out["target_relevant_event_ids"])

    def test_c_late_scheduler_evidence_resets_timer(self) -> None:
        rt = _row("RUNTIME_BACKMSG_ENTRY", event_id="e-rt", ts=1.0)
        app = _row("APPSESSION_BACKMSG_ENTRY", event_id="e-app", ts=1.1)
        consumed = _row("SCRIPTREQUESTS_RERUN_CONSUMED", event_id="e-cons", ts=3.0)
        run_script = _row("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", event_id="e-run", ts=3.1)
        # First see early Pause evidence briefly, then late scheduler evidence resets timer.
        early = _snap(89, critical=[rt, app])
        late = _snap(110, critical=[consumed, run_script])
        fetches = [early, early, late, late, late, late, late, late]
        out = self._run(
            fetches,
            stable_polls_required=4,
            min_stable_s=0.3,
            max_wait_s_after_first_evidence=5.0,
            hold_last=True,
        )
        self.assertTrue(out["ok"], out)
        self.assertIn("SCRIPTREQUESTS_RERUN_CONSUMED", out["target_relevant_phases"])
        self.assertIn("SCRIPTRUNNER_RUN_SCRIPT_ENTRY", out["target_relevant_phases"])
        self.assertEqual(out["deepest_target_phase"], "SCRIPTRUNNER_RUN_SCRIPT_ENTRY")
        # Late evidence arrived after the first early polls and reset the stability window.
        self.assertGreaterEqual(int(out["target_last_changed_poll"] or 0), 3)
        self.assertGreater(int(out["target_last_changed_poll"] or 0), int(out["target_first_seen_poll"] or 0))

    def test_d_genuine_early_stop_without_safe_sessionstate(self) -> None:
        rt = _row("RUNTIME_BACKMSG_ENTRY", event_id="e-rt", ts=1.0)
        app = _row("APPSESSION_BACKMSG_ENTRY", event_id="e-app", ts=1.1)
        req = _row("APPSESSION_REQUEST_RERUN_ENTRY", event_id="e-req", ts=1.2)
        target = [rt, app, req]
        fetches = [
            _snap(89, critical=target),
            _snap(93, critical=target + [_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg", ts=9.0)]),
            _snap(95, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg2", ts=9.1)]),
            _snap(98, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg3", ts=9.2)]),
            _snap(102, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg4", ts=9.3)]),
            _snap(104, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg5", ts=9.4)]),
            _snap(188, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg6", ts=9.5)]),
        ]
        out = self._run(fetches, max_wait_s_after_first_evidence=5.0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["settle_reason"], "oob_pause_evidence_quiescent")
        self.assertEqual(out["deepest_target_phase"], "APPSESSION_REQUEST_RERUN_ENTRY")
        self.assertNotIn("SAFE_SESSIONSTATE_RECEIVE_ENTRY", out["target_relevant_phases"])

    def test_e_no_pause_evidence(self) -> None:
        fetches = [
            _snap(89, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg1", ts=1.0)]),
            _snap(93, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg2", ts=1.1)]),
            _snap(95, critical=[_unrelated_row("RUNTIME_BACKMSG_ENTRY", event_id="bg3", ts=1.2)]),
        ]
        out = self._run(
            fetches,
            max_wait_s_before_first_evidence=0.5,
            max_wait_s_after_first_evidence=0.5,
            hold_last=True,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["settle_reason"], "oob_pause_evidence_not_observed")

    def test_f_target_evidence_keeps_changing_until_timeout(self) -> None:
        def growing(i: int) -> dict:
            rows = [
                _row("RUNTIME_BACKMSG_ENTRY", event_id=f"e-rt-{j}", ts=1.0 + j * 0.01)
                for j in range(i + 1)
            ]
            return _snap(89 + i, critical=rows, publish_source=f"src-{i}")

        fetches = [growing(i) for i in range(20)]
        out = self._run(
            fetches,
            stable_polls_required=10,
            min_stable_s=2.0,
            max_wait_s_before_first_evidence=2.0,
            max_wait_s_after_first_evidence=0.5,
            hold_last=False,
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["settle_reason"], "oob_pause_evidence_settle_timeout")
        self.assertGreater(out["target_relevant_row_count"], 0)

    def test_g_deduplication_across_snapshots(self) -> None:
        rt = _row("RUNTIME_BACKMSG_ENTRY", event_id="e-rt-same", ts=1.0)
        fetches = [
            _snap(89, critical=[rt], module=[rt]),
            _snap(93, critical=[rt], module=[rt]),
            _snap(95, critical=[rt]),
            _snap(98, critical=[rt]),
            _snap(102, critical=[rt]),
            _snap(104, critical=[rt]),
        ]
        out = self._run(fetches, max_wait_s_after_first_evidence=5.0)
        self.assertTrue(out["ok"], out)
        matches = [r for r in out["accumulated_rows"] if r.get("event_id") == "e-rt-same"]
        self.assertEqual(len(matches), 1)

    def test_h_classifier_receives_accumulated_union(self) -> None:
        early = [
            _row("RUNTIME_BACKMSG_ENTRY", event_id="e-rt", ts=1.0),
            _row("APPSESSION_BACKMSG_ENTRY", event_id="e-app", ts=1.1),
            _row("APPSESSION_REQUEST_RERUN_ENTRY", event_id="e-req", ts=1.2),
        ]
        late = [
            _row("SAFE_SESSIONSTATE_RECEIVE_ENTRY", event_id="e-safe", ts=2.0),
            _row(
                "SERVER_RECEIVE_ENTRY",
                event_id="e-recv",
                ts=2.1,
            ),
            _row(
                "SERVER_STATE_APPLIED",
                event_id="e-applied",
                ts=2.2,
                pause_trigger_from_deserialized=True,
            ),
        ]
        fetches = [
            _snap(89, critical=early),
            _snap(110, critical=late),  # early phases evicted
            _snap(120, critical=late),
            _snap(130, critical=late),
            _snap(140, critical=late),
            _snap(150, critical=late),
            _snap(160, critical=late),
        ]
        out = self._run(fetches, max_wait_s_after_first_evidence=5.0)
        self.assertTrue(out["ok"], out)
        acc = out["accumulated_rows"]
        # Final snapshot alone would miss early Runtime/AppSession Pause rows.
        final_only = list((out["final_snapshot"] or {}).get("critical_ledger_rows") or [])
        final_phases = {r.get("phase") for r in final_only}
        self.assertNotIn("RUNTIME_BACKMSG_ENTRY", final_phases)
        chain = pause_observability_chain(acc)
        self.assertTrue(chain.get("runtime_backmsg_pause"))
        self.assertTrue(chain.get("backmsg_pause"))
        self.assertTrue(chain.get("safe_sessionstate_pause"))
        self.assertTrue(chain.get("server_applied_pause"))
        case, note, _ev = classify_s3_with_observability(
            module_rows=[],
            authoritative_rows=acc,
            pause_resolved=True,
            strict_backmsg={"ok": True, "activated_widget_ids": [PAUSE_WID]},
            wire_widget_id="$$ID-sibling",
            sibling_python_effect=True,
            register_widget_result=True,
            st_button_returned=True,
            binding_ok=True,
        )
        self.assertNotEqual(case, "BUTTON_DISPATCH_S3_R3O0_SERVER_OBSERVABILITY_ABORT")
        self.assertTrue(case or note)  # formal classifier ran without abort on missing early phases

    def test_i_session_isolation(self) -> None:
        other = _row(
            "RUNTIME_BACKMSG_ENTRY",
            event_id="e-other",
            ts=1.0,
            sid=OTHER_SID,
            pause_widget_id=PAUSE_WID,
        )
        mine = _row("RUNTIME_BACKMSG_ENTRY", event_id="e-mine", ts=1.1)
        fetches = [
            _snap(89, critical=[other, mine]),
            _snap(93, critical=[other]),
            _snap(95, critical=[other]),
            _snap(98, critical=[other]),
            _snap(102, critical=[other]),
            _snap(104, critical=[other]),
        ]
        out = self._run(fetches, max_wait_s_after_first_evidence=5.0)
        self.assertTrue(out["ok"], out)
        self.assertIn("e-mine", out["target_relevant_event_ids"])
        self.assertNotIn("e-other", out["target_relevant_event_ids"])
        for r in out["accumulated_rows"]:
            if is_target_pause_scheduler_row(
                r, streamlit_session_id=SID, pause_widget_id=PAUSE_WID
            ):
                self.assertEqual(str(r.get("streamlit_session_id") or "")[:36], SID[:36])

    def test_merge_never_deletes(self) -> None:
        acc: dict = {}
        snap1 = _snap(89, critical=[_row("RUNTIME_BACKMSG_ENTRY", event_id="keep", ts=1.0)])["snapshot"]
        snap2 = _snap(188, critical=[])["snapshot"]
        merge_oob_snapshot_into_accumulator(acc, snap1)
        merge_oob_snapshot_into_accumulator(acc, snap2)
        self.assertEqual(len(acc), 1)
        self.assertEqual(next(iter(acc.values())).get("event_id"), "keep")

    def test_gate_wires_pause_evidence_settle(self) -> None:
        import inspect

        from run_production_bridge_s3_server_registry_gate import main

        src = inspect.getsource(main)
        self.assertIn("wait_for_oob_pause_evidence_settled_after", src)
        self.assertIn("s3_oob_pause_evidence_settle_after_pause", src)
        self.assertIn("oob_pause_evidence_accumulator", src)
        self.assertIn("wait_for_oob_generation_after", src)
        # Historical helper retained for regression / import availability.
        self.assertIn("wait_for_oob_settled_after", src)


if __name__ == "__main__":
    unittest.main()
