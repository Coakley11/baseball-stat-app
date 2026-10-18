"""AMI safety: read-only by construction, no secrets in context/payloads, no other users' data."""

from __future__ import annotations

import ast
import copy
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from ami_assistant.capabilities import FUTURE_ACTION_KEYS
from ami_assistant.context import PAGE_KEYS, build_ami_context
from ami_assistant.conversation import SESSION_KEY
from ami_assistant.engine import ask
from ami_assistant.provider import ComposeRequest, build_model_payload
from ami_assistant.router import Router
from ami_assistant.safety import find_secrets, looks_secret, scrub
from ami_assistant.tools import REGISTRY
from ami_assistant.tools import registry as codes
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

    def test_every_tool_is_wired_and_offered(self) -> None:
        # The waiver reader exists now (633538f); no unwired contract remains to hide from a model.
        offered = {s["name"] for s in REGISTRY.schemas()}
        self.assertEqual(offered, set(REGISTRY.names()))
        self.assertTrue(all(REGISTRY.get(n).wired for n in REGISTRY.names()))

    def test_no_tool_can_change_the_app(self) -> None:
        # The app supports these actions; AMI must not, in any spelling.
        writes = ("save", "use_suggested", "draft_player", "queue", "add_waiver", "drop", "accept", "propose",
                  "execute", "finalize", "commission", "claim", "set_", "submit", "delete", "rename", "activate")
        for name in REGISTRY.names():
            self.assertFalse(any(w in name for w in writes), name)

    def test_package_imports_no_storage_auth_billing_network_or_model_sdk(self) -> None:
        forbidden = ("suite_storage", "suite_auth", "suite_cloud_state", "suite_user_persistence", "baseball_billing",
                     "baseball_persistent_state", "draft_room_supabase", "fantasy_shared_league", "requests", "urllib",
                     "http", "socket", "anthropic", "openai", "subprocess", "draft_state", "applied_math_context",
                     "live_draft_pick_commit", "draft_actions", "fantasy_waiver_wire", "fantasy_trade_proposals",
                     # League state is read only through fantasy_league_peek / fantasy_read_api.
                     "fantasy_league_context", "resolved_fantasy_context", "fantasy_weekly_lineup",
                     "suggested_lineup", "fantasy_team_control", "fantasy_trade_legality", "draft_archive_state")
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
        from ami_assistant.context import LEAGUE_PAGES

        for page in (*PAGE_KEYS, "Draft Assistant Simulator", ""):
            session = RecordingSession(secret_session())
            build_ami_context(session, page)
            self.assertTrue(session.read <= allowed, (page, session.read - allowed))
        # League pages resolve the league through fantasy_league_peek (it reads what the page resolvers
        # read, on a copy); only the small league summary reaches the context.
        for page in LEAGUE_PAGES:
            ctx = build_ami_context(secret_session(), page)
            self.assertLessEqual(set(ctx.league), {"league_name", "my_team", "access_mode", "week_label", "week_status"})
            self.assertEqual(find_secrets(ctx.as_dict()), [])

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

class EntitlementGateTests(unittest.TestCase):
    """AMI applies the shared plan gate (CAPABILITY_FEATURES + entitlement_for_capability) to the tools that
    serve a plan capability, and only while the app enforces that feature."""

    DRAFT_TOOLS = {"get_draft_recommendations", "explain_draft_recommendation", "get_team_needs"}
    ARGS = {"explain_draft_recommendation": {"player": "Bobby Witt"}}

    def _enforce(self, *features):
        import baseball_monetization as bm

        return mock.patch.object(bm, "ENFORCED_FEATURES", frozenset(features))  # feature-level enforcement

    def test_tagged_tools_use_the_shared_capability_metadata(self) -> None:
        from baseball_monetization import CAPABILITY_FEATURES, FeatureId

        tagged = {s.name: s.plan_capability for s in REGISTRY.specs() if s.plan_capability}
        self.assertEqual(tagged, {"get_draft_recommendations": "draft_recommendations",
                                  "explain_draft_recommendation": "draft_recommendation_explanation",
                                  "get_team_needs": "draft_team_needs"})
        for cap in tagged.values():
            self.assertEqual(CAPABILITY_FEATURES[cap], FeatureId.ADVANCED_DRAFT_INTELLIGENCE)
        # Draft Lab and ML Predictions are plan capabilities too; AMI has no tool that serves them
        # (it declines projection questions and doesn't read Draft Lab results). A tool that ever reads
        # them must carry the matching tag, so its reuses must not name those sources untagged.
        for spec in REGISTRY.specs():
            sources = " ".join(spec.reuses).lower()
            if any(k in sources for k in ("ml_predict", "draft_lab", "draft lab", "next-season")):
                self.assertIn(spec.plan_capability, ("draft_lab_simulation", "ml_predictions"), spec.name)

    def test_nothing_changes_while_nothing_is_enforced(self) -> None:
        import baseball_monetization as bm

        self.assertEqual(bm.enforced_features(), frozenset())  # the app enforces no feature today
        for name in self.DRAFT_TOOLS:
            self.assertEqual(REGISTRY.call(name, self.ARGS.get(name, {}), session={}, entitlement=None).error_code,
                             codes.MISSING_DRAFT_CONTEXT)

    def test_enforced_feature_uses_the_same_gate_as_the_ui(self) -> None:
        from baseball_monetization import EntitlementSnapshot, FeatureId, Plan, SubscriptionStatus, can_use_feature

        free = EntitlementSnapshot(plan=Plan.FREE, ready=True, status=SubscriptionStatus.AUTHENTICATED_FREE)
        pro = EntitlementSnapshot(plan=Plan.PRO, ready=True, status=SubscriptionStatus.ACTIVE)
        loading = EntitlementSnapshot(ready=False, status=SubscriptionStatus.UNKNOWN)
        with self._enforce(FeatureId.ADVANCED_DRAFT_INTELLIGENCE):
            for name in self.DRAFT_TOOLS:
                args = self.ARGS.get(name, {})
                self.assertEqual(REGISTRY.call(name, args, session={}, entitlement=free).error_code, codes.NOT_ENTITLED)
                self.assertEqual(REGISTRY.call(name, args, session={}, entitlement=loading).error_code, codes.ENTITLEMENT_LOADING)
                self.assertEqual(REGISTRY.call(name, args, session={}, entitlement=None).error_code, codes.ENTITLEMENT_LOADING)
                # Pro passes the gate (and then needs a draft, as before).
                self.assertEqual(REGISTRY.call(name, args, session={}, entitlement=pro).error_code, codes.MISSING_DRAFT_CONTEXT)
            self.assertFalse(can_use_feature(free, FeatureId.ADVANCED_DRAFT_INTELLIGENCE))  # same answer as the UI's check
            # Untagged tools are never gated.
            self.assertTrue(REGISTRY.call("explain_metric", {"term": "ops"}, entitlement=free).ok)
            answer = ask("Who should I draft next?", session_state={}, active_page="Draft Assistant Simulator",
                         dataset=synthetic_dataset(), entitlement=free).answer
            self.assertIn("part of Pro", answer)
        for other in (FeatureId.ML_PREDICTIONS, FeatureId.DRAFT_LAB):  # other features enforced: draft tools stay open
            with self._enforce(other):
                self.assertEqual(REGISTRY.call("get_team_needs", {}, session={}, entitlement=free).error_code,
                                 codes.MISSING_DRAFT_CONTEXT)
                self.assertTrue(REGISTRY.call("explain_metric", {"term": "ops"}, entitlement=free).ok)
                # ML questions never reach a model-output tool, so nothing to gate: AMI declines them.
                ml = ask("Who will hit the most home runs next season?", session_state={}, dataset=synthetic_dataset(),
                         entitlement=free)
                self.assertIn("ML Predictions", ml.answer)
                self.assertEqual(ml.tools, [])
        # Page-level enforcement reaches the same gate (enforced_features() includes page features).
        import baseball_monetization as bm

        with mock.patch.object(bm, "ENFORCED_PAGE_FEATURES",
                               MappingProxyType({"Draft Assistant Simulator": FeatureId.ADVANCED_DRAFT_INTELLIGENCE})):
            self.assertEqual(REGISTRY.call("get_team_needs", {}, session={}, entitlement=free).error_code,
                             codes.NOT_ENTITLED)

    def test_ami_never_resolves_entitlements_itself(self) -> None:
        # Resolving may call the billing provider; AMI only uses the snapshot the host already has.
        for path in PKG.rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn("resolve_trusted_entitlement", src, path.name)
            self.assertNotIn("current_entitlement", src, path.name)


class HelpQuestionsAreReadOnlyTests(unittest.TestCase):
    def test_u2_u3_help_questions_leave_the_session_unchanged(self) -> None:
        import pickle

        session = secret_session()
        session["compare_players"] = ["Aaron Judge", "Juan Soto"]
        before = pickle.dumps({k: session[k] for k in sorted(session)})
        ds = synthetic_dataset()
        for page, q in (("Home", "What can I do on Home?"), ("Home", "How do I start a draft?"),
                        ("Home", "What's the difference between Draft Assistant and Draft Lab?"),
                        ("Home", "Where is the Comparison Tool?"), ("Comparison Tool", "What does Compare Players show me?"),
                        ("Valuation", "Where are the advanced filters?"),
                        ("Fantasy Lineup Assistant", "What are Commissioner Tools?"),
                        ("Fantasy Lineup Assistant", "What does Draft mean on my lineup?"),
                        ("Fantasy Lineup Assistant", "What does Creates roster issue mean?"),
                        ("Fantasy Lineup Assistant", "Use suggested lineup for me")):
            ask(q, session_state=session, active_page=page, dataset=ds, remember=False)
        self.assertEqual(pickle.dumps({k: session[k] for k in sorted(session)}), before)


if __name__ == "__main__":
    unittest.main()
