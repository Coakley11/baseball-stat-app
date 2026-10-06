"""Mobile M5 — generic wide-table column pinning (generalized from M4's Fantasy-only helper)."""

from __future__ import annotations

import unittest

import mobile_table_layout as T


class _PinSt:
    class column_config:  # noqa: N801 - mirrors streamlit attribute
        @staticmethod
        def Column(**kw):  # noqa: N802 - mirrors streamlit API
            return dict(kw)


class _NoPinSt:
    """Older Streamlit build without column_config.Column(pinned=...)."""

    class column_config:  # noqa: N801
        @staticmethod
        def Column(**_kw):  # noqa: N802
            raise TypeError("pinned is not a supported argument")


class LeadingIdentityColumnsTests(unittest.TestCase):
    def test_pins_only_the_contiguous_leading_run(self) -> None:
        cols = ["Year", "Player", "Bats", "Team", "HR", "RBI"]
        # "Bats" is not identity, so it stops the run before reaching "Team" —
        # Team is never pulled forward, which would reorder the desktop table.
        self.assertEqual(T.leading_identity_columns(cols, T.GENERAL_IDENTITY_COLUMNS), ["Year", "Player"])

    def test_identity_column_not_at_left_edge_is_never_pinned(self) -> None:
        cols = ["MLB Team", "Player"]
        self.assertEqual(T.leading_identity_columns(cols, ("Player",)), [])

    def test_empty_when_no_leading_column_is_identity(self) -> None:
        self.assertEqual(T.leading_identity_columns(["HR", "RBI"], T.GENERAL_IDENTITY_COLUMNS), [])

    def test_all_columns_identity_pins_everything(self) -> None:
        cols = ["Player", "Team"]
        self.assertEqual(T.leading_identity_columns(cols, T.GENERAL_IDENTITY_COLUMNS), cols)

    def test_caller_supplied_identity_set_overrides_general_list(self) -> None:
        # A caller can pass its own narrower/wider identity tuple; only columns in
        # THAT tuple are eligible, even if GENERAL_IDENTITY_COLUMNS would allow more.
        cols = ["Player", "Team", "HR"]
        self.assertEqual(T.leading_identity_columns(cols, ("Player",)), ["Player"])


class PinnedIdentityColumnConfigTests(unittest.TestCase):
    def test_builds_one_pinned_entry_per_leading_identity_column(self) -> None:
        cfg = T.pinned_identity_column_config(_PinSt, ["Year", "Player", "HR"], T.GENERAL_IDENTITY_COLUMNS)
        self.assertEqual(cfg, {"Year": {"pinned": True}, "Player": {"pinned": True}})

    def test_empty_identity_run_returns_empty_config(self) -> None:
        self.assertEqual(T.pinned_identity_column_config(_PinSt, ["HR", "RBI"], T.GENERAL_IDENTITY_COLUMNS), {})

    def test_degrades_to_empty_config_on_older_streamlit(self) -> None:
        """A build without column_config.Column(pinned=...) must not crash the page —
        it should just render the table unpinned."""
        cfg = T.pinned_identity_column_config(_NoPinSt, ["Player", "HR"], T.GENERAL_IDENTITY_COLUMNS)
        self.assertEqual(cfg, {})

    def test_works_against_installed_streamlit(self) -> None:
        import streamlit as st

        cfg = T.pinned_identity_column_config(st, ["Player", "Team", "HR"], ("Player", "Team"))
        self.assertEqual(set(cfg), {"Player", "Team"})


if __name__ == "__main__":
    unittest.main()
