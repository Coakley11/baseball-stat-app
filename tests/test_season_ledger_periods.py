"""Scoring periods: explicit calendar, derived status, lineup snapshots and their lock rules."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import pandas as pd

from fantasy_season_ledger import (
    PERIOD_ACTIVE,
    PERIOD_FINALIZED,
    PERIOD_LOCKED,
    PERIOD_UPCOMING,
    build_lineup_snapshot,
    configure_season_calendar,
    current_period_number,
    get_period,
    get_period_lineup,
    get_season_ledger,
    list_periods,
    period_date_label,
    period_status,
    save_period_lineup,
)


def _at(day: str, hour: int = 16) -> datetime:
    """A UTC moment on the given date (16:00 UTC = noon Eastern)."""
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=timezone.utc)


def _context() -> dict:
    ctx = {"league_context_id": "archive:qa", "context_type": "real_league", "league_rosters": {}}
    ok, err = configure_season_calendar(ctx, first_day="2026-04-06", period_count=3)
    assert ok, err
    return ctx


ROSTER = pd.DataFrame(
    [
        {"Player": "Cal Raleigh", "Primary Position": "C", "MLBAM ID": 663728.0},
        {"Player": "Aaron Judge", "Primary Position": "OF", "MLBAM ID": 592450},
        {"Player": "Jo Adell", "Primary Position": "OF"},
    ]
)


class CalendarTests(unittest.TestCase):
    def test_periods_have_explicit_inclusive_boundaries(self):
        ctx = _context()
        periods = list_periods(ctx)
        self.assertEqual([(p["label"], p["start"], p["end"]) for p in periods], [
            ("Week 1", "2026-04-06", "2026-04-12"),
            ("Week 2", "2026-04-13", "2026-04-19"),
            ("Week 3", "2026-04-20", "2026-04-26"),
        ])
        self.assertEqual(period_date_label(periods[0]), "Apr 6 – Apr 12, 2026")
        self.assertEqual(get_season_ledger(ctx)["version"], 1)

    def test_status_comes_from_the_boundaries_not_from_today_alone(self):
        p1 = get_period(_context(), 1)
        self.assertEqual(period_status(p1, now=_at("2026-04-05")), PERIOD_UPCOMING)
        self.assertEqual(period_status(p1, now=_at("2026-04-06")), PERIOD_ACTIVE)
        self.assertEqual(period_status(p1, now=_at("2026-04-12")), PERIOD_ACTIVE)
        self.assertEqual(period_status(p1, now=_at("2026-04-13")), PERIOD_LOCKED)
        # 02:00 UTC on Apr 13 is still Apr 12 in New York: the period is still running.
        self.assertEqual(period_status(p1, now=_at("2026-04-13", hour=2)), PERIOD_ACTIVE)
        p1["finalized_at"] = "2026-04-14T00:00:00+00:00"
        self.assertEqual(period_status(p1, now=_at("2026-04-05")), PERIOD_FINALIZED)

    def test_calendar_is_fixed_once_a_period_is_finalized(self):
        ctx = _context()
        get_season_ledger(ctx)["periods"]["P1"]["finalized_at"] = "2026-04-14T00:00:00+00:00"
        ok, err = configure_season_calendar(ctx, first_day="2026-05-01", period_count=2)
        self.assertFalse(ok)
        self.assertIn("can no longer change", err)
        self.assertEqual(get_period(ctx, 1)["start"], "2026-04-06")

    def test_current_period_is_the_first_unfinalized(self):
        ctx = _context()
        self.assertEqual(current_period_number(ctx), 1)
        get_season_ledger(ctx)["periods"]["P1"]["finalized_at"] = "x"
        self.assertEqual(current_period_number(ctx), 2)

    def test_legacy_league_has_no_ledger(self):
        self.assertIsNone(get_season_ledger({"workflow": {"weekly_lineups": {}}}))
        self.assertEqual(list_periods({}), [])

    def test_invalid_calendar_is_refused(self):
        ctx = {}
        self.assertFalse(configure_season_calendar(ctx, first_day="", period_count=3)[0])
        self.assertFalse(configure_season_calendar(ctx, first_day="2026-04-06", period_count=0)[0])


class SnapshotTests(unittest.TestCase):
    def test_snapshot_separates_starters_bench_and_empty_slots(self):
        snap = build_lineup_snapshot(
            team="Team A",
            slots=["C", "OF", "OF", "UTIL"],
            slot_assignments={"C": "Cal Raleigh", "OF": "Aaron Judge", "OF_2": "", "UTIL": ""},
            roster_df=ROSTER,
            owner_of={"aaron judge": "Team A"},
        )
        self.assertEqual([(s["slot"], s["player_name"]) for s in snap["starters"]], [("C", "Cal Raleigh"), ("OF", "Aaron Judge")])
        self.assertEqual([b["player_name"] for b in snap["bench"]], ["Jo Adell"])
        self.assertEqual(snap["empty_slots"], ["OF", "UTIL"])
        self.assertEqual(snap["starters"][0]["player_id"], "663728")
        self.assertEqual(snap["starters"][1]["owner_at_snapshot"], "Team A")
        self.assertIn("OF", snap["starters"][1]["eligible_positions"])


class LineupLockRuleTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _context()
        self.snap = build_lineup_snapshot(team="Team A", slots=["C"], slot_assignments={"C": "Cal Raleigh"}, roster_df=ROSTER)
        self.owner = {"user_id": "local:qa", "acting_as": "owner"}

    def test_owner_sets_lineup_before_the_period_starts(self):
        ok, err = save_period_lineup(self.ctx, number=1, team="Team A", snapshot=self.snap, actor=self.owner, now=_at("2026-04-05"))
        self.assertTrue(ok, err)
        saved = get_period_lineup(self.ctx, 1, "Team A")
        self.assertFalse(saved["set_after_lock"])
        self.assertEqual(saved["saved_by"]["acting_as"], "owner")

    def test_owner_cannot_change_a_saved_or_started_lineup(self):
        save_period_lineup(self.ctx, number=1, team="Team A", snapshot=self.snap, actor=self.owner, now=_at("2026-04-05"))
        ok, err = save_period_lineup(self.ctx, number=1, team="Team A", snapshot=self.snap, actor=self.owner, now=_at("2026-04-05"))
        self.assertFalse(ok)
        self.assertIn("already locked", err)
        ok, err = save_period_lineup(self.ctx, number=2, team="Team A", snapshot=self.snap, actor=self.owner, now=_at("2026-04-14"))
        self.assertFalse(ok)
        self.assertIn("has started", err)

    def test_commissioner_can_set_a_late_lineup_and_it_is_marked(self):
        actor = {"user_id": "local:qa", "acting_as": "commissioner_proxy"}
        ok, err = save_period_lineup(self.ctx, number=1, team="Team B", snapshot=self.snap, actor=actor,
                                     is_commissioner=True, now=_at("2026-04-20"))
        self.assertTrue(ok, err)
        saved = get_period_lineup(self.ctx, 1, "Team B")
        self.assertTrue(saved["set_after_lock"])
        audit = get_period(self.ctx, 1)["audit"][-1]
        self.assertEqual((audit["action"], audit["team"], audit["actor"]["acting_as"], audit["after_lock"]),
                         ("lineup_set", "Team B", "commissioner_proxy", True))

    def test_finalized_period_never_changes(self):
        save_period_lineup(self.ctx, number=1, team="Team A", snapshot=self.snap, actor=self.owner, now=_at("2026-04-05"))
        get_season_ledger(self.ctx)["periods"]["P1"]["finalized_at"] = "2026-04-14T00:00:00+00:00"
        other = build_lineup_snapshot(team="Team A", slots=["C"], slot_assignments={"C": "Jo Adell"}, roster_df=ROSTER)
        ok, err = save_period_lineup(self.ctx, number=1, team="Team A", snapshot=other, actor=self.owner,
                                     is_commissioner=True, now=_at("2026-04-20"))
        self.assertFalse(ok)
        self.assertIn("finalized", err)
        self.assertEqual(get_period_lineup(self.ctx, 1, "Team A")["starters"][0]["player_name"], "Cal Raleigh")


if __name__ == "__main__":
    unittest.main()


class SaveWeeklyLineupIntegrationTests(unittest.TestCase):
    """The existing Save Lineup path writes the period snapshot when the league has a calendar."""

    def _league(self, *, calendar_start=None, commissioner=True):
        from datetime import timedelta
        from unittest import mock

        from fantasy_league_context import activate_archive_league_context, get_active_league_context, save_imported_league_context
        from fantasy_league_context import upsert_league_context
        from fantasy_league_lineup_format import apply_lineup_format_to_context
        from fantasy_season_ledger import league_today

        self.patches = [mock.patch("fantasy_league_team_ownership._resolve_user_id", return_value="local:qa"),
                        mock.patch("suite_user.get_account_user_id", return_value="local:qa")]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        session: dict = {}
        board = pd.DataFrame([{"Pick": 1, "Round": 1, "Team": "Team A", "Player": "Cal Raleigh"},
                              {"Pick": 2, "Round": 1, "Team": "Team B", "Player": "Juan Soto"},
                              {"Pick": 3, "Round": 2, "Team": "Team A", "Player": "Aaron Judge"},
                              {"Pick": 4, "Round": 2, "Team": "Team B", "Player": "Jo Adell"}])
        entry, _ = save_imported_league_context(session, board, my_team_name="Team A", draft_name="QA", league_name="QA",
                                                save_only=True, assign_team=True)
        activate_archive_league_context(session, entry["draft_id"])
        ctx = get_active_league_context(session)
        ctx = apply_lineup_format_to_context(ctx, lineup_slots=["C", "OF"], roster_capacity=2, configured_by="qa",
                                             configuration_source="uploaded")
        if not commissioner:
            ctx["metadata"] = {**(ctx.get("metadata") or {}), "commissioner_user_id": "user:someone-else"}
        if calendar_start is not None:
            configure_season_calendar(ctx, first_day=league_today() + timedelta(days=calendar_start), period_count=2)
        upsert_league_context(session, ctx)
        return session

    def _save(self, session):
        from fantasy_weekly_lineup import save_weekly_lineup

        roster = pd.DataFrame([{"Player": "Cal Raleigh", "Team": "Team A", "Primary Position": "C", "H": 10, "AB": 40, "HR": 2, "R": 5, "RBI": 6, "SB": 0},
                               {"Player": "Aaron Judge", "Team": "Team A", "Primary Position": "OF", "H": 12, "AB": 40, "HR": 4, "R": 7, "RBI": 9, "SB": 1}])
        return save_weekly_lineup(session, week=1, slots=["C", "OF"], assignments={"C": "Cal Raleigh", "OF": "Aaron Judge"},
                                  my_team="Team A", roster_df=roster)

    def test_save_before_the_period_records_the_snapshot(self):
        from fantasy_league_context import get_active_league_context

        session = self._league(calendar_start=3)
        result = self._save(session)
        self.assertTrue(result["ok"], result)
        snap = get_period_lineup(get_active_league_context(session), 1, "Team A")
        self.assertEqual([s["player_name"] for s in snap["starters"]], ["Cal Raleigh", "Aaron Judge"])
        self.assertEqual(snap["starters"][1]["owner_at_snapshot"], "Team A")
        self.assertFalse(snap["set_after_lock"])

    def test_started_period_refuses_a_non_commissioner_owner(self):
        session = self._league(calendar_start=-3, commissioner=False)
        result = self._save(session)
        self.assertFalse(result["ok"])
        self.assertIn("has started", " ".join(result["errors"]))

    def test_league_without_calendar_saves_as_before(self):
        from fantasy_league_context import get_active_league_context

        session = self._league(calendar_start=None)
        result = self._save(session)
        self.assertTrue(result["ok"], result)
        self.assertIsNone(get_season_ledger(get_active_league_context(session)))
        self.assertNotIn("season_ledger_period", result["lineup"])


class LegacyWeeklyRecordIdentityTests(unittest.TestCase):
    def test_each_team_gets_its_own_weekly_record(self):
        from unittest import mock

        import fantasy_weekly_hitter_scoring as W

        ctx = {"league_context_id": "archive:qa", "fantasy_format": "5x5 Roto", "metadata": {"league_id": "lg"},
               "team_ownership": {"A": {"user_id": "local:qa", "claim_status": "claimed"}}}
        roster = pd.DataFrame([{"Player": "Judge", "H": 1, "AB": 4, "HR": 1, "R": 1, "RBI": 1, "SB": 0},
                               {"Player": "Soto", "H": 2, "AB": 4, "HR": 0, "R": 1, "RBI": 0, "SB": 0}])
        prof = W.resolve_hitter_scoring_profile(ctx)
        with mock.patch("fantasy_league_team_ownership._resolve_user_id", return_value="local:qa"), \
                mock.patch("fantasy_weekly_hitter_scoring.resolve_canonical_league_id", return_value="lg"):
            W.create_weekly_baseline_on_lock(ctx, week=1, team="A", assignments={"UTIL": "Judge"}, roster_df=roster.iloc[[0]], profile=prof)
            W.create_weekly_baseline_on_lock(ctx, week=1, team="B", assignments={"UTIL": "Soto"}, roster_df=roster.iloc[[1]], profile=prof)
            rec_b = W.get_weekly_scoring_record(ctx, week=1, team="B")
        self.assertEqual(rec_b["canonical_team_identity"], "B")  # was the account's own team "A"
        self.assertEqual(list(rec_b["starters"]), ["soto"])
