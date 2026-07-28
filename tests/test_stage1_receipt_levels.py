"""Tests for Stage 1A receipt level classification (diagnostic harness)."""

from __future__ import annotations

import unittest

from live_draft_stage1_receipt_levels import (
    classify_receipt_levels,
    is_logical_value_receipt,
    refine_a5a_subclass,
)


class Stage1ReceiptLevelsTest(unittest.TestCase):
    def test_register_not_value_receipt(self) -> None:
        row = {"message_type": "solo:rvCountdownRegister", "has_set_component_value": False}
        self.assertFalse(is_logical_value_receipt(row))

    def test_frame_height_not_value_receipt(self) -> None:
        row = {"message_type": "streamlit:setFrameHeight", "is_streamlit_message": True}
        self.assertFalse(is_logical_value_receipt(row))

    def test_set_component_value_counts(self) -> None:
        tok = "ROOM|0|123.456"
        row = {"message_type": "streamlit:setComponentValue", "value_preview": tok}
        self.assertTrue(is_logical_value_receipt(row, expected_token=tok))

    def test_observer_duplication_does_not_inflate_logical_count(self) -> None:
        dup = {"message_type": "streamlit:setComponentValue", "value_preview": "T|0|1"}
        levels = classify_receipt_levels(
            expected_token="T|0|1",
            iframe_send_stages=["component_value_sent"],
            immediate_parent_messages=[dup, dict(dup)],
            coalesced_value="",
        )
        self.assertEqual(levels["logical_set_component_value_receipts_immediate"], 2)
        self.assertTrue(levels["LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_IMMEDIATE"])

    def test_misleading_legacy_deduped_counts_non_value_messages(self) -> None:
        msgs = [
            {"message_type": "solo:rvCountdownRegister"},
            {"message_type": "streamlit:setFrameHeight"},
        ]
        levels = classify_receipt_levels(
            expected_token="X|0|1",
            iframe_send_stages=["component_value_sent"],
            immediate_parent_messages=msgs,
        )
        self.assertEqual(levels["misleading_legacy_deduped_parent_count"], 2)
        self.assertEqual(levels["logical_set_component_value_receipts_immediate"], 0)
        self.assertFalse(levels["LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_IMMEDIATE"])

    def test_immediate_and_top_reported_separately(self) -> None:
        imm = [{"message_type": "streamlit:setComponentValue", "value_preview": "A|0|1"}]
        top: list = []
        levels = classify_receipt_levels(
            expected_token="A|0|1",
            iframe_send_stages=["component_value_sent"],
            immediate_parent_messages=imm,
            top_parent_messages=top,
        )
        self.assertTrue(levels["LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_IMMEDIATE"])
        self.assertFalse(levels["LEVEL_2_TOP_PARENT_MESSAGE_RECEIVED_TOP"])

    def test_a5a1_when_send_but_no_parent_scv(self) -> None:
        levels = classify_receipt_levels(
            expected_token="A|0|1",
            iframe_send_stages=["component_value_sent", "transport_before_postMessage"],
            immediate_parent_messages=[
                {"message_type": "solo:rvCountdownRegister"},
            ],
        )
        self.assertEqual(refine_a5a_subclass(levels), "A5a1")

    def test_unrelated_render_a5a6(self) -> None:
        levels = classify_receipt_levels(
            expected_token="",
            iframe_send_stages=[],
        )
        self.assertEqual(refine_a5a_subclass(levels, unrelated_render_after_send=True), "A5a6")


if __name__ == "__main__":
    unittest.main()
