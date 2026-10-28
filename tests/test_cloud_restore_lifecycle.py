"""Save → refresh → second device → navigate → save again, through the real app (2026-10-28).

Each test drives ``streamlit_app.py`` under AppTest as a signed-in account against a fake cloud
that enforces the same compare-and-set as the Supabase write. Scenario numbers refer to the
mandatory list in the restore-repair brief. Slow by design (each app run takes seconds).
"""

from __future__ import annotations

import unittest

import draft_room_state as drs
from tests.cloud_restore_harness import CloudRestoreHarness, Device

OHTANI, JUDGE, SOTO = "Shohei Ohtani", "Aaron Judge", "Juan Soto"


class _Base(CloudRestoreHarness, unittest.TestCase):
    def setUp(self) -> None:
        self.start_cloud()

    def saved_one_pick(self, device_name: str = "desktop") -> Device:
        dev = self.device(device_name).run()
        dev.pick(OHTANI)
        self.assertIn("Saved 1 pick(s) to your account.", dev.save())
        return dev


class SaveRefreshAndSecondDeviceTests(_Base):
    def test_save_is_in_the_cloud_with_a_recovery_snapshot_and_restores_on_refresh_and_phone(self) -> None:  # 1-5
        self.saved_one_pick()
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI])                       # 2
        self.assertEqual(self.store.snapshot_picks(self.cloud_key), 1)                      # 3
        refreshed = self.device("desktop-refresh").run()                                    # 4 (local copy present)
        self.assertEqual(refreshed.board(), [OHTANI])
        self.assertEqual(refreshed.visible_pick_text(), "1 pick(s) logged")
        self.wipe_local_disk()
        phone = self.device("phone").run()                                                  # 5 (nothing local)
        self.assertEqual(phone.board(), [OHTANI])
        self.assertEqual(phone.visible_pick_text(), "1 pick(s) logged")
        self.assertEqual(phone.state().get("room_your_team"), refreshed.state().get("room_your_team"))

    def test_sign_in_finishing_after_the_first_render_still_restores_the_board(self) -> None:  # 4-5 (the root cause)
        self.saved_one_pick()
        for label, wipe in (("desktop", False), ("phone", True)):
            if wipe:
                self.wipe_local_disk()
            dev = self.device(f"late-{label}", signed_in=False).run()        # first run: auth not ready
            self.assertEqual(dev.board(), [])
            dev.sign_in()                                                    # sign-in completes on a later run
            self.assertEqual(dev.board(), [OHTANI], label)
            self.assertEqual(dev.visible_pick_text(), "1 pick(s) logged", label)
            self.assertFalse(drs.is_draft_room_locally_dirty(dev.state()), label)

    def test_navigation_keeps_the_pick_and_a_later_save_works(self) -> None:  # 6-7
        dev = self.saved_one_pick()
        dev.go("Trend Value")
        dev.go("Draft Room Simulator")
        self.assertEqual(dev.board(), [OHTANI])
        dev.pick(JUDGE)
        self.assertIn("Saved 2 pick(s) to your account.", dev.save())
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI, JUDGE])


class ResearchIdentityTests(_Base):
    def test_research_pages_use_the_simulator_team_and_its_drafted_players(self) -> None:  # 8-9
        self.saved_one_pick()
        self.wipe_local_disk()
        dev = self.device("phone", signed_in=False, override=True).run()
        dev.sign_in()
        dev.go("Trend Value")
        import active_team_context as atc
        import fantasy_context_source as fcs

        state = dev.state()
        team = state.get("room_your_team")
        self.assertTrue(team and not str(team).startswith("Team "))
        banner = fcs.fantasy_context_source_badge_text(state)
        self.assertIn(f"Team: **{team}**", banner)
        self.assertNotIn("temporary / unsaved", banner)
        ctx = atc.resolve_active_team_context(state)
        self.assertEqual(ctx.active_team, team)
        self.assertEqual(ctx.drafted_names, [OHTANI])  # the exclusion list reflects the restored board

    def test_banner_wording_tracks_what_is_actually_verified(self) -> None:  # status wording
        import fantasy_context_source as fcs

        dev = self.device("desktop", override=True).run()
        self.assertIn("no picks yet", fcs.fantasy_context_source_badge_text(dev.state()))
        dev.pick(OHTANI)
        self.assertIn("not yet confirmed saved", fcs.fantasy_context_source_badge_text(dev.state()))
        dev.save()
        self.assertIn("saved to your account", fcs.fantasy_context_source_badge_text(dev.state()))
        dev.pick(JUDGE)
        self.assertIn("changes not yet saved", fcs.fantasy_context_source_badge_text(dev.state()))


class StaleWriterAndLocalEditsTests(_Base):
    def _stale_tab(self) -> tuple[Device, Device]:
        a = self.saved_one_pick("A")
        b = self.device("B").run()
        return a, b

    def test_a_stale_writer_is_refused_and_keeps_its_own_picks_until_the_user_chooses(self) -> None:  # 10-11
        a, b = self._stale_tab()
        b.pick(JUDGE)
        b.save()
        a.at.session_state["_suite_workspace_synced::baseball"] = True      # A is a stale tab: it does not resync
        a.pick(SOTO)
        messages = a.save()
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI, JUDGE])   # the newer cloud board is untouched
        self.assertEqual(a.board(), [OHTANI, SOTO])                           # A's unsaved pick is not discarded
        self.assertTrue(any("changed from another device or tab" in m for m in messages), messages)
        self.assertFalse(any("Try again in a moment" in m for m in messages), messages)
        a.click("Save Draft Board Now")                                       # a retry cannot succeed silently either
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI, JUDGE])
        self.assertTrue(a.button("Load the saved board").disabled)            # choices need an acknowledgement
        self.assertTrue(a.button("Save this page's board instead").disabled)

    def test_choosing_the_saved_board_replaces_this_pages_picks_and_stays(self) -> None:
        a, b = self._stale_tab()
        b.pick(JUDGE)
        b.save()
        a.at.session_state["_suite_workspace_synced::baseball"] = True
        a.pick(SOTO)
        a.save()
        [c for c in a.at.checkbox if c.label.startswith("I understand this page's picks")][0].check().run()
        a.click("Load the saved board")
        self.assertEqual(a.board(), [OHTANI, JUDGE])
        a.run()
        self.assertEqual(a.board(), [OHTANI, JUDGE])                          # the next rerun does not wipe it
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI, JUDGE])

    def test_choosing_this_pages_board_replaces_the_saved_one(self) -> None:
        a, b = self._stale_tab()
        b.pick(JUDGE)
        b.save()
        a.at.session_state["_suite_workspace_synced::baseball"] = True
        a.pick(SOTO)
        a.save()
        [c for c in a.at.checkbox if c.label.startswith("I understand the saved board")][0].check().run()
        a.click("Save this page's board instead")
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI, SOTO])

    def test_a_revision_that_moved_without_a_board_change_is_rebased_not_refused(self) -> None:  # 7 / repeat save
        a, b = self._stale_tab()
        b.go("Trend Value")                                                   # B writes; the board is unchanged
        a.at.session_state["_suite_workspace_synced::baseball"] = True
        a.pick(JUDGE)
        self.assertIn("Saved 2 pick(s) to your account.", a.save())
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI, JUDGE])

    def test_a_signed_out_pick_never_enters_the_account_and_never_blocks_its_saved_board(self) -> None:  # 11, 16
        self.saved_one_pick()
        self.wipe_local_disk()
        dev = self.device("phone", signed_in=False).run()
        dev.pick(JUDGE)                                                       # a guest's board is private to the guest
        dev.sign_in()
        dev.run()                                                             # the next rerun that login always triggers
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI])          # the guest pick was not written to the account
        self.assertEqual(dev.board(), [OHTANI])                               # and the account's board restored normally

    def test_an_unsaved_edit_on_a_signed_in_device_survives_a_later_restore_attempt(self) -> None:  # 11
        dev = self.saved_one_pick()
        dev.pick(JUDGE)                                                       # unsaved
        dev.at.session_state["_suite_workspace_synced::baseball"] = False     # force a fresh workspace sync
        dev.run()
        self.assertEqual(dev.board(), [OHTANI, JUDGE])


class UndoResetAndFailureTests(_Base):
    def test_an_intentional_undo_is_never_reversed_by_restore(self) -> None:  # 12
        dev = self.saved_one_pick()
        dev.pick(JUDGE)
        dev.save()
        dev.click("Undo Last Pick")
        self.assertEqual(dev.board(), [OHTANI])
        dev.save()
        dev.run()
        self.assertEqual(dev.board(), [OHTANI])
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI])
        self.assertEqual(self.device("refresh").run().board(), [OHTANI])

    def test_an_explicit_reset_still_empties_the_board_everywhere(self) -> None:  # 13
        dev = self.saved_one_pick()
        dev.click("Reset Draft Room Simulator")
        self.assertEqual(dev.board(), [])
        dev.run()
        self.assertEqual(dev.board(), [])
        self.assertEqual(self.device("refresh").run().board(), [])

    def test_a_failed_cloud_read_cannot_erase_saved_data(self) -> None:  # 17
        self.saved_one_pick()
        writes_before = len(self.store.log)
        self.store.fail = True
        outage = self.device("outage").run()
        self.assertEqual(outage.board(), [])
        outage.pick(JUDGE)
        outage.save()
        self.store.fail = False
        self.assertEqual(len(self.store.log), writes_before)                  # nothing was written during the outage
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI])
        self.wipe_local_disk()
        self.assertEqual(self.device("after-outage").run().board(), [OHTANI])


class LibraryAndIsolationTests(_Base):
    def test_a_named_draft_and_the_working_board_both_survive_a_new_device(self) -> None:  # 15
        dev = self.saved_one_pick()
        dev.click("Save as Mock Draft")
        before = len(dev.state().get("draft_archive_teams") or [])
        self.assertEqual(before, 1)
        self.wipe_local_disk()
        phone = self.device("phone").run()
        self.assertEqual(len(phone.state().get("draft_archive_teams") or []), 1)
        self.assertEqual(phone.board(), [OHTANI])

    def test_two_accounts_stay_isolated(self) -> None:  # 16
        self.saved_one_pick()
        other_account = "qa_restore_other"
        other = self.device("other", account=other_account).run()
        self.assertEqual(other.board(), [])                                   # sees nothing of the first account
        other.pick(JUDGE)
        other.save()
        self.acting_as(None)
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI])          # and wrote nothing into it
        self.assertEqual(self.store.board(f"baseball@{other_account}"), [JUDGE])


if __name__ == "__main__":
    unittest.main()
