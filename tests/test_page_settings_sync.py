"""Page settings and account work across navigation, refresh and two devices, through the real app.

``streamlit_app.py`` runs under AppTest as a signed-in throwaway account against the fake
compare-and-set cloud of ``cloud_restore_harness``. Widgets are changed the way a browser changes
them (``set_value`` + rerun), so Streamlit's own lifecycle applies: a page's widget values are
dropped from the session when the user leaves it, and a value changed in the browser arrives
before the script runs. Slow by design. Scenario numbers refer to the persistence brief.
"""

from __future__ import annotations

import copy
import unittest

import draft_state
from tests.cloud_restore_harness import CloudRestoreHarness, Device

HIST, TREND, CAREER = "Historical Explorer", "Trend Value", "Career Totals"
OHTANI, JUDGE, SOTO = "Shohei Ohtani", "Aaron Judge", "Juan Soto"


def on(dev: Device, page: str) -> Device:
    dev.at.session_state["active_page"] = page
    dev.at.session_state["main_sidebar_page"] = page
    return dev


def cloud_block(store, key: str, page: str) -> dict:
    full = ((store.row(key) or {}).get("metrics") or {}).get("full_session") or {}
    return (full.get("page_filter_state") or {}).get(page) or {}


def cloud_full(store, key: str) -> dict:
    return ((store.row(key) or {}).get("metrics") or {}).get("full_session") or {}


def other_option(widget, current):
    return [o for o in widget.options if o != current][0]


class _Base(CloudRestoreHarness, unittest.TestCase):
    def setUp(self) -> None:
        self.start_cloud()

    def hist_settings(self, dev: Device) -> dict:
        s = dev.state()
        return {k: s.get(k) for k in ("hist_2B_min", "hist_HR_min", "historical_year_range_filter",
                                      "historical_sort_stat_filter")}

    def set_hist(self, dev: Device, **values) -> Device:
        for key, value in values.items():
            widget = dev.at.slider(key=key) if key == "historical_year_range_filter" else (
                dev.at.selectbox(key=key) if key == "historical_sort_stat_filter" else dev.at.number_input(key=key))
            self.store.who = dev.name
            widget.set_value(value).run()
        return dev

    def queue(self, dev: Device) -> list[str]:
        return [str(x) for x in (dev.state().get("draft_queue") or [])]

    def add_to_queue(self, dev: Device, player: str) -> Device:
        """What the Add-to-Queue button's on_click does to the session, then the rerun it causes."""
        before = dev.state()
        work = copy.deepcopy(before)
        draft_state.add_player_to_draft_queue(work, player)
        for key, value in work.items():
            try:
                same = key in before and bool(before[key] == value)
            except (TypeError, ValueError):  # DataFrames and the like: the queue never touches them
                same = True
            if not same:
                dev.at.session_state[key] = value
        return dev.run()


EXPECTED_HIST = {"hist_2B_min": 30, "hist_HR_min": 40, "historical_year_range_filter": (2006, 2012),
                 "historical_sort_stat_filter": "2B"}


class NavigationAndDevicesTests(_Base):
    def test_page_settings_survive_navigation_refresh_and_a_fresh_phone(self) -> None:  # 1-7
        dell = on(self.device("dell"), HIST).run()
        # The first edit lands on the rerun right after the account's first cloud sync (7).
        self.set_hist(dell, hist_2B_min=30, hist_HR_min=40,
                      historical_year_range_filter=(2006, 2012), historical_sort_stat_filter="2B")
        self.assertEqual(self.hist_settings(dell), EXPECTED_HIST)

        dell.go(TREND)                                                              # 1-2
        lag = dell.at.selectbox(key="trend_lag")
        new_lag = other_option(lag, lag.value)
        lag.set_value(new_lag).run()                                                # 3
        min_g = dell.at.number_input(key="trend_min_g")
        min_g.set_value(int(min_g.value) + 7).run()
        trend_expected = {k: dell.state().get(k) for k in ("trend_lag", "trend_min_g")}
        self.assertEqual(str(trend_expected["trend_lag"]), str(new_lag))

        dell.go(CAREER)                                                             # 4
        career_sort = dell.at.selectbox(key="career_sort_stat_filter")
        career_expected = other_option(career_sort, career_sort.value)
        career_sort.set_value(career_expected).run()

        dell.go(HIST)
        self.assertEqual(self.hist_settings(dell), EXPECTED_HIST)
        dell.go(TREND)
        self.assertEqual({k: dell.state().get(k) for k in trend_expected}, trend_expected)
        dell.go(CAREER)
        self.assertEqual(dell.state().get("career_sort_stat_filter"), career_expected)

        # The account holds all of it.
        block = cloud_block(self.store, self.cloud_key, HIST)
        self.assertEqual((block.get("hist_2B_min"), block.get("hist_HR_min")), (30, 40))
        self.assertEqual(list(block.get("historical_year_range_filter")), [2006, 2012])

        refreshed = on(self.device("dell-refresh"), HIST).run()                     # 5
        self.assertEqual(self.hist_settings(refreshed), EXPECTED_HIST)
        self.wipe_local_disk()
        phone = on(self.device("phone"), HIST).run()                                # 6
        self.assertEqual(self.hist_settings(phone), EXPECTED_HIST)
        phone.go(TREND)
        self.assertEqual({k: phone.state().get(k) for k in trend_expected}, trend_expected,
                         cloud_block(self.store, self.cloud_key, TREND))

    def test_late_sign_in_restores_settings_and_keeps_an_edit_made_before_it(self) -> None:  # 5, 7
        dell = on(self.device("dell"), HIST).run()
        self.set_hist(dell, hist_HR_min=40, historical_year_range_filter=(2006, 2012))
        self.wipe_local_disk()
        phone = on(self.device("phone", signed_in=False), HIST).run()               # auth not ready yet
        phone.sign_in()
        self.assertEqual(self.hist_settings(phone)["hist_HR_min"], 40)
        self.assertEqual(self.hist_settings(phone)["historical_year_range_filter"], (2006, 2012))


class CrossDeviceMergeTests(_Base):
    def test_stale_device_save_merges_instead_of_erasing_newer_work(self) -> None:  # 11, 17
        dell = on(self.device("dell"), HIST).run()
        for player in ("Aaron Judge", "Juan Soto", "Mookie Betts"):
            self.add_to_queue(dell, player)
        self.wipe_local_disk()
        phone = on(self.device("phone"), HIST).run()
        self.assertEqual(self.queue(phone), ["Aaron Judge", "Juan Soto", "Mookie Betts"])

        self.add_to_queue(phone, "Bobby Witt Jr.")                                  # phone: 4th player
        self.set_hist(phone, hist_2B_min=30)                                        # phone: a filter
        self.assertIn("Bobby Witt Jr.", cloud_full(self.store, self.cloud_key).get("draft_queue") or [])

        self.set_hist(dell, hist_HR_min=40)                                         # stale Dell edits
        full = cloud_full(self.store, self.cloud_key)
        self.assertEqual(full.get("draft_queue"),
                         ["Aaron Judge", "Juan Soto", "Mookie Betts", "Bobby Witt Jr."])
        block = cloud_block(self.store, self.cloud_key, HIST)
        self.assertEqual((block.get("hist_2B_min"), block.get("hist_HR_min")), (30, 40))
        self.assertNotIn("REJECTED", " ".join(self.store.log[-1:]))

        dell.go(TREND)                                                              # Dell receives
        self.assertIn("Bobby Witt Jr.", self.queue(dell))
        dell.go(HIST)
        self.assertEqual(self.hist_settings(dell)["hist_2B_min"], 30)
        self.assertEqual(self.hist_settings(dell)["hist_HR_min"], 40)

        phone.go(TREND)                                                             # phone receives
        phone.go(HIST)
        self.assertEqual(self.hist_settings(phone)["hist_HR_min"], 40)

    def test_same_setting_changed_on_both_devices_keeps_both_until_the_user_chooses(self) -> None:  # 18
        dell = on(self.device("dell"), HIST).run()
        self.wipe_local_disk()
        phone = on(self.device("phone"), HIST).run()
        self.set_hist(dell, hist_HR_min=40)
        self.set_hist(phone, hist_HR_min=30)                                        # stale, same field
        self.assertEqual(cloud_block(self.store, self.cloud_key, HIST).get("hist_HR_min"), 40)
        phone.run()
        self.assertEqual(phone.state().get("hist_HR_min"), 30)                      # phone keeps its side
        self.assertTrue(any("Another device changed" in str(w.value) for w in phone.at.warning))
        phone.at.button(key="ws_conflict_keep_local_btn").click().run()
        phone.run()
        self.assertEqual(cloud_block(self.store, self.cloud_key, HIST).get("hist_HR_min"), 30)
        dell.go(TREND)
        dell.go(HIST)
        self.assertEqual(dell.state().get("hist_HR_min"), 30)                       # explicit choice syncs

    def test_research_edits_on_either_device_never_touch_the_saved_board(self) -> None:  # 12, 7 (draft)
        dell = self.device("dell").run()
        dell.pick(OHTANI)
        self.assertIn("Saved 1 pick(s) to your account.", dell.save())
        self.wipe_local_disk()
        phone = self.device("phone").run()          # opens on the account's page (the Simulator)
        phone.go(HIST)
        self.set_hist(phone, hist_HR_min=40)
        dell.go(HIST)
        self.set_hist(dell, hist_2B_min=30)                                         # stale Dell
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI])
        self.assertEqual(self.store.snapshot_picks(self.cloud_key), 1)
        block = cloud_block(self.store, self.cloud_key, HIST)
        self.assertEqual((block.get("hist_2B_min"), block.get("hist_HR_min")), (30, 40))
        dell.go("Draft Room Simulator")
        self.assertEqual(dell.board(), [OHTANI])


class DraftRoomSyncTests(_Base):
    def test_a_phone_pick_reaches_an_open_dell_session_and_later_saves_still_work(self) -> None:  # 6, 3
        dell = self.device("dell").run()
        dell.pick(OHTANI)
        self.assertIn("Saved 1 pick(s) to your account.", dell.save())
        self.wipe_local_disk()
        phone = self.device("phone").run()
        self.assertEqual(phone.board(), [OHTANI])
        phone.pick(JUDGE)
        self.assertIn("Saved 2 pick(s) to your account.", phone.save())
        dell.go(TREND)                                   # the Dell never refreshed
        dell.go("Draft Room Simulator")
        self.assertEqual(dell.board(), [OHTANI, JUDGE])
        dell.pick(SOTO)
        self.assertIn("Saved 3 pick(s) to your account.", dell.save())
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI, JUDGE, SOTO])
        self.assertEqual(self.store.snapshot_picks(self.cloud_key), 3)
        phone.go(TREND)
        phone.go("Draft Room Simulator")
        self.assertEqual(phone.board(), [OHTANI, JUDGE, SOTO])

    def test_a_brand_new_accounts_first_pick_is_saved_without_pressing_save(self) -> None:  # 4
        # The account has never saved anything: its read answers "no row" and there is nothing on
        # this device. Its first picks used to live in the browser session only.
        dell = self.device("dell").run()
        dell.pick(OHTANI)
        dell.go(TREND)
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI])
        self.wipe_local_disk()
        phone = self.device("phone").run()
        self.assertEqual(phone.board(), [OHTANI])

    def test_a_pick_is_saved_without_pressing_save_and_survives_navigation(self) -> None:  # 4
        # An account that already has a saved board.
        dell = self.device("dell").run()
        dell.pick(OHTANI)
        dell.save()
        dell.pick(JUDGE)
        dell.go(TREND)
        self.assertEqual(self.store.board(self.cloud_key), [OHTANI, JUDGE])
        dell.go("Draft Room Simulator")
        self.assertEqual(dell.board(), [OHTANI, JUDGE])


class FailureAndIsolationTests(_Base):
    def test_failed_cloud_save_keeps_the_local_setting_and_saves_it_later(self) -> None:  # 10
        dell = on(self.device("dell"), HIST).run()
        self.store.fail = True
        self.set_hist(dell, hist_HR_min=40)
        self.assertEqual(dell.state().get("hist_HR_min"), 40)
        self.store.fail = False
        failure = dict(dell.at.session_state["_suite_cloud_read_failed"])
        failure["at"] = float(failure["at"]) - 61                      # the retry backoff (max 60 s) has passed
        dell.at.session_state["_suite_cloud_read_failed"] = failure
        self.set_hist(dell, hist_2B_min=30)
        dell.run()
        block = cloud_block(self.store, self.cloud_key, HIST)
        self.assertEqual((block.get("hist_2B_min"), block.get("hist_HR_min")), (30, 40))

    def test_another_account_sees_none_of_it(self) -> None:  # 16
        dell = on(self.device("dell"), HIST).run()
        self.set_hist(dell, hist_HR_min=40)
        other = f"{self.account}_other"
        stranger = on(self.device("stranger", account=other), HIST).run()
        self.assertNotEqual(stranger.state().get("hist_HR_min"), 40)
        self.assertEqual(cloud_block(self.store, f"baseball@{other}", HIST).get("hist_HR_min") or 0, 0)


if __name__ == "__main__":
    unittest.main()
