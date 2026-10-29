"""The draft queue across two devices, through the real app: order, removals and reorders.

Each queue action is applied the way its button's on_click applies it (the real ``draft_state``
function on the session, then the rerun it causes). The Dell stays open and stale while the phone
acts, exactly the case that used to bring removed players back or lose a reorder.
"""

from __future__ import annotations

import copy
import unittest

import draft_state
from tests.test_page_settings_sync import HIST, TREND, _Base, cloud_full, on

J, S, B, W, A = "Aaron Judge", "Juan Soto", "Mookie Betts", "Bobby Witt Jr.", "Yordan Alvarez"


class QueueAcrossDevices(_Base):
    def op(self, dev, fn, *args, **kwargs):
        """One queue button press: its on_click on the session, then the rerun."""
        before = dev.state()
        work = copy.deepcopy(before)
        fn(work, *args, **kwargs)
        for key, value in work.items():
            try:
                same = key in before and bool(before[key] == value)
            except (TypeError, ValueError):
                same = True
            if not same:
                dev.at.session_state[key] = value
        self.store.who = dev.name
        return dev.run()

    def cloud_queue(self) -> list[str]:
        return list(cloud_full(self.store, self.cloud_key).get("draft_queue") or [])

    def two_devices(self, players):
        dell = on(self.device("dell"), HIST).run()
        for player in players:
            self.add_to_queue(dell, player)
        self.wipe_local_disk()
        phone = on(self.device("phone"), HIST).run()
        self.assertEqual(self.queue(phone), list(players))
        return dell, phone

    def test_a_removal_and_a_move_to_top_on_the_phone_are_not_undone_by_the_dell(self) -> None:
        dell, phone = self.two_devices([J, S, B, W])
        self.op(phone, draft_state.remove_player_from_draft_queue, S)
        self.op(phone, draft_state.move_queue_item_to_top, self.queue(phone).index(W))
        self.assertEqual(self.cloud_queue(), [W, J, B])

        self.set_hist(dell, hist_HR_min=40)              # the stale Dell saves something unrelated
        self.assertEqual(self.cloud_queue(), [W, J, B])  # Soto stays removed, Witt stays on top
        dell.go(TREND)
        self.assertEqual(self.queue(dell), [W, J, B])
        self.add_to_queue(dell, A)                       # and the Dell keeps working from there
        phone.go(TREND)
        self.assertEqual(self.queue(phone), [W, J, B, A])
        self.assertEqual(self.cloud_queue(), [W, J, B, A])

    def test_a_reorder_on_the_dell_and_an_addition_on_the_phone_both_survive(self) -> None:
        dell, phone = self.two_devices([J, S, B])
        self.add_to_queue(phone, W)                                      # phone: [J, S, B, W]
        self.op(dell, draft_state.move_queue_item_up, self.queue(dell).index(B))   # stale Dell: B up
        dell.go(TREND)
        self.assertEqual(self.queue(dell), [J, B, S, W])
        self.assertEqual(self.cloud_queue(), [J, B, S, W])
        phone.go(TREND)
        self.assertEqual(self.queue(phone), [J, B, S, W])
        self.assertEqual(len(set(self.queue(phone))), 4)                 # no duplicates anywhere

    def test_both_devices_reordering_keeps_both_orders_until_the_user_chooses(self) -> None:
        dell, phone = self.two_devices([J, S, B])
        self.op(phone, draft_state.move_queue_item_to_top, 2)             # phone: [B, J, S]
        self.op(dell, draft_state.move_queue_item_down, 0)                # stale Dell: [S, J, B]
        dell.run()
        self.assertEqual(self.queue(dell), [S, J, B])                     # this device keeps its order
        self.assertEqual(self.cloud_queue(), [B, J, S])                   # the account keeps the phone's
        self.assertTrue(any("Draft queue" in str(w.value) for w in dell.at.warning))
        dell.at.button(key="ws_conflict_keep_local_btn").click().run()
        dell.run()
        self.assertEqual(self.cloud_queue(), [S, J, B])
        phone.go(TREND)
        self.assertEqual(self.queue(phone), [S, J, B])


if __name__ == "__main__":
    unittest.main()
