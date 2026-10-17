"""Hosted autosave: a failed cloud read must never lead to a destructive cloud write.

Uses a fake storage backend (no network, no credentials). Scenarios from
docs/HOSTED_AUTOSAVE_RELIABILITY_PROPOSAL.md:

* the store answers with data / with nothing / not at all / cloud disabled;
* failed read + older disk copy: nothing stale is applied, nothing is written to the cloud;
* failed read + empty disk + a user edit: the edit is not written over the cloud copy;
* recovery: the saved copy is restored (outage edits are not trusted), then saves resume;
* a transient failure after a good sync clears without re-applying;
* a confirmed-empty new workspace can save.
"""

from __future__ import annotations

import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

import suite_cloud_state as scs
import suite_user_persistence as sup

APP = "baseball"


class FakeStore:
    def __init__(self, blob=None, updated_at="2026-10-16T10:00:00+00:00"):
        self.blob = blob
        self.updated_at = updated_at
        self.fail = False
        self.malformed = False
        self.reads = 0
        self.writes: list[dict] = []

    def normalize_app_key(self, key):
        return key

    def load_current_state_meta_for_app(self, app_id):
        self.reads += 1
        if self.fail:
            raise ConnectionError("store unreachable")
        return {"updated_at": self.updated_at} if self.blob is not None else {}

    def load_current_state_for_app(self, app_id):
        if self.fail:
            raise ConnectionError("store unreachable")
        if self.malformed:
            return ["not", "a", "row"]
        if self.blob is None:
            return None
        return {"updated_at": self.updated_at, "metrics": {scs.FULL_SESSION_KEY: self.blob}}

    def save_current_state(self, app_key, *, page, summary, metrics, skip_metrics_merge_read=False):
        if self.fail:
            raise ConnectionError("store unreachable")
        self.writes.append(metrics[scs.FULL_SESSION_KEY])
        self.blob = metrics[scs.FULL_SESSION_KEY]
        self.updated_at = "2026-10-16T12:00:00+00:00"


class Harness:
    """Hosted install: cloud enabled, fake store, fake disk, session dict as st.session_state."""

    def __init__(self, store: FakeStore, disk_state=None, disk_ts="2026-10-15T09:00:00+00:00"):
        self.store = store
        self.disk_state = disk_state or {}
        self.disk_ts = disk_ts if disk_state else None
        self.session: dict = {}
        self.st = SimpleNamespace(session_state=self.session, warning=mock.Mock(), success=mock.Mock(), toast=mock.Mock())
        self.applied: list[dict] = []
        self.disk_writes: list[dict] = []
        self.stack = ExitStack()

    def __enter__(self):
        p = self.stack.enter_context
        p(mock.patch("suite_storage_config.cloud_storage_enabled", return_value=True))
        p(mock.patch.object(scs, "_import_storage", return_value=(self.store, "fake")))
        p(mock.patch.object(scs, "_streamlit_session", return_value=self.session))
        p(mock.patch.object(scs, "invalidate_cloud_full_session_cache", lambda app_id: None))
        p(mock.patch.object(sup, "_load_raw", side_effect=lambda app_id, workspace_id=None: (self.disk_state, None, self.disk_ts)))
        p(mock.patch.object(sup, "save_user_state", side_effect=self._write_disk))
        p(mock.patch("suite_egress_policy.cloud_autosave_allowed", return_value=(True, "")))
        return self

    def __exit__(self, *exc):
        self.stack.close()

    def _write_disk(self, app_id, state, **_kw):
        self.disk_writes.append(dict(state))
        self.disk_state, self.disk_ts = dict(state), sup._utc_now_iso()
        return True

    def sync(self):
        return sup.sync_workspace_protocol(self.st, APP, apply_state=lambda st, s: self.applied.append(dict(s)))

    def save(self, state, reason="fantasy_edit"):
        return sup.force_autosave(self.st, APP, build_state=lambda st: dict(state), reason=reason)

    def end_run(self):
        sup.clear_workspace_autosave_block(self.st, APP)


SAVED = {"active_page": "Fantasy Standings Tracker", "league": "the real league"}


class CloudReadStatusTests(unittest.TestCase):
    def test_statuses(self):
        for blob, fail, malformed, expected in [
            (SAVED, False, False, scs.CLOUD_READ_OK),
            (None, False, False, scs.CLOUD_READ_NOT_FOUND),
            ({}, False, False, scs.CLOUD_READ_NOT_FOUND),
            (SAVED, True, False, scs.CLOUD_READ_ERROR),
            (SAVED, False, True, scs.CLOUD_READ_ERROR),
        ]:
            store = FakeStore(blob)
            store.fail, store.malformed = fail, malformed
            with Harness(store) as h:
                read = scs.load_cloud_full_session_status(APP, force=True)
                self.assertEqual(read.status, expected, (blob, fail, malformed))
                self.assertEqual(scs.cloud_read_failure(h.session) is not None, expected == scs.CLOUD_READ_ERROR)
                # The legacy tuple API is unchanged: same (state, updated_at) as before; errors look empty.
                legacy = scs.load_cloud_full_session(APP, force=True)
                self.assertEqual(legacy, (read.state, read.updated_at))
                if expected == scs.CLOUD_READ_OK:
                    self.assertEqual(legacy, (SAVED, store.updated_at))
                if expected == scs.CLOUD_READ_ERROR:
                    self.assertEqual(legacy, ({}, None))

    def test_disabled(self):
        with mock.patch("suite_storage_config.cloud_storage_enabled", return_value=False):
            self.assertEqual(scs.load_cloud_full_session_status(APP).status, scs.CLOUD_READ_DISABLED)

    def test_writes_refused_until_reconciled(self):
        store = FakeStore(SAVED)
        with Harness(store) as h:
            store.fail = True
            scs.load_cloud_full_session_status(APP, force=True)
            store.fail = False
            self.assertFalse(scs.save_cloud_full_session(APP, {"x": 1}))
            self.assertEqual(store.writes, [])
            self.assertEqual(h.session[scs.CLOUD_WRITE_BLOCKED_KEY]["reason"], "cloud_read_failed")
            # Another caller's successful read does not unlock writes on its own.
            scs.load_cloud_full_session_status(APP, force=True)
            self.assertFalse(scs.save_cloud_full_session(APP, {"x": 1}))
            scs.mark_cloud_reconciled(h.session)
            self.assertTrue(scs.save_cloud_full_session(APP, {"x": 1}))
            self.assertEqual(store.writes, [{"x": 1}])


class HostedSyncTests(unittest.TestCase):
    def test_failed_read_with_older_disk_applies_nothing_and_writes_nothing(self):
        store = FakeStore(SAVED)
        store.fail = True
        with Harness(store, disk_state={"active_page": "Historical Explorer", "league": "stale copy"}) as h:
            self.assertFalse(h.sync())
            self.assertEqual(h.applied, [])  # the stale disk copy is not shown
            self.assertIsNotNone(scs.cloud_read_failure(h.session))
            h.save({"league": "stale copy + an edit"})
            self.assertEqual(store.writes, [])
            self.assertEqual(store.blob, SAVED)

    def test_failed_read_empty_disk_user_edit_never_overwrites_cloud(self):
        # The destructive case: new container, store unreachable, user saves a league.
        store = FakeStore(SAVED)
        store.fail = True
        with Harness(store) as h:
            h.sync()
            h.end_run()
            store.fail = False  # the store is back, but this session never loaded the saved data
            h.save({"league": "brand-new near-empty session"})  # may still save on this device's disk
            self.assertFalse(h.session.get("_suite_persist_last_save_cloud"))
            self.assertEqual(store.writes, [])
            self.assertEqual(store.blob, SAVED)

    def test_recovery_restores_saved_copy_then_saves_resume(self):
        store = FakeStore(SAVED)
        store.fail = True
        with Harness(store) as h:
            h.sync()
            h.end_run()
            h.session[sup._local_dirty_key(APP)] = True  # edits made during the outage
            store.fail = False
            h.session[scs.CLOUD_READ_FAILED_KEY]["at"] = time.time() - 120  # backoff elapsed
            h.sync()
            self.assertEqual(h.applied, [SAVED])  # the saved copy wins over outage edits
            self.assertIsNone(scs.cloud_read_failure(h.session))
            self.assertTrue(h.session[scs.CLOUD_RECONCILED_KEY])
            h.end_run()
            self.assertTrue(h.save({**SAVED, "league": "the real league + a new edit"}))
            self.assertEqual(store.writes[-1]["league"], "the real league + a new edit")

    def test_backoff_skips_reads(self):
        store = FakeStore(SAVED)
        store.fail = True
        with Harness(store) as h:
            h.sync()
            reads = store.reads
            h.sync()  # immediately again: inside the 5 s backoff
            self.assertEqual(store.reads, reads)
            self.assertIn("waiting to retry", h.session["_suite_persist_restore_skip_reason"])
        self.assertEqual(sup._cloud_read_retry_wait({"count": 1, "at": 100.0}, now=101.0), 4.0)
        self.assertEqual(sup._cloud_read_retry_wait({"count": 3, "at": 100.0}, now=100.0), 20.0)
        self.assertEqual(sup._cloud_read_retry_wait({"count": 9, "at": 100.0}, now=100.0), 60.0)

    def test_transient_failure_after_good_sync_clears_without_reapplying(self):
        store = FakeStore(SAVED)
        with Harness(store) as h:
            h.sync()
            self.assertEqual(len(h.applied), 1)
            h.end_run()
            store.fail = True
            scs.load_cloud_full_session_status(APP, force=True)  # e.g. a draft-room read fails
            h.save({**SAVED, "x": 1})
            self.assertEqual(store.writes, [])
            store.fail = False
            h.session[scs.CLOUD_READ_FAILED_KEY]["at"] = time.time() - 120
            h.sync()
            self.assertEqual(len(h.applied), 1)  # already synced: no re-apply
            self.assertIsNone(scs.cloud_read_failure(h.session))
            h.end_run()
            self.assertTrue(h.save({**SAVED, "x": 2}))

    def test_confirmed_empty_new_workspace_can_save(self):
        store = FakeStore(None)
        with Harness(store) as h:
            h.sync()
            self.assertTrue(h.session.get(scs.CLOUD_RECONCILED_KEY))
            self.assertTrue(h.save({"league": "first league"}))
            self.assertEqual(store.writes, [{"league": "first league"}])

    def test_user_is_told(self):
        store = FakeStore(SAVED)
        store.fail = True
        with Harness(store) as h:
            h.sync()
            sup.show_persistence_messages(h.st)
            text = " ".join(str(c.args[0]) for c in h.st.warning.call_args_list)
            self.assertIn("couldn't reach your saved data", text)

    def test_warm_skip_cannot_hide_a_failure(self):
        from pathlib import Path

        src = (Path(sup.__file__).resolve().parent / "baseball_persistent_state.py").read_text(encoding="utf-8")
        block = src[src.index("force = bool("):src.index("fp = warm_startup_fingerprint(ss)")]
        self.assertIn('ss.get("_suite_cloud_read_failed")', block)


if __name__ == "__main__":
    unittest.main()
