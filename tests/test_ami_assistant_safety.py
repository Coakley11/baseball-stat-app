"""AMI safety: read-only by construction, no secrets in context/payloads, no other users' data."""

from __future__ import annotations

import ast
import copy
import unittest
from collections.abc import Mapping
from pathlib import Path

from ami_assistant.capabilities import FUTURE_ACTION_KEYS
from ami_assistant.context import PAGE_KEYS, build_ami_context
from ami_assistant.conversation import SESSION_KEY
from ami_assistant.engine import ask
from ami_assistant.provider import ComposeRequest, build_model_payload
from ami_assistant.router import Router
from ami_assistant.safety import find_secrets, looks_secret, scrub
from ami_assistant.tools import REGISTRY
from ami_assistant.tools.registry import ToolRegistry, ToolResult, ToolSpec
from tests.ami_assistant_fixtures import realistic_draft_session, synthetic_dataset

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "ami_assistant"

SECRETS = {
    "sb_access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.c2lnbmF0dXJlLXZhbHVl",
    "stripe_secret_key": "sk_live_51HxAbCdEfGhIjKlMnOpQrStUv",
    "stripe_customer_id": "cus_Q1w2E3r4T5y6U7",
    "supabase_service_role_key": "sb_secret_abcdefghijklmnop",
    "anthropic_key": "sk-ant-api03-abcdefghijklmnopqrstuvwx",
    "db_url": "postgresql://postgres:hunter2@db.example.supabase.co:5432/postgres",
    "user_password": "password: hunter2",
}


def secret_session() -> dict:
    session = {k: v for k, v in SECRETS.items()}
    session["_suite_auth"] = {"access_token": SECRETS["sb_access_token"], "refresh_token": "r-abc"}
    session["workspace_blob"] = {"other_user": {"roster": ["Somebody Else"]}}
    return session


def assert_same(test: unittest.TestCase, a, b, path: str = "session") -> None:
    """Deep equality that understands DataFrames."""
    import pandas as pd

    if isinstance(a, pd.DataFrame) or isinstance(b, pd.DataFrame):
        pd.testing.assert_frame_equal(a, b, obj=path)
    elif isinstance(a, Mapping) and isinstance(b, Mapping):
        test.assertEqual(set(a), set(b), path)
        for k in a:
            assert_same(test, a[k], b[k], f"{path}[{k!r}]")
    elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        test.assertEqual(len(a), len(b), path)
        for i, (x, y) in enumerate(zip(a, b)):
            assert_same(test, x, y, f"{path}[{i}]")
    else:
        test.assertEqual(a, b, path)


class RecordingSession(dict):
    """Records every key read, to prove AMI only reads allowlisted keys."""

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.read: set[str] = set()

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)


class ReadOnlyTests(unittest.TestCase):
    def test_no_registered_tool_mutates_and_no_future_action_is_callable(self) -> None:
        self.assertTrue(all(not spec.mutates for spec in REGISTRY.specs()))
        self.assertFalse(FUTURE_ACTION_KEYS & set(REGISTRY.names()))
        for verb in ("draft_player", "add_player", "drop_player", "execute_trade", "set_lineup", "save"):
            self.assertIsNone(REGISTRY.get(verb))

    def test_registry_refuses_a_mutating_tool(self) -> None:
        reg = ToolRegistry()
        spec = ToolSpec("draft_player", "future_actions", "x", {}, lambda **_: ToolResult("draft_player", True), mutates=True)
        with self.assertRaises(ValueError):
            reg.register(spec)

    def test_unwired_fantasy_tools_are_not_offered_to_a_model(self) -> None:
        offered = {s["name"] for s in REGISTRY.schemas()}
        for name in ("get_active_league", "get_team_roster", "get_lineup", "get_standings", "get_available_free_agents", "evaluate_trade"):
            self.assertNotIn(name, offered)
            self.assertFalse(REGISTRY.get(name).wired)

    def test_package_imports_no_storage_auth_billing_network_or_model_sdk(self) -> None:
        forbidden = ("suite_storage", "suite_auth", "suite_cloud_state", "suite_user_persistence", "baseball_billing",
                     "baseball_persistent_state", "draft_room_supabase", "fantasy_shared_league", "requests", "urllib",
                     "http", "socket", "anthropic", "openai", "subprocess", "draft_state", "applied_math_context",
                     "live_draft_pick_commit", "draft_actions", "fantasy_waiver_wire", "fantasy_trade_proposals")
        for path in PKG.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for name in names:
                    self.assertFalse(any(name == f or name.startswith(f + ".") or name.startswith(f) for f in forbidden),
                                     f"{path.name} imports {name}")

    def test_tools_never_write_to_session(self) -> None:
        for path in (PKG / "tools").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
                    targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
                    for t in targets:
                        self.assertFalse(isinstance(t, ast.Subscript) and getattr(t.value, "id", "") == "session",
                                         f"{path.name}:{node.lineno} writes session")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                        getattr(node.func.value, "id", "") == "session":
                    self.assertIn(node.func.attr, ("get",), f"{path.name}:{node.lineno} calls session.{node.func.attr}")

    def test_answering_draft_questions_leaves_session_state_untouched(self) -> None:
        session = realistic_draft_session()
        before = copy.deepcopy({k: v for k, v in session.items()})
        ds = synthetic_dataset()
        for q in ("Who should I draft next?", "Why is Cal Raleigh recommended?", "What positions am I weak at?",
                  "Draft Cal Raleigh", "Should I draft for need or take the best player available?"):
            ask(q, session_state=session, active_page="Draft Assistant Simulator", dataset=ds)
        after = {k: v for k, v in session.items() if k != SESSION_KEY}
        assert_same(self, after, before)


class SecretTests(unittest.TestCase):
    def test_patterns(self) -> None:
        for value in SECRETS.values():
            self.assertTrue(looks_secret(value), value)
        for ok in ("Aaron Judge", "Valuation Score 100.00", "2023–2025", "Fantasy Edge = Market Rank − Model Rank"):
            self.assertFalse(looks_secret(ok), ok)

    def test_context_reads_only_allowlisted_keys(self) -> None:
        allowed = {k for page in PAGE_KEYS.values() for keys in page.values() for k in keys} | {"_ami_draft_snapshot"}
        for page in (*PAGE_KEYS, "Draft Assistant Simulator", "Fantasy Lineup Assistant", ""):
            session = RecordingSession(secret_session())
            build_ami_context(session, page)
            self.assertTrue(session.read <= allowed, (page, session.read - allowed))

    def test_secret_values_in_allowed_keys_are_dropped(self) -> None:
        ctx = build_ami_context({"compare_players": [SECRETS["stripe_secret_key"], "Aaron Judge"],
                                 "compare_stat": SECRETS["sb_access_token"]}, "Comparison Tool")
        self.assertEqual(ctx.players, ("Aaron Judge",))
        self.assertEqual(ctx.metric, "")
        self.assertEqual(find_secrets(ctx.as_dict()), [])

    def test_no_secret_reaches_the_model_payload_or_the_answer(self) -> None:
        session = realistic_draft_session()
        session.update(secret_session())
        # A poisoned recommendation row must not leak either.
        session["_ami_draft_snapshot"]["recommended_players"][0]["why_this_pick"] = "token " + SECRETS["stripe_secret_key"]
        ds = synthetic_dataset()
        for page, q in (("Draft Assistant Simulator", "Why is Cal Raleigh recommended?"), ("Comparison Tool", "Compare Judge and Soto"),
                        ("Valuation", "Why is he ranked this high?"), ("", "What can you do?")):
            ctx = build_ami_context(session, page)
            from ami_assistant.conversation import ConversationState

            plan = Router(ds).route(q, ctx, ConversationState())
            results = {}
            for call in plan.calls:
                results.setdefault(call.name, []).append(REGISTRY.call(call.name, call.args, dataset=ds, session=session))
            payload = build_model_payload(ComposeRequest(q, plan, results, ctx.as_dict(), REGISTRY.schemas()))
            self.assertEqual(find_secrets(payload), [], q)
            text = str(payload)
            for value in SECRETS.values():
                self.assertNotIn(value, text)
            self.assertNotIn("Somebody Else", text)  # another user's workspace data
            answer = ask(q, session_state=session, active_page=page, dataset=ds).answer
            for value in SECRETS.values():
                self.assertNotIn(value, answer)

    def test_scrub_redacts_nested_values_and_keys(self) -> None:
        out = scrub({"a": [SECRETS["stripe_secret_key"], {"b": SECRETS["db_url"]}], SECRETS["anthropic_key"]: 1, "ok": "Judge"})
        self.assertEqual(find_secrets(out), [])
        self.assertEqual(out["ok"], "Judge")


class ConversationStorageTests(unittest.TestCase):
    def test_conversation_is_not_persisted_to_the_cloud_workspace(self) -> None:
        src = (ROOT / "baseball_persistent_state.py").read_text(encoding="utf-8")
        self.assertNotIn("_ami_assistant", src)
        self.assertNotIn("ami_assistant", (ROOT / "page_state.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
