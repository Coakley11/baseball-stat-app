"""Tests for Baseball AMI analyst framing."""

from __future__ import annotations

import unittest

from baseball_ami_frame import (
    AMI_ANSWER_TEMPLATE,
    PAGE_ACCEPTANCE_QUESTIONS,
    attach_baseball_ami_frame,
    player_draft_status,
)


class TestBaseballAmiFrame(unittest.TestCase):
    def test_attach_frame_adds_template_and_questions(self) -> None:
        ctx: dict = {"page": "Draft Assistant Simulator"}
        attach_baseball_ami_frame(ctx, "Draft Assistant Simulator")
        self.assertEqual(len(ctx["ami_answer_template"]), len(AMI_ANSWER_TEMPLATE))
        self.assertIn("Who should I draft next?", ctx["ami_acceptance_questions"])
        self.assertIn("ami_quality_rule", ctx)

    def test_draft_assistant_acceptance_questions(self) -> None:
        qs = PAGE_ACCEPTANCE_QUESTIONS["Draft Assistant Simulator"]
        self.assertIn("How risky is this pick?", qs)
        self.assertIn("What changes if I prioritize power, speed, saves, or pitching?", qs)

    def test_player_draft_status_not_drafted(self) -> None:
        session: dict = {}
        status = player_draft_status(session, "Juan Soto")
        self.assertEqual(status["player"], "Juan Soto")
        self.assertFalse(status["is_drafted"])


if __name__ == "__main__":
    unittest.main()
