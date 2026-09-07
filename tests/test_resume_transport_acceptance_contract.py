"""Acceptance Resume success requires durable paused → in_progress with revision bump."""

from __future__ import annotations

import unittest


def resume_disk_accepted(
    *,
    resumed_disk: bool,
    resume_click: bool,
    resume_pre_status: str,
    rev_before: int,
    rev_after: int,
) -> bool:
    """Mirror local_tb_full_shared_draft_pass resume_disk gate."""
    return bool(
        resumed_disk
        and resume_click
        and str(resume_pre_status or "").lower() == "paused"
        and int(rev_after or 0) > int(rev_before or 0)
    )


class ResumeTransportAcceptanceContractTests(unittest.TestCase):
    def test_click_without_revision_bump_is_not_success(self) -> None:
        self.assertFalse(
            resume_disk_accepted(
                resumed_disk=True,  # status poll alone must not pass
                resume_click=True,
                resume_pre_status="paused",
                rev_before=12,
                rev_after=12,
            )
        )

    def test_true_transition_with_revision_bump_passes(self) -> None:
        self.assertTrue(
            resume_disk_accepted(
                resumed_disk=True,
                resume_click=True,
                resume_pre_status="paused",
                rev_before=12,
                rev_after=13,
            )
        )

    def test_never_paused_pre_status_fails(self) -> None:
        self.assertFalse(
            resume_disk_accepted(
                resumed_disk=True,
                resume_click=True,
                resume_pre_status="in_progress",
                rev_before=12,
                rev_after=13,
            )
        )


if __name__ == "__main__":
    unittest.main()
