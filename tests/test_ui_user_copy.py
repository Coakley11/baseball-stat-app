"""Plain-language user copy — no storage jargon in ordinary UI."""

from __future__ import annotations

import unittest

from ui_user_copy import (
    CREATION_STILL_WORKING,
    DRAFT_BOARD_SAVED_ACCOUNT,
    LINEUP_SAVED,
    SAVE_STATUS_HEADING,
    SIGN_IN_PROMPT,
    TRADE_ACCEPTED,
    TRADE_DECLINED,
    TRADE_PROPOSED,
    USER_COPY_BANNED_TERMS,
    all_user_copy_constants,
    contains_banned_user_term,
    format_save_status_banner,
    format_user_error,
)


class UserCopyBannedTermsTests(unittest.TestCase):
    def test_sign_in_prompt_has_no_cloud(self) -> None:
        self.assertNotIn("cloud", SIGN_IN_PROMPT.lower())

    def test_exported_constants_avoid_banned_terms(self) -> None:
        banned_hits: list[str] = []
        for name, text in all_user_copy_constants().items():
            if contains_banned_user_term(text):
                banned_hits.append(name)
        self.assertEqual(banned_hits, [])

    def test_save_status_heading_not_persistence(self) -> None:
        self.assertNotIn("persistence", SAVE_STATUS_HEADING.lower())

    def test_transaction_messages_plain(self) -> None:
        for msg in (TRADE_PROPOSED, TRADE_ACCEPTED, TRADE_DECLINED, LINEUP_SAVED):
            self.assertFalse(contains_banned_user_term(msg), msg)
        self.assertIn("rosters", TRADE_ACCEPTED.lower())

    def test_draft_board_success_has_no_supabase(self) -> None:
        line = DRAFT_BOARD_SAVED_ACCOUNT.format(count=3)
        self.assertNotIn("supabase", line.lower())
        self.assertNotIn("payload", line.lower())

    def test_creation_still_working_has_no_developer_mode(self) -> None:
        self.assertNotIn("developer mode", CREATION_STILL_WORKING.lower())
        self.assertNotIn(" ms", CREATION_STILL_WORKING.lower())


class UserErrorSanitizerTests(unittest.TestCase):
    def test_hides_traceback_from_ordinary_users(self) -> None:
        raw = 'RuntimeError: boom\nTraceback (most recent call last):\n  File "x.py", line 1'
        plain = format_user_error(raw, developer_mode=False)
        self.assertNotIn("traceback", plain.lower())
        self.assertNotIn("x.py", plain)

    def test_developer_mode_shows_raw_error(self) -> None:
        raw = "RuntimeError: boom"
        self.assertEqual(format_user_error(raw, developer_mode=True), raw)


class SaveStatusBannerTests(unittest.TestCase):
    def test_durable_status_plain(self) -> None:
        label, warning, ok = format_save_status_banner(
            {"durable_persistence": True, "cloud_saved_draft_count": 2}
        )
        self.assertTrue(ok)
        self.assertFalse(warning)
        self.assertNotIn("cloud", label.lower())
        self.assertIn("2", label)

    def test_temp_session_plain(self) -> None:
        label, warning, ok = format_save_status_banner({"cloud_enabled": False})
        self.assertFalse(ok)
        self.assertNotIn("persistence", label.lower())
        self.assertNotIn("payload", warning.lower())

    def test_strips_technical_warning_fallback(self) -> None:
        label, warning, ok = format_save_status_banner(
            {
                "cloud_enabled": True,
                "durable_persistence": False,
                "durability_warning": "Last payload was 4096 bytes. Supabase error.",
            }
        )
        self.assertFalse(ok)
        self.assertNotIn("supabase", warning.lower())
        self.assertNotIn("payload", warning.lower())
        self.assertNotIn("persistence", label.lower())


class DeveloperDiagnosticsStillTechnicalTests(unittest.TestCase):
    def test_banned_term_list_documents_technical_vocabulary(self) -> None:
        self.assertIn("supabase", USER_COPY_BANNED_TERMS)
        self.assertIn("persistence", USER_COPY_BANNED_TERMS)


if __name__ == "__main__":
    unittest.main()
