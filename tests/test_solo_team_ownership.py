"""Solo team ownership (owner review + decision, 2026-11-08).

The owner's own team read "Dave is managed by coakley11." and every lineup drop snapped back. The hosted app
has two ids for one account (the sign-in id and the suite account id). Dave's ownership record holds the suite
id, but the check compared it with the sign-in id, and the id bridge only read plain dicts, while the hosted
session is a SessionStateProxy. Tests used one id for both, so this never showed.

Owner decision: a personal solo draft saved while signed in is owned by the verified account automatically.
Never in a shared league, never from a display name or browser state, never over an existing claim.
"""

from __future__ import annotations

import unittest
from collections.abc import MutableMapping
from unittest import mock

import pandas as pd

from fantasy_league_context import (
    assign_solo_team_to_verified_account,
    get_active_league_context,
    is_personal_solo_context,
    save_simulator_league_context,
)
from fantasy_league_team_ownership import assign_team_owner_to_context, get_team_ownership, ownership_is_firm_claim
from fantasy_team_control import MODE_NONE, MODE_OWNER, resolve_team_control

BOARD = pd.DataFrame([
    {"Team": "Dave", "Player": "Aaron Judge", "Pick": 1, "Primary Position": "OF"},
    {"Team": "Bob", "Player": "Juan Soto", "Pick": 2, "Primary Position": "OF"},
    {"Team": "Bob", "Player": "Trea Turner", "Pick": 3, "Primary Position": "SS"},
    {"Team": "Dave", "Player": "Francisco Lindor", "Pick": 4, "Primary Position": "SS"},
])


class HostedSession(MutableMapping):
    """Like Streamlit's SessionStateProxy: a mapping, but not a dict."""

    def __init__(self, **kw):
        self._d = dict(kw)

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


def _signed_in(**extra) -> HostedSession:
    return HostedSession(_suite_auth_session=True, _suite_auth_user_id="auth-1", _suite_cloud_user_id="suite-1", **extra)


def _hosted():
    return mock.patch.multiple("fantasy_shared_league_authz", sign_in_enabled=mock.DEFAULT,
                               checked_load=mock.DEFAULT)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        p = mock.patch("fantasy_shared_league_authz.sign_in_enabled", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch("fantasy_team_control.auth_required", return_value=True)
        p2.start()
        self.addCleanup(p2.stop)
        p3 = mock.patch("fantasy_shared_league_authz.checked_load", return_value=("missing", None))
        self.load = p3.start()
        self.addCleanup(p3.stop)

    def _context(self, session):
        save_simulator_league_context(session, BOARD, my_team_name="Dave")
        return get_active_league_context(session)


class SplitIdTests(_Base):
    def test_the_owners_team_recorded_with_the_suite_id_is_theirs(self) -> None:
        session = _signed_in()
        ctx = self._context(session)
        ctx = assign_team_owner_to_context(ctx, "Dave", user_id="suite-1")  # how Dave's record was stored
        control = resolve_team_control(session, ctx, "Dave")
        self.assertEqual(control.mode, MODE_OWNER, control.reason)

    def test_another_accounts_team_is_not(self) -> None:
        session = _signed_in()
        ctx = assign_team_owner_to_context(self._context(session), "Dave", user_id="suite-2")
        control = resolve_team_control(session, ctx, "Dave")
        self.assertEqual(control.mode, MODE_NONE)
        self.assertIn("is managed by", control.reason)

    def test_a_matching_display_name_or_email_is_never_ownership(self) -> None:
        session = _signed_in()
        ctx = assign_team_owner_to_context(self._context(session), "Dave", user_id="suite-2",
                                           display_name="coakley11", email="coakley11@example.com")
        self.assertEqual(resolve_team_control(session, ctx, "Dave").mode, MODE_NONE)


class AutoOwnershipTests(_Base):
    def test_a_signed_in_solo_draft_is_owned_by_the_verified_account(self) -> None:
        session = _signed_in()
        ctx = self._context(session)
        rec = get_team_ownership(ctx).get("Dave") or {}
        self.assertTrue(ownership_is_firm_claim(rec))
        self.assertEqual(rec["user_id"], "suite-1")  # the suite account id, what league records use
        self.assertNotIn("Bob", get_team_ownership(ctx))  # the other team is never claimed
        self.assertEqual(resolve_team_control(session, ctx, "Dave").mode, MODE_OWNER)

    def test_saving_again_changes_nothing(self) -> None:
        session = _signed_in()
        first = dict(get_team_ownership(self._context(session))["Dave"])
        again = assign_solo_team_to_verified_account(session, get_active_league_context(session))
        self.assertIsNone(again)  # a firm claim already exists
        self.assertEqual(get_team_ownership(get_active_league_context(session))["Dave"]["user_id"], first["user_id"])

    def test_signed_out_records_nothing(self) -> None:
        session = HostedSession()
        ctx = self._context(session)
        self.assertEqual({k: v for k, v in get_team_ownership(ctx).items() if ownership_is_firm_claim(v)}, {})

    def test_never_in_a_shared_league(self) -> None:
        session = _signed_in()
        ctx = self._context(HostedSession())  # built signed out: no record yet
        for status in ("found", "error"):
            self.load.return_value = (status, {} if status == "found" else None)
            self.assertFalse(is_personal_solo_context(ctx), status)
            self.assertIsNone(assign_solo_team_to_verified_account(session, ctx), status)
        self.load.return_value = ("missing", None)
        real = dict(ctx, context_type="real_league")
        self.assertIsNone(assign_solo_team_to_verified_account(session, real))
        from_room = dict(ctx, metadata={**(ctx.get("metadata") or {}), "source_room_code": "ABC123"})
        self.assertIsNone(assign_solo_team_to_verified_account(session, from_room))

    def test_an_existing_claim_is_never_replaced(self) -> None:
        session = _signed_in()
        ctx = assign_team_owner_to_context(self._context(HostedSession()), "Bob", user_id="suite-9")
        self.assertIsNone(assign_solo_team_to_verified_account(session, ctx))
        self.assertEqual(get_team_ownership(ctx)["Bob"]["user_id"], "suite-9")
        self.assertNotIn("Dave", {k for k, v in get_team_ownership(ctx).items() if ownership_is_firm_claim(v)})

    def test_an_older_or_imported_draft_is_never_auto_claimed(self) -> None:
        session = _signed_in()
        ctx = self._context(HostedSession())
        legacy = {k: v for k, v in ctx.items() if k != "context_type"}  # older saved shape: no type at all
        self.assertIsNone(assign_solo_team_to_verified_account(session, legacy))
        imported = dict(ctx, context_type="real_league", metadata={**(ctx.get("metadata") or {}), "source": "imported_draft"})
        self.assertIsNone(assign_solo_team_to_verified_account(session, imported))
        # The claim is made only when the owner saves a Simulator draft, never on load, restore or render.
        import re
        from pathlib import Path as _P
        root = _P(__file__).resolve().parents[1]
        calls = [f.name for f in root.glob("*.py")
                 if re.search(r"(?<!def )assign_solo_team_to_verified_account\(", f.read_text(encoding="utf-8"))]
        self.assertEqual(calls, ["fantasy_league_context.py"])
        src = (root / "fantasy_league_context.py").read_text(encoding="utf-8")
        body = src[src.index("def save_simulator_league_context("):]
        body = body[:body.index(chr(10) + "def ", 1)]
        self.assertIn("assign_solo_team_to_verified_account(", body)
        self.assertEqual(src.count("assign_solo_team_to_verified_account("), 2)  # the definition + that one call


if __name__ == "__main__":
    unittest.main()
