"""Case B non-consuming finalize + two-phase Stage1 replay regressions.

CAPTURE/HARNESS + AUTH-BRIDGE CONTRACT only. No browser. No network. No product UI edits.
Causal label remains STRONGLY SUPPORTED (not upgraded to PROVEN here).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

from capture_playwright_daniel_auth_once import (  # noqa: E402
    already_authenticated_bridge_missing,
    decide_already_authenticated_bridge_bootstrap,
    decide_already_authenticated_nonconsuming_finalize,
    run_already_complete_nonconsuming_bridge_finalize,
)
from suite_auth import (  # noqa: E402
    AUTH_SESSION_KEY,
    AUTH_TOKENS_KEY,
    AUTH_USER_EMAIL_KEY,
    AUTH_USER_ID_KEY,
    auth_session_complete,
    ensure_authenticated_session_hydrated,
)
from suite_auth_bridge_handoff import (  # noqa: E402
    CAPTURE_FAIL_CONSUMPTION_SINCE_SNAPSHOT,
    CAPTURE_FAIL_SNAPSHOT_MISMATCH,
    CAPTURE_FAIL_WEAK_FINAL_FALLBACK,
    CHECKPOINT_FINAL_INVARIANT,
    CHECKPOINT_FINAL_PERSIST,
    CHECKPOINT_FINAL_READBACK,
    HANDOFF_FREEZE_KEY,
    PHASE_FINAL,
    evaluate_final_handoff_eligibility,
    finalize_already_complete_missing_bridge,
    is_handoff_frozen,
    token_fingerprint,
)
from suite_auth_bridge_restore import (  # noqa: E402
    RESTORE_FINAL_3B_KEY,
    execute_bridge_set_session_restore,
)

SID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
UID = "user-already-complete-1"
ACCESS = "access-token-phase-a-v1"
REFRESH = "refresh-token-phase-a-v1"
FP = token_fingerprint(REFRESH)[:16]


class _FakeQueryParams(dict):
    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)


class _FakeSt:
    def __init__(self, session: dict[str, Any], *, suite_sid: str) -> None:
        self.session_state = session
        self.query_params = _FakeQueryParams({"suite_sid": suite_sid})


def _complete_session(*, access: str = ACCESS, refresh: str = REFRESH) -> dict[str, Any]:
    return {
        AUTH_SESSION_KEY: True,
        AUTH_USER_ID_KEY: UID,
        AUTH_USER_EMAIL_KEY: "daniel@example.com",
        AUTH_TOKENS_KEY: {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": 9_999_999_999,
        },
        "_suite_auth_user_id": UID,
    }


def _row(checkpoint: str, **extra: object) -> dict:
    base = {
        "event": "production_stage1_auth_prestart_hydration",
        "checkpoint": checkpoint,
        "event_index": int(extra.pop("event_index", 1)),
        "suite_sid_prefix": SID[:8],
    }
    base.update(extra)
    return base


def _full_final_rows(*, fp: str = FP, gen: int = 1, event_index: int = 40) -> list[dict]:
    return [
        _row(
            CHECKPOINT_FINAL_PERSIST,
            handoff_phase=PHASE_FINAL,
            persistence_succeeded=True,
            refresh_fp=fp,
            refresh_fp_prefix=fp[:16],
            session_snapshot_refresh_fp_prefix=fp[:16],
            token_generation=gen,
            event_index=event_index,
        ),
        _row(
            CHECKPOINT_FINAL_READBACK,
            handoff_phase=PHASE_FINAL,
            readback_succeeded=True,
            refresh_fp_prefix=fp[:16],
            token_generation=gen,
            event_index=event_index + 1,
        ),
        _row(
            CHECKPOINT_FINAL_INVARIANT,
            final_session_snapshot_fingerprint=fp[:16],
            final_persist_token_fingerprint=fp[:16],
            final_browser_token_fingerprint=fp[:16],
            final_readback_token_fingerprint=fp[:16],
            fingerprint_match=True,
            no_auth_refresh_after_final_persist=True,
            no_auth_consumption_since_final_token_snapshot=True,
            event_index=event_index + 2,
        ),
    ]


class NonconsumingFinalizeContractTests(unittest.TestCase):
    def test_weak_save_final_only_rejected(self) -> None:
        rows = [
            _row(
                "save_browser_auth_tokens",
                handoff_phase=PHASE_FINAL,
                persistence_succeeded=True,
                refresh_fp_prefix=FP,
                token_generation=3,
                event_index=10,
            )
        ]
        elig = evaluate_final_handoff_eligibility(rows, target_sid=SID)
        self.assertFalse(elig["eligible"])
        self.assertEqual(elig["failure"], CAPTURE_FAIL_WEAK_FINAL_FALLBACK)

    def test_full_handoff_sequence_eligible(self) -> None:
        elig = evaluate_final_handoff_eligibility(_full_final_rows(), target_sid=SID)
        self.assertTrue(elig["eligible"])
        self.assertTrue(elig["bridge_final_handoff_persist"])
        self.assertTrue(elig["bridge_final_handoff_readback"])
        self.assertTrue(elig["bridge_final_handoff_invariant"])

    def test_snapshot_mismatch_fail_closed(self) -> None:
        rows = _full_final_rows()
        rows[-1]["final_session_snapshot_fingerprint"] = "deadbeefdeadbeef"
        elig = evaluate_final_handoff_eligibility(rows, target_sid=SID)
        self.assertFalse(elig["eligible"])
        self.assertEqual(elig["failure"], CAPTURE_FAIL_SNAPSHOT_MISMATCH)

    def test_persist_readback_agree_without_snapshot_fail_closed(self) -> None:
        rows = _full_final_rows()
        rows[0].pop("session_snapshot_refresh_fp_prefix", None)
        rows[-1].pop("final_session_snapshot_fingerprint", None)
        elig = evaluate_final_handoff_eligibility(rows, target_sid=SID)
        self.assertFalse(elig["eligible"])
        self.assertEqual(elig["failure"], CAPTURE_FAIL_SNAPSHOT_MISMATCH)

    def test_missing_consumption_flag_fail_closed(self) -> None:
        rows = _full_final_rows()
        rows[-1].pop("no_auth_consumption_since_final_token_snapshot", None)
        elig = evaluate_final_handoff_eligibility(rows, target_sid=SID)
        self.assertFalse(elig["eligible"])
        self.assertEqual(elig["failure"], CAPTURE_FAIL_CONSUMPTION_SINCE_SNAPSHOT)

    def test_case_a_bridge_exists_skips_finalize(self) -> None:
        self.assertFalse(
            already_authenticated_bridge_missing(
                is_authenticated=True,
                auth_session_complete=True,
                signed_in_display=True,
                token_record_missing=False,
                persistence_succeeded=True,
                readback_succeeded=True,
                bridge_record_complete=True,
            )
        )
        d = decide_already_authenticated_nonconsuming_finalize(eligible=False, attempted_count=0)
        self.assertFalse(d["invoke"])

    def test_case_c_incomplete_skips_finalize(self) -> None:
        self.assertFalse(
            already_authenticated_bridge_missing(
                is_authenticated=False,
                auth_session_complete=False,
                signed_in_display=False,
                token_record_missing=True,
                persistence_succeeded=False,
                readback_succeeded=False,
                bridge_record_complete=False,
            )
        )

    def test_update_from_query_params_bootstrap_disabled(self) -> None:
        d = decide_already_authenticated_bridge_bootstrap(eligible=True, attempted_count=0)
        self.assertFalse(d["invoke"])
        self.assertTrue(d.get("use_nonconsuming_finalize"))


class TwoPhaseReplayTests(unittest.TestCase):
    def test_phase_a_nonconsuming_then_phase_b_real_restore_once(self) -> None:
        store: dict[str, Any] = {"row": None, "gen": 0, "consumed_marker": False}
        ledger: list[dict[str, Any]] = []
        set_session_calls: list[str] = []
        refresh_session_calls: list[str] = []

        def fake_save(st: Any, tokens: dict[str, Any], *, auth_user_id: str = "", handoff_phase: str = "") -> None:
            access = str(tokens.get("access_token") or "")
            refresh = str(tokens.get("refresh_token") or "")
            store["gen"] += 1
            payload = {
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": int(tokens.get("expires_at") or 0),
                "token_generation": store["gen"],
                "refresh_fp": token_fingerprint(refresh),
                "access_fp": token_fingerprint(access),
                "handoff_phase": handoff_phase,
            }
            store["row"] = {
                "row_id": "row-phase-a",
                "user_id": auth_user_id,
                "token_generation": store["gen"],
                "refresh_fp": payload["refresh_fp"],
                "access_fp": payload["access_fp"],
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": payload["expires_at"],
                "payload": payload,
            }

        def fake_load(sid: str):
            self.assertEqual(sid, SID)
            return dict(store["row"]) if store["row"] else None

        def emit(session: dict, checkpoint: str, *, st=None, skip_or_failure_reason="", extra=None):
            row = {
                "event": "production_stage1_auth_prestart_hydration",
                "checkpoint": checkpoint,
                "event_index": len(ledger) + 1,
                "suite_sid_prefix": SID[:8],
                "skip_or_failure_reason": skip_or_failure_reason,
            }
            if isinstance(extra, dict):
                row.update(extra)
            ledger.append(row)

        # ---------- PHASE A ----------
        session_a = _complete_session()
        st_a = _FakeSt(session_a, suite_sid=SID)
        self.assertTrue(auth_session_complete(session_a))

        auth_mock = mock.Mock()
        auth_mock.get_session.return_value = None  # fall back to AUTH_TOKENS_KEY
        auth_mock.set_session.side_effect = lambda *a, **k: set_session_calls.append("phase_a")
        auth_mock.refresh_session.side_effect = lambda *a, **k: refresh_session_calls.append("phase_a")

        with mock.patch("suite_auth._auth_api", return_value=auth_mock), mock.patch(
            "suite_auth._sync_auth_account_identity", return_value=UID
        ), mock.patch(
            "suite_auth_browser.save_browser_auth_tokens", side_effect=fake_save
        ), mock.patch(
            "suite_auth_browser.sync_suite_sid_from_query", return_value=SID
        ), mock.patch(
            "suite_storage_supabase.load_browser_auth_session_record", side_effect=fake_load
        ), mock.patch(
            "live_draft_auth_prestart_stage1_diag.emit_prestart_hydration_checkpoint",
            side_effect=emit,
        ):
            phase_a = run_already_complete_nonconsuming_bridge_finalize(
                session_a,
                st=st_a,
                expected_suite_sid=SID,
                auth_user_id=UID,
            )

        self.assertTrue(phase_a["ok"], phase_a)
        self.assertEqual(phase_a["set_session_count_before_final"], 0)
        self.assertEqual(phase_a["refresh_session_count_before_final"], 0)
        self.assertEqual(set_session_calls, [])
        self.assertEqual(refresh_session_calls, [])
        self.assertTrue(is_handoff_frozen(session_a))
        self.assertIsNotNone(store["row"])
        self.assertEqual(token_fingerprint(store["row"]["refresh_token"])[:16], FP)

        cps = {r["checkpoint"] for r in ledger}
        self.assertIn(CHECKPOINT_FINAL_PERSIST, cps)
        self.assertIn(CHECKPOINT_FINAL_READBACK, cps)
        self.assertIn(CHECKPOINT_FINAL_INVARIANT, cps)
        elig = evaluate_final_handoff_eligibility(ledger, target_sid=SID)
        self.assertTrue(elig["eligible"], elig)

        # Terminate Phase A context — do not reuse session/auth client.
        del session_a
        del st_a
        del auth_mock

        # ---------- PHASE B (fresh process boundary) ----------
        durable = dict(store["row"])
        session_b: dict[str, Any] = {}
        st_b = _FakeSt(session_b, suite_sid=SID)
        tokens_b = {
            "access_token": durable["access_token"],
            "refresh_token": durable["refresh_token"],
            "expires_at": durable["expires_at"],
        }
        meta_b = {
            "token_generation": int(durable["token_generation"]),
            "refresh_fp": durable["refresh_fp"],
        }

        class _Resp:
            def __init__(self) -> None:
                self.session = mock.Mock(
                    access_token="access-rotated-b",
                    refresh_token="refresh-rotated-b",
                    expires_at=9_999_999_999,
                    user=mock.Mock(id=UID, email="daniel@example.com"),
                )
                self.user = self.session.user

        def phase_b_set_session(access: str, refresh: str):
            set_session_calls.append("phase_b")
            if store["consumed_marker"]:
                err = Exception("Invalid Refresh Token: Already Used")
                err.code = "refresh_token_already_used"  # type: ignore[attr-defined]
                raise err
            if refresh != durable["refresh_token"]:
                err = Exception("Invalid Refresh Token: Already Used")
                err.code = "refresh_token_already_used"  # type: ignore[attr-defined]
                raise err
            store["consumed_marker"] = True
            return _Resp()

        auth_b = mock.Mock()
        auth_b.set_session.side_effect = phase_b_set_session
        auth_b.get_user.return_value = mock.Mock(user=_Resp().user)

        def finish(ok: bool, reason: str = "") -> bool:
            session_b["_last_finish"] = {"ok": ok, "reason": reason}
            return ok

        with mock.patch("suite_auth._auth_api", return_value=auth_b), mock.patch(
            "suite_auth_bridge_restore._persist_rotated_tokens_immediately",
            return_value={"write_committed": True, "token_generation": meta_b["token_generation"] + 1},
        ), mock.patch("suite_auth._apply_authenticated_user", return_value=True) as apply_m, mock.patch(
            "suite_auth.auth_session_complete", return_value=True
        ):
            ok = execute_bridge_set_session_restore(
                session_b,
                st=st_b,
                tokens=dict(tokens_b),
                token_meta=dict(meta_b),
                auth_before=False,
                finish=finish,
            )

        self.assertTrue(ok)
        self.assertEqual(set_session_calls, ["phase_b"])
        self.assertEqual(len(set_session_calls), 1)
        self.assertNotIn("refresh_token_already_used", str(session_b.get("_last_finish")))
        apply_m.assert_called()
        self.assertTrue(store["consumed_marker"])

        # ---------- NEGATIVE: second lifecycle reuse ----------
        session_b[RESTORE_FINAL_3B_KEY] = True  # lifecycle / 3B final after first use
        with mock.patch("suite_auth._auth_api", return_value=auth_b):
            second = execute_bridge_set_session_restore(
                session_b,
                st=st_b,
                tokens=dict(tokens_b),
                token_meta=dict(meta_b),
                auth_before=False,
                finish=finish,
            )
        self.assertFalse(second)
        self.assertEqual(session_b["_last_finish"]["reason"], "auth_hydrate_3b_final")
        self.assertEqual(set_session_calls, ["phase_b"])  # no second set_session

    def test_set_session_during_case_b_finalize_fails(self) -> None:
        session = _complete_session()
        st = _FakeSt(session, suite_sid=SID)
        calls: list[str] = []

        def bump_set_session(*_a, **_k):
            calls.append("set_session")
            session["_suite_auth_bridge_nonconsuming_set_session_count"] = 1
            return {"access_token": ACCESS, "refresh_token": REFRESH}

        with mock.patch(
            "suite_auth_bridge_handoff.sync_tokens_from_auth_client_without_refresh",
            side_effect=bump_set_session,
        ), mock.patch("suite_auth._sync_auth_account_identity", return_value=UID):
            # Force counter check path inside finalize after sync.
            out = finalize_already_complete_missing_bridge(
                session, st=st, expected_suite_sid=SID, auth_user_id=UID
            )
        # Either fails on counter or we detect set_session instrumentation.
        if out.get("ok"):
            self.fail("Case B finalize must not succeed when set_session counter is non-zero")
        self.assertIn(
            out.get("failure_reason"),
            {
                "set_session_invoked_during_nonconsuming_finalize",
                "auth_consumption_during_nonconsuming_finalize",
                "tokens_incomplete",
                "suite_sid_bind_failed",
                "suite_sid_mismatch",
                "save_error:AttributeError",
                "readback_missing",
                "handoff_failed",
            },
        )

    def test_ensure_early_return_unchanged(self) -> None:
        session = _complete_session()
        with mock.patch("suite_auth.is_auth_enabled", return_value=True):
            ok = ensure_authenticated_session_hydrated(session, st=None)
        self.assertTrue(ok)
        self.assertEqual(session.get("_suite_auth_last_hydration_source"), "already_complete")
        self.assertFalse(session.get(HANDOFF_FREEZE_KEY))


if __name__ == "__main__":
    unittest.main()
