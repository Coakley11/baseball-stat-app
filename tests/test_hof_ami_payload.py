"""HOF AMI payload enrichment and audit diagnostics."""

from __future__ import annotations

import unittest

import pandas as pd

from hall_of_fame_data import (
    HOF_AMI_CONTEXT_TYPE,
    audit_hof_ami_blob,
    build_hof_ami_payload,
    build_hof_case_packet,
)


class HofAmiPayloadTests(unittest.TestCase):
    def _sample_packet(self) -> dict:
        df = pd.DataFrame(
            [
                {
                    "fullName": "Mike Trout",
                    "playerID": "troutmi01",
                    "isHallOfFamer": False,
                    "displayPosition": "CF",
                    "HR": 310,
                    "H": 1500,
                    "RBI": 900,
                    "OPS": 0.999,
                },
                {
                    "fullName": "Babe Ruth",
                    "playerID": "ruthba01",
                    "isHallOfFamer": True,
                    "displayPosition": "RF",
                    "HR": 714,
                    "H": 2873,
                    "RBI": 2214,
                    "OPS": 1.164,
                },
                {
                    "fullName": "Hank Aaron",
                    "playerID": "aaronha01",
                    "isHallOfFamer": True,
                    "displayPosition": "RF",
                    "HR": 755,
                    "H": 3771,
                    "RBI": 2297,
                    "OPS": 0.930,
                },
            ]
        )
        return build_hof_case_packet(
            "Mike Trout",
            df,
            filters_summary={"year_range": [1901, 2024], "stat_minimums": {"HR": 300}},
            sort_stat="HR",
        )

    def test_build_hof_ami_payload_routing_and_audit(self) -> None:
        packet = self._sample_packet()
        insight = {
            "conclusion": "Borderline statistical case",
            "supporting_points": ["Strong OPS for cohort", "Below milestone thresholds"],
            "confidence": 0.72,
        }
        payload = build_hof_ami_payload(
            packet=packet,
            question="Hall of Fame case for Mike Trout",
            question_id="q-test-123",
            action_url="https://example.com/ami?suite_ai_question_id=q-test-123",
            context={"player": "Mike Trout", "routing_hint": "hof_case_analysis"},
            insight=insight,
            workspace_snapshot={"career_state": {"filters": {}}},
            resume_key="bb:hof_case:mike-trout",
        )
        self.assertEqual(payload["context_type"], HOF_AMI_CONTEXT_TYPE)
        self.assertEqual(payload["ami_source_app"], "baseball_analytics")
        self.assertEqual(payload["ami_source_page"], "career_totals")
        self.assertTrue(payload.get("workspace_snapshot_present"))
        self.assertEqual(payload.get("workspace_snapshot_ref"), "bb:hof_case:mike-trout")
        audit = payload.get("hof_ami_audit") or {}
        self.assertTrue(audit.get("has_target_player_stats"))
        self.assertTrue(audit.get("has_cohort_rows"))
        self.assertTrue(audit.get("has_comparable_players"))
        self.assertTrue(audit.get("has_action_url"))
        self.assertTrue(audit.get("has_workspace_snapshot"))
        self.assertTrue(audit.get("has_insight"))

    def test_audit_hof_ami_blob_counts(self) -> None:
        packet = self._sample_packet()
        blob = build_hof_ami_payload(
            packet=packet,
            question="Hall of Fame case",
            question_id="q-audit",
            action_url="https://example.com/ami?q=q-audit",
            context={"hof_case_packet": packet},
        )
        audit = audit_hof_ami_blob(blob)
        self.assertTrue(audit["valid"])
        self.assertIn("hof_case_packet", audit["blob_keys"] or blob.keys())
        counts = audit["counts"]
        self.assertGreaterEqual(counts["cohort_rows"], 3)
        self.assertGreaterEqual(counts["comparable_overall"], 1)
        self.assertGreater(counts["cohort_rank_stats"], 0)


if __name__ == "__main__":
    unittest.main()
