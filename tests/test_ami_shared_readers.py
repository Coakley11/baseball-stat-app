"""The AMI shared readers in ``fantasy_read_api`` (player owner, weekly lineup status, waiver
recommendations, loaded player pool, trade verdict package, pending trade draft, week view), the
``team_access`` unknown-team fix and the capability → plan-feature metadata.

Each reader is checked against the calculation its page runs, for team access (owner,
commissioner for an unclaimed team, another manager's team, an invite-reserved team, a team that
doesn't exist), for missing state, and for side effects (session byte-identical, no network, no
file writes)."""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
import unittest
from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

import baseball_monetization as bm
import fantasy_read_api as api
from fantasy_league_context import get_active_league_context, upsert_league_context
from fantasy_season_ledger import build_lineup_snapshot, configure_season_calendar, save_period_lineup
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from fantasy_standings_snapshot import score_current_roster_standings
from tests.test_team_control_and_local_saves import _as, _league

ROOT = Path(__file__).resolve().parents[1]
AFTER = datetime(2026, 5, 1, 16, tzinfo=timezone.utc)
COMM = {"user_id": "local:qa", "acting_as": "owner"}

# Current-season hitters: the six rostered players plus three free agents.
POOL = pd.DataFrame([
    {"Player": n, "Primary Position": p, "Eligible Positions": p, "H": h, "AB": ab, "HR": hr, "R": r, "RBI": rbi,
     "SB": sb, "BA": h / ab, "OBP": h / ab + 0.06, "SLG": h / ab + 0.2, "OPS": 2 * (h / ab) + 0.26, "MLB Team": t}
    for n, p, h, ab, hr, r, rbi, sb, t in [
        ("Cal Raleigh", "C", 30, 120, 12, 20, 25, 1, "SEA"), ("Adley Rutschman", "C", 28, 110, 4, 15, 14, 0, "BAL"),
        ("Salvador Perez", "C", 25, 115, 6, 12, 18, 0, "KC"), ("Aaron Judge", "OF", 40, 120, 14, 30, 30, 3, "NYY"),
        ("Juan Soto", "OF", 35, 118, 10, 28, 24, 4, "NYM"), ("Kyle Tucker", "OF", 33, 117, 9, 26, 22, 8, "CHC"),
        ("Mike Trout", "OF", 30, 110, 11, 22, 25, 2, "LAA"), ("Will Smith", "C", 27, 105, 7, 14, 17, 0, "LAD"),
        ("Corbin Carroll", "OF", 32, 120, 6, 30, 15, 15, "ARI")]
])


def _roster_stats(session) -> pd.DataFrame:
    ctx = get_active_league_context(session)
    rows = [{**POOL[POOL.Player == p["player_name"]].iloc[0].to_dict(), "Team": team}
            for team, entry in ctx["league_rosters"].items() for p in entry["players"]]
    return pd.DataFrame(rows)


def _frozen(session) -> bytes:
    return pickle.dumps({k: session[k] for k in sorted(session, key=str)})


class ProxyLikeSession(MutableMapping):
    """Streamlit's SessionStateProxy is a MutableMapping, not a dict."""

    def __init__(self, data):
        self._d = data

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        self._d[k] = v

    def __delitem__(self, k):
        del self._d[k]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


class _LeagueCase(unittest.TestCase):
    """local:qa owns Team A and is commissioner; Team B is claimed by someone else; Team C is
    unclaimed. Current stats are loaded the way League Standings leaves them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        set_shared_league_store(LocalFileSharedLeagueStore(root=Path(self._tmp.name)))
        self.session: dict = {}
        _league(self.session, claim_b="uuid-b")
        self.stats = _roster_stats(self.session)
        self.session["fantasy_current_roster_stats"] = self.stats
        self.session["fantasy_current_standings"] = score_current_roster_standings(self.stats, "5x5 Roto")
        self.session["_fantasy_current_hitter_stats"] = POOL.copy()
        self.user = _as("local:qa")
        self.user.__enter__()

    def tearDown(self):
        self.user.__exit__(None, None, None)
        set_shared_league_store(None)
        self._tmp.cleanup()

    def _reserve(self, team: str):
        ctx = get_active_league_context(self.session)
        ownership = dict(ctx.get("team_ownership") or {})
        ownership[team] = {"team_name": team, "provisional": True, "claim_status": "reserved_live_draft",
                           "reserved_for_email": "invitee@qa"}
        ctx["team_ownership"] = ownership
        upsert_league_context(self.session, ctx)


# --- B. team_access ---------------------------------------------------------------------------


class TeamAccessTests(_LeagueCase):
    def test_owner_proxy_claimed_reserved_and_unknown(self):
        cases = {"Team A": ("owner", True), "Team C": ("commissioner_proxy", True), "Team B": ("none", False),
                 "Team Z": ("none", False), "": ("none", False)}
        for team, (mode, can) in cases.items():
            with self.subTest(team=team):
                control = api.team_access(self.session, team)
                self.assertEqual((control.mode, control.can_manage), (mode, can))
        self.assertIn("not a team in this league", api.team_access(self.session, "Team Z").reason)
        self._reserve("Team C")
        reserved = api.team_access(self.session, "Team C")
        self.assertEqual((reserved.mode, reserved.can_manage), ("none", False))
        self.assertIn("reserved for invitee@qa", reserved.reason)

    def test_unknown_team_is_refused_even_where_everyone_is_commissioner(self):
        from fantasy_team_control import resolve_team_control

        ctx = get_active_league_context(self.session)
        mock_league = {**ctx, "context_type": "mock_draft_simulation", "team_ownership": {}}
        self.assertTrue(resolve_team_control(self.session, mock_league, "Team C").can_manage)
        unknown = resolve_team_control(self.session, mock_league, "Team Z")
        self.assertEqual((unknown.mode, unknown.can_manage, unknown.is_commissioner), ("none", False, True))

    def test_every_team_reader_refuses_an_unknown_team(self):
        self.assertFalse(api.week_lineup_status(self.session, "Team Z").allowed)
        self.assertFalse(api.waiver_recommendations_view(self.session, "Team Z").allowed)
        self.assertFalse(api.pending_trade_draft(self.session, "Team Z").allowed)
        self.assertFalse(api.evaluate_trade_for_team(self.session, my_team="Team Z", partner_team="Team A", give=[],
                                                     receive=["Aaron Judge"], roster_stats=self.stats).allowed)

    def test_writes_refuse_an_unknown_team(self):
        from fantasy_waiver_wire import apply_waiver_move_pairs

        before = get_active_league_context(self.session)["league_rosters"]
        result = apply_waiver_move_pairs(self.session, [{"add_player": "Mike Trout", "drop_player": "Kyle Tucker"}],
                                         stats_pool=POOL, team="Team Z")
        self.assertFalse(result["ok"])
        self.assertIn("not a team in this league", " ".join(result["errors"]))
        self.assertEqual(get_active_league_context(self.session)["league_rosters"], before)

    def test_league_without_rosters_keeps_its_own_team(self):
        from fantasy_team_control import league_team_names

        self.assertEqual(league_team_names({"my_team_name": "Mine", "league_rosters": {}}), {"Mine"})
        self.assertEqual(league_team_names({"league_rosters": {"A": {}, "B": {}}, "my_team_name": "X"}), {"A", "B"})
        self.assertEqual(league_team_names(None), set())


# --- C. plan features -------------------------------------------------------------------------


class CapabilityFeatureTests(unittest.TestCase):
    def test_metadata_uses_the_existing_feature_ids(self):
        for capability, feature in bm.CAPABILITY_FEATURES.items():
            with self.subTest(capability=capability):
                self.assertIsInstance(feature, bm.FeatureId)
                self.assertIn(feature, bm.FEATURE_REGISTRY)
        self.assertEqual(bm.feature_for_capability("draft_team_needs"), bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE)
        self.assertIsNone(bm.feature_for_capability("player_owner"))
        for reader in ("player_owner", "week_lineup_status", "waiver_recommendations_view", "loaded_player_pool",
                       "evaluate_trade_for_team", "pending_trade_draft", "week_view"):
            self.assertIsNone(bm.feature_for_capability(reader), "fantasy readers are not plan features")

    def test_nothing_is_enforced_today(self):
        self.assertEqual(bm.ENFORCED_FEATURES, frozenset())
        self.assertEqual(bm.enforced_features(), frozenset())
        free = bm.default_entitlement()
        for capability in bm.CAPABILITY_FEATURES:
            self.assertTrue(bm.entitlement_for_capability(free, capability))

    def test_when_enforced_the_page_gate_rule_applies(self):
        pro = bm.development_entitlement("pro")
        unready = bm.EntitlementSnapshot(ready=False)
        with mock.patch.object(bm, "ENFORCED_FEATURES", frozenset({bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE})):
            self.assertEqual(bm.enforced_features(), {bm.FeatureId.ADVANCED_DRAFT_INTELLIGENCE})
            self.assertFalse(bm.entitlement_for_capability(bm.default_entitlement(), "draft_recommendations"))
            self.assertTrue(bm.entitlement_for_capability(pro, "draft_recommendations"))
            self.assertFalse(bm.entitlement_for_capability(unready, "draft_recommendations"))
            self.assertTrue(bm.entitlement_for_capability(bm.default_entitlement(), "ml_predictions"), "not enforced")
            self.assertTrue(bm.entitlement_for_capability(bm.default_entitlement(), "week_view"), "free")
        with mock.patch.object(bm, "ENFORCED_PAGE_FEATURES", {"ML Predictions": bm.FeatureId.ML_PREDICTIONS}):
            self.assertFalse(bm.entitlement_for_capability(bm.default_entitlement(), "ml_predictions"))


# --- A1. player_owner -------------------------------------------------------------------------


class PlayerOwnerTests(_LeagueCase):
    def test_same_ownership_as_transaction_validation(self):
        from fantasy_trade_proposals import _player_owner
        from fantasy_waiver_wire import is_player_rostered, resolve_waiver_league_context

        hydrated = resolve_waiver_league_context(dict(self.session))  # what Confirm Waiver Move checks
        for name in POOL["Player"]:
            with self.subTest(player=name):
                owner = api.player_owner(self.session, name)
                self.assertEqual(owner.rostered, is_player_rostered(hydrated, name))
                self.assertEqual(owner.owner_team, _player_owner(hydrated, name))  # trade proposals' lookup
                self.assertEqual(owner.is_free_agent, not owner.rostered)

    def test_statuses(self):
        self.assertEqual(api.player_owner(self.session, "aaron judge").status, "your_team")
        self.assertEqual(api.player_owner(self.session, "Aaron Judge").player, "Aaron Judge")
        soto = api.player_owner(self.session, "Juan Soto")
        self.assertEqual((soto.status, soto.owner_team, soto.my_team), ("other_team", "Team B", "Team A"))
        trout = api.player_owner(self.session, "Mike Trout")
        self.assertEqual((trout.status, trout.in_loaded_pool), ("free_agent", True))
        nobody = api.player_owner(self.session, "Nobody Here")
        self.assertEqual((nobody.status, nobody.in_loaded_pool), ("free_agent", False), "not on a roster, not known")
        self.assertEqual(api.player_owner({}, "Aaron Judge").status, "no_league")

    def test_follows_a_waiver_move(self):
        from fantasy_waiver_wire import apply_waiver_move_pairs

        result = apply_waiver_move_pairs(self.session, [{"add_player": "Mike Trout", "drop_player": "Aaron Judge"}],
                                         stats_pool=POOL, team="Team A")
        self.assertTrue(result["applied"], result)
        self.assertEqual(api.player_owner(self.session, "Mike Trout").status, "your_team")
        self.assertEqual(api.player_owner(self.session, "Aaron Judge").status, "free_agent")
        again = apply_waiver_move_pairs(self.session, [{"add_player": "Mike Trout", "drop_player": "Cal Raleigh"}],
                                        stats_pool=POOL, team="Team A")
        self.assertIn("Mike Trout is already rostered.", again["errors"], "the reader and the validator agree")


# --- A2. week_lineup_status -------------------------------------------------------------------


class LineupStatusTests(_LeagueCase):
    def _page_answer(self, team="Team A", week=1, proxy=False):
        """What the Lineup page computes for this team/week (its own helpers, its own inputs)."""
        from fantasy_weekly_lineup import lineup_status_answer, lineup_week_state, resolve_weekly_lineup_slots

        ctx = get_active_league_context(self.session)
        state = lineup_week_state(ctx, week, team=team, session=self.session, is_commissioner=True)
        saved = state["saved"] or {}
        return state, lineup_status_answer(
            team=team, week_text=f"Week {week}", slots=resolve_weekly_lineup_slots(ctx),
            assignments=dict(saved.get("assignments") or {}),
            team_roster=self.stats[self.stats.Team == team], locked=state["locked"],
            record_status=str(saved.get("status") or ""), edit_message=state["edit_message"], proxy=proxy)

    def test_not_saved_draft_and_saved_locked(self):
        from fantasy_weekly_lineup import persist_weekly_lineup_draft, save_weekly_lineup

        roster = self.stats[self.stats.Team == "Team A"]
        status = api.week_lineup_status(self.session)
        self.assertEqual((status.status, status.record_status, status.locked), ("Not saved yet", "", False))
        persist_weekly_lineup_draft(self.session, week=1, slots=["C", "OF"], assignments={"C": "Cal Raleigh", "OF": ""},
                                    my_team="Team A", roster_df=roster)
        draft = api.week_lineup_status(self.session)
        self.assertEqual((draft.status, draft.record_status), ("Draft (not submitted)", "draft"))
        self.assertEqual(draft.open_positions, ("OF 1",))
        ok = save_weekly_lineup(self.session, week=1, slots=["C", "OF"],
                                assignments={"C": "Cal Raleigh", "OF": "Aaron Judge"}, my_team="Team A", roster_df=roster)
        self.assertTrue(ok[0] if isinstance(ok, tuple) else ok, ok)
        locked = api.week_lineup_status(self.session)
        self.assertEqual((locked.status, locked.record_status, locked.locked, locked.complete),
                         ("Saved and locked", "locked", True, True))
        self.assertEqual(locked.assignments, {"C": "Cal Raleigh", "OF": "Aaron Judge"})

    def test_equals_the_lineup_page_answer(self):
        from fantasy_weekly_lineup import persist_weekly_lineup_draft

        roster = self.stats[self.stats.Team == "Team A"]
        for assignments in ({}, {"C": "Cal Raleigh", "OF": ""}, {"C": "Aaron Judge", "OF": "Cal Raleigh"}):
            with self.subTest(assignments=assignments):
                if assignments:
                    persist_weekly_lineup_draft(self.session, week=1, slots=["C", "OF"], assignments=assignments,
                                                my_team="Team A", roster_df=roster)
                state, page = self._page_answer()
                mine = api.week_lineup_status(self.session)
                self.assertEqual((mine.headline, mine.body, mine.status, mine.tone),
                                 (page["headline"], page["body"], page["status"], page["tone"]))
                self.assertEqual((mine.locked, mine.edit_message), (state["locked"], state["edit_message"]))
        bad = api.week_lineup_status(self.session)
        self.assertEqual(bad.not_eligible, ("Aaron Judge at C", "Cal Raleigh at OF"))
        check = api.check_lineup(["C", "OF"], {"C": "Aaron Judge", "OF": "Cal Raleigh"}, roster)
        self.assertEqual(len(check["ineligible_slots"]), 2, "the same rule Save Lineup applies")

    def test_the_page_uses_the_shared_helpers(self):
        src = (ROOT / "fantasy_weekly_lineup_ui.py").read_text(encoding="utf-8")
        fn = src[src.index("def render_weekly_lineup_section("):src.index("def _render_period_finalize(")]
        self.assertIn("week_state = lineup_week_state(context, int(selected_week), team=active_team, session=session,", fn)
        self.assertIn("answer = lineup_status_answer(", fn)
        self.assertNotIn("lineup_answer(", fn.replace("lineup_status_answer(", ""))

    def test_access_proxy_and_missing_state(self):
        proxy = api.week_lineup_status(self.session, "Team C")
        self.assertTrue(proxy.allowed)
        self.assertEqual(proxy.acting_as, "commissioner_proxy")
        self.assertTrue(proxy.headline.startswith("Team C's lineup"))
        self.assertFalse(api.week_lineup_status(self.session, "Team B").allowed)
        self.assertFalse(api.week_lineup_status({}).allowed)
        no_stats = dict(self.session)
        no_stats.pop("fantasy_current_roster_stats")
        bare = api.week_lineup_status(no_stats)
        self.assertTrue(bare.allowed)
        self.assertFalse(bare.roster_loaded)
        self.assertEqual(bare.status, "Not saved yet", "status needs no stats; eligibility does")

    def test_season_calendar_week(self):
        ctx = get_active_league_context(self.session)
        configure_season_calendar(ctx, first_day="2030-04-01", period_count=3)
        upsert_league_context(self.session, ctx)
        status = api.week_lineup_status(self.session)
        self.assertEqual((status.week, status.has_season_calendar, status.period_status), (1, True, "upcoming"))
        self.assertIn("before it starts on 2030-04-01", status.edit_message)
        self.assertFalse(api.week_lineup_status(self.session, week=9).allowed)


# --- A3/A4. waivers ---------------------------------------------------------------------------


def _page_waiver_capture(session):
    """Run the real Waiver Wire page and capture what it hands its answer card."""
    from fantasy_waiver_wire_ui import WAIVER_POSITION_FILTER_KEY, render_waiver_wire_page
    from fantasy_waiver_wire import loaded_waiver_stats_pool

    captured = {}

    def selectbox(label, options=(), *a, **k):
        # Streamlit returns the widget's session value, else the option at ``index`` (default 0).
        options = list(options or k.get("options") or [])
        key = k.get("key")
        if key and key in session:
            return session[key]
        return options[int(k.get("index", 0) or 0)] if options else None

    st = mock.MagicMock()
    st.selectbox = mock.MagicMock(side_effect=selectbox)
    st.columns = mock.MagicMock(side_effect=lambda spec, *a, **k: [mock.MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))])
    st.button = mock.MagicMock(return_value=False)
    st.multiselect = mock.MagicMock(return_value=[])
    st.text_input = mock.MagicMock(return_value="")
    with mock.patch("fantasy_waiver_wire_ui._render_u1_waiver_answer",
                    side_effect=lambda _st, **kw: captured.update(kw)):
        render_waiver_wire_page(st, session, current_stats_pool=loaded_waiver_stats_pool(session),
                                league_roster_stats=session.get("fantasy_current_roster_stats"))
    return captured


class WaiverTests(_LeagueCase):
    def test_equals_the_waiver_wire_page(self):
        import u1_answers as u1a
        from fantasy_waiver_wire import waiver_card_fields

        for position in ("All positions", "C", "OF"):
            with self.subTest(position=position):
                page_session = dict(self.session, waiver_position_filter=position)
                page = _page_waiver_capture(page_session)
                self.assertTrue(page, "the page reached its answer card")
                mine = api.waiver_recommendations_view(self.session, position=position, limit=3)
                self.assertTrue(mine.allowed, mine.reason)
                self.assertEqual(mine.headline, u1a.needs_headline(page["needs"]))
                expected = [waiver_card_fields(row, page["my_roster"]) for _, row in page["adds"].head(3).iterrows()]
                self.assertEqual([{k: c[k] for k in expected[0]} for c in mine.adds] if expected else [], expected)
                self.assertEqual(mine.open_roster_spots, tuple(page["open_slots"]))
                self.assertEqual(mine.team, page["my_team"])

    def test_cards_carry_structured_reasons_and_are_unrostered(self):
        view = api.waiver_recommendations_view(self.session, limit=15)
        self.assertEqual([c["rank"] for c in view.adds], list(range(1, len(view.adds) + 1)))
        for card in view.adds:
            self.assertEqual(api.player_owner(self.session, card["player"]).status, "free_agent")
            self.assertTrue(card["why"])
            self.assertIn("OPS", card["stats"])
        self.assertTrue(view.drops and all(d["why"] for d in view.drops))
        self.assertIn("Confirm Waiver Move", view.basis)

    def test_access_and_missing_state(self):
        self.assertEqual(api.waiver_recommendations_view(self.session, "Team C").acting_as, "commissioner_proxy")
        self.assertFalse(api.waiver_recommendations_view(self.session, "Team B").allowed)
        self.assertFalse(api.waiver_recommendations_view(self.session, position="P").allowed)
        no_stats = dict(self.session)
        no_stats.pop("_fantasy_current_hitter_stats")
        missing = api.waiver_recommendations_view(no_stats)
        self.assertFalse(missing.allowed)
        self.assertIn("aren't loaded", missing.reason)
        self.assertFalse(api.waiver_recommendations_view({}).allowed)

    def test_loaded_player_pool_is_bounded_and_unrostered(self):
        from fantasy_waiver_wire import build_waiver_pool

        pool = api.loaded_player_pool(self.session)
        expected = build_waiver_pool(POOL, get_active_league_context(self.session))
        self.assertEqual([r["player"] for r in pool.rows], expected["Player"].tolist())
        self.assertEqual(pool.total, len(expected))
        self.assertEqual(set(pool.rows[0]), {"player", "mlb_team", "positions", "stats"})
        self.assertEqual(len(api.loaded_player_pool(self.session, limit=1).rows), 1)
        self.assertEqual(len(api.loaded_player_pool(self.session, unrostered_only=False, limit=500).rows), len(POOL))
        self.assertEqual([r["player"] for r in api.loaded_player_pool(self.session, position="C").rows], ["Will Smith"])
        self.assertEqual([r["player"] for r in api.loaded_player_pool(self.session, query="carroll").rows], ["Corbin Carroll"])
        no_stats = dict(self.session)
        no_stats.pop("_fantasy_current_hitter_stats")
        self.assertFalse(api.loaded_player_pool(no_stats).available)


# --- A5. trade package ------------------------------------------------------------------------


class TradePackageTests(_LeagueCase):
    def _trade_center_card(self, give, receive, partner):
        """Trade Center's own verdict card: its workspace, its roster checks, its package."""
        import fantasy_trade_center_ui as tc
        from fantasy_standings_snapshot import summarize_team_category_needs
        from fantasy_trade_analysis import build_trade_analysis_package
        from fantasy_trade_category_values import format_trade_category_value
        from fantasy_trade_evaluation import build_trade_verdict_text, evaluate_trade
        from u3_answers import trade_verdict

        ws = tc._trade_workspace(self.session, my_team="Team A")
        issues = tc._trade_roster_issues(self.session, proposer_team="Team A", recipient_team=partner,
                                         proposer_gives=give, proposer_receives=receive)
        package = build_trade_analysis_package(
            give_players=give, receive_players=receive, roster_stats=ws["roster_stats"], standings=ws["standings"],
            my_team="Team A", evaluate_trade_fn=evaluate_trade, build_trade_verdict_text_fn=build_trade_verdict_text,
            summarize_team_category_needs_fn=summarize_team_category_needs)
        card = trade_verdict(package, my_team="Team A", partner=partner, roster_issues=issues,
                             format_change=lambda c, v: format_trade_category_value(c, v, is_change=True))
        return package, issues, card

    def test_verdict_equals_trade_center(self):
        for give, receive, partner in ((["Cal Raleigh"], ["Kyle Tucker"], "Team C"),
                                       (["Aaron Judge"], ["Kyle Tucker"], "Team C"),
                                       (["Aaron Judge"], ["Juan Soto"], "Team B"),
                                       (["Cal Raleigh", "Aaron Judge"], ["Salvador Perez"], "Team C")):
            with self.subTest(give=give, receive=receive):
                package, issues, card = self._trade_center_card(give, receive, partner)
                mine = api.evaluate_trade_for_team(self.session, my_team="Team A", partner_team=partner, give=give,
                                                   receive=receive, roster_stats=self.stats)
                self.assertTrue(mine.allowed, mine.reason)
                self.assertEqual((mine.verdict_label, mine.value_label, mine.verdict_headline, mine.verdict_body,
                                  mine.verdict_tone), (card["label"], card["value_label"], card["headline"],
                                                       card["body"], card["tone"]))
                self.assertEqual(list(mine.roster_issues), issues)
                self.assertEqual(list(mine.required_position_issues) + list(mine.roster_size_issues), card["my_issues"])
                self.assertEqual(list(mine.other_team_notes), card["other_notes"])
                self.assertEqual((mine.verdict, mine.weighted_gain), (package["verdict"], package["weighted_gain"]))
                self.assertEqual(list(mine.category_changes), package["category_rows"])
                self.assertEqual(mine.analysis, package)

    def test_roster_issue_overrides_the_value_label(self):
        catcherless = api.evaluate_trade_for_team(self.session, my_team="Team A", partner_team="Team C",
                                                  give=["Cal Raleigh"], receive=["Kyle Tucker"], roster_stats=self.stats)
        self.assertEqual(catcherless.verdict_label, "Creates roster issue")
        self.assertEqual(catcherless.required_position_issues,
                         ("This trade leaves your team without an eligible C for the required lineup.",))
        self.assertTrue(catcherless.value_label)

    def test_existing_fields_unchanged_without_loaded_standings(self):
        from fantasy_trade_evaluation import evaluate_trade

        bare = dict(self.session)
        bare.pop("fantasy_current_standings")
        bare.pop("_fantasy_current_hitter_stats")
        mine = api.evaluate_trade_for_team(bare, my_team="Team A", partner_team="Team C", give=["Aaron Judge"],
                                           receive=["Kyle Tucker"], roster_stats=self.stats)
        table, verdict, gain = evaluate_trade(["Aaron Judge"], ["Kyle Tucker"], self.stats, self.stats,
                                              score_current_roster_standings(self.stats, "5x5 Roto"), "Team A")
        pd.testing.assert_frame_equal(mine.category_table, table)
        self.assertEqual((mine.verdict, mine.weighted_gain), (verdict, gain))
        self.assertEqual(mine.legality_warnings, tuple(i["message"] for i in mine.roster_issues))


# --- A6. pending trade draft ------------------------------------------------------------------


class PendingTradeTests(_LeagueCase):
    def _scope_key(self):
        from fantasy_league_identity import resolve_canonical_league_id
        from fantasy_trade_builder_state import trade_scope_fingerprint, trade_scope_state_key

        ctx = get_active_league_context(self.session)
        league = str(resolve_canonical_league_id(ctx) or ctx.get("league_context_id") or "")
        return trade_scope_state_key(trade_scope_fingerprint("Team A", league))

    def test_reads_the_trade_center_builder(self):
        import fantasy_trade_center_ui as tc
        from fantasy_trade_builder_state import builder_widget_keys

        scope = tc._resolve_trade_scope(self.session, page_lineup_team="Team A")
        self.assertEqual(tc._trade_scope_state_key(scope["scope_fingerprint"]), self._scope_key(), "Trade Center's key")
        keys = builder_widget_keys(self._scope_key())
        self.session.update({keys["give"]: ["Aaron Judge"], keys["receive"]: ["Kyle Tucker"], keys["partner"]: "Any team"})
        draft = api.pending_trade_draft(self.session)
        self.assertEqual((draft.give, draft.receive, draft.partner, draft.source, draft.is_complete),
                         (("Aaron Judge",), ("Kyle Tucker",), "Team C", "builder", True))
        verdict = api.evaluate_trade_for_team(self.session, my_team=draft.team, partner_team=draft.partner,
                                              give=list(draft.give), receive=list(draft.receive), roster_stats=self.stats)
        self.assertTrue(verdict.allowed)

    def test_saved_state_analysis_and_empty(self):
        self.assertEqual(api.pending_trade_draft(self.session).source, "none")
        self.session[self._scope_key()] = {"give_players": ["Cal Raleigh"], "get_players": ["Juan Soto"],
                                           "trade_partner": "Team B", "analysis": {
                                               "give_players": ["Cal Raleigh"], "receive_players": ["Juan Soto"],
                                               "verdict": "Neutral", "weighted_gain": 0.5}}
        draft = api.pending_trade_draft(self.session)
        self.assertEqual((draft.source, draft.partner, draft.last_analysis),
                         ("saved_state", "Team B", {"verdict": "Neutral", "weighted_gain": 0.5}))

    def test_access(self):
        self.assertFalse(api.pending_trade_draft(self.session, "Team B").allowed)
        self.assertFalse(api.pending_trade_draft({}).allowed)


# --- A7. week_view ----------------------------------------------------------------------------


class WeekViewTests(_LeagueCase):
    def _finalize_week_one(self):
        from fantasy_season_results import finalize_period

        ctx = get_active_league_context(self.session)
        configure_season_calendar(ctx, first_day="2026-04-06", period_count=2)
        for team, c, of in (("Team A", "Cal Raleigh", "Aaron Judge"), ("Team B", "Adley Rutschman", "Juan Soto"),
                            ("Team C", "Salvador Perez", "Kyle Tucker")):
            roster = self.stats[self.stats.Team == team]
            snap = build_lineup_snapshot(team=team, slots=["C", "OF"], slot_assignments={"C": c, "OF": of}, roster_df=roster)
            ok, err = save_period_lineup(ctx, number=1, team=team, snapshot=snap, actor=COMM, is_commissioner=True, now=AFTER)
            self.assertTrue(ok, err)
        week = self.stats.assign(PA=self.stats["AB"], **{"2B": 0, "3B": 0, "BB": 0, "HBP": 0, "SF": 0, "TB": self.stats["H"],
                                                          "G": 6})
        week = week[week.Player != "Juan Soto"]  # no games for Soto this week
        ok, err, _ = finalize_period(ctx, 1, stats_df=week, actor=COMM, is_commissioner=True, now=AFTER)
        self.assertTrue(ok, err)
        upsert_league_context(self.session, ctx)
        return get_active_league_context(self.session)

    def test_finalized_week_equals_the_ledger(self):
        from fantasy_season_ledger import get_period_lineup
        from fantasy_season_results import period_category_table, period_result

        ctx = self._finalize_week_one()
        view = api.week_view(self.session, 1, "Team B")
        self.assertTrue(view.available, view.reason)
        self.assertEqual((view.status, view.status_label, view.finalized, view.last_finalized_week, view.current_week),
                         ("finalized", "Final", True, 1, 2))
        self.assertEqual(pd.DataFrame(list(view.category_table)).to_dict("records"),
                         period_category_table(ctx, 1).to_dict("records"))
        result = period_result(ctx, 1)["teams"]["Team B"]
        self.assertEqual(view.team_result["totals"], result["totals"])
        self.assertEqual(view.team_result["starters"], result["starters"])
        soto = next(s for s in view.team_result["starters"] if s["player_name"] == "Juan Soto")
        self.assertEqual(soto["matched_by"], "no_games", "why Soto didn't count")
        snap = get_period_lineup(ctx, 1, "Team B")
        self.assertEqual([s["player"] for s in view.team_lineup["starters"]], [s["player_name"] for s in snap["starters"]])
        self.assertEqual(view.team_lineup["starters"][0]["owner_at_snapshot"], "Team B")
        dumped = json.dumps(view.team_lineup) + json.dumps(view.team_result)
        for secret in ("saved_by", "local:qa", "audit", "user_id"):
            self.assertNotIn(secret, dumped)

    def test_default_week_and_missing_states(self):
        self.assertFalse(api.week_view(self.session).available, "no season calendar yet")
        self._finalize_week_one()
        current = api.week_view(self.session)
        self.assertEqual((current.number, current.finalized, current.category_table), (2, False, ()))
        self.assertFalse(api.week_view(self.session, 7).available)
        self.assertFalse(api.week_view(self.session, 1, "Team Z").available)
        self.assertFalse(api.week_view({}).available)

    def test_unstarted_week_lineups_stay_private(self):
        ctx = get_active_league_context(self.session)
        configure_season_calendar(ctx, first_day="2030-04-01", period_count=2)
        for team in ("Team A", "Team B"):
            roster = self.stats[self.stats.Team == team]
            snap = build_lineup_snapshot(team=team, slots=["C", "OF"], slot_assignments={}, roster_df=roster)
            self.assertTrue(save_period_lineup(ctx, number=1, team=team, snapshot=snap, actor=COMM, is_commissioner=True)[0])
        upsert_league_context(self.session, ctx)
        self.assertEqual(api.week_view(self.session, 1, "Team B").lineup_visibility, "private")
        self.assertIsNone(api.week_view(self.session, 1, "Team B").team_lineup)
        self.assertEqual(api.week_view(self.session, 1, "Team A").lineup_visibility, "visible")
        self.assertEqual(api.week_view(self.session, 1, "Team C").lineup_visibility, "not_set")


# --- side effects -----------------------------------------------------------------------------


def _all_readers(session, stats):
    return [
        api.player_owner(session, "Aaron Judge"), api.week_lineup_status(session), api.week_lineup_status(session, "Team C"),
        api.waiver_recommendations_view(session), api.loaded_player_pool(session), api.pending_trade_draft(session),
        api.week_view(session), api.team_access(session, "Team Z"),
        api.evaluate_trade_for_team(session, my_team="Team A", partner_team="Team C", give=["Aaron Judge"],
                                    receive=["Kyle Tucker"], roster_stats=stats),
    ]


class SideEffectTests(_LeagueCase):
    def test_session_is_byte_identical_dict_and_proxy(self):
        from fantasy_trade_builder_state import builder_widget_keys

        keys = builder_widget_keys("trade_center_state|trade|Team A|x")
        self.session[keys["give"]] = ["Aaron Judge"]
        for session in (self.session, ProxyLikeSession(self.session)):
            with self.subTest(kind=type(session).__name__):
                before = _frozen(session)
                _all_readers(session, self.stats)
                self.assertEqual(_frozen(session), before)

    def test_no_network_and_no_stats_fetch(self):
        def boom(*_a, **_k):
            raise AssertionError("a reader tried to sync or fetch")

        with mock.patch("fantasy_shared_league_store.sync_context_with_shared_store", side_effect=boom), \
                mock.patch("fantasy_shared_league_store.push_league_context_to_shared", side_effect=boom), \
                mock.patch("fantasy_lineup_stats_loader.ensure_lineup_page_hitter_stats", side_effect=boom), \
                mock.patch("requests.sessions.Session.request", side_effect=boom):
            results = _all_readers(self.session, self.stats)
        self.assertTrue(all(results))


WRITE_PROBE = r"""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.getcwd())
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
from fantasy_shared_league_store import LocalFileSharedLeagueStore, set_shared_league_store
from tests.test_ami_shared_readers import POOL, _all_readers, _roster_stats
from tests.test_team_control_and_local_saves import _as, _league
from fantasy_standings_snapshot import score_current_roster_standings
tmp = tempfile.mkdtemp()
set_shared_league_store(LocalFileSharedLeagueStore(root=Path(tmp)))
session = {}
with _as("local:qa"):
    _league(session, claim_b="uuid-b")
    stats = _roster_stats(session)
    session.update(fantasy_current_roster_stats=stats, _fantasy_current_hitter_stats=POOL,
                   fantasy_current_standings=score_current_roster_standings(stats, "5x5 Roto"))
    _all_readers(session, stats)  # warm imports outside the audit
    writes, armed = [], [True]
    def audit(event, args):
        if not armed[0]:
            return
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            mode = str(args[1] or "r") if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            if any(c in mode for c in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
                writes.append(str(args[0]))
        elif event in ("os.rename", "os.replace", "os.remove", "os.unlink", "shutil.rmtree"):
            writes.append(f"{event}:{args[0]}")
    sys.addaudithook(audit)
    _all_readers(session, stats)
    armed[0] = False
print(json.dumps(sorted(set(writes))))
"""


class NoFileWriteTests(unittest.TestCase):
    def test_readers_write_no_files(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        out = subprocess.run([sys.executable, "-c", WRITE_PROBE], cwd=ROOT, env=env, capture_output=True, text=True,
                             timeout=600)
        self.assertEqual(out.returncode, 0, out.stderr[-3000:])
        self.assertEqual(json.loads(out.stdout.strip().splitlines()[-1]), [])


if __name__ == "__main__":
    unittest.main()
