"""Provider-independent Baseball Free/Pro entitlements.

This module deliberately has no Streamlit, Stripe, Supabase, or draft-state
dependency.  A later billing adapter can project server-authoritative account
state into :class:`EntitlementSnapshot` without changing product pages.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from types import MappingProxyType
from typing import Mapping


class Plan(str, Enum):
    FREE = "free"
    PRO = "pro"

class SubscriptionStatus(str, Enum):
    ANONYMOUS="anonymous"
    AUTHENTICATED_FREE="authenticated_free"
    TRIALING="trialing"
    ACTIVE="active"
    CANCELED_PERIOD_END="canceled_period_end"
    PAST_DUE="past_due"
    EXPIRED="expired"
    UNKNOWN="unknown"
    DEVELOPMENT="development"


class FeatureId(str, Enum):
    ML_PREDICTIONS = "ml_predictions"
    DRAFT_LAB = "draft_lab"
    ADVANCED_DRAFT_INTELLIGENCE = "advanced_draft_intelligence"
    PREMIUM_EXPORTS = "premium_exports"
    EXPANDED_WORKSPACES = "expanded_workspaces"


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: FeatureId
    name: str
    description: str
    required_plan: Plan


@dataclass(frozen=True)
class EntitlementSnapshot:
    plan: Plan = Plan.FREE
    ready: bool = True
    source: str = "default"
    status: SubscriptionStatus = SubscriptionStatus.ANONYMOUS
    user_id: str = ""
    current_period_end: str = ""

    @property
    def grants_pro(self) -> bool:
        return self.ready and self.plan is Plan.PRO and self.status in {
            SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE,
            SubscriptionStatus.CANCELED_PERIOD_END, SubscriptionStatus.DEVELOPMENT,
        }


FEATURE_REGISTRY: Mapping[FeatureId, FeatureDefinition] = MappingProxyType(
    {
        FeatureId.ML_PREDICTIONS: FeatureDefinition(
            FeatureId.ML_PREDICTIONS,
            "ML Predictions",
            "Model-driven projections, tuning, and similar-player forecasts.",
            Plan.PRO,
        ),
        FeatureId.DRAFT_LAB: FeatureDefinition(
            FeatureId.DRAFT_LAB,
            "Draft Lab",
            "Advanced draft simulations and scenario analysis.",
            Plan.PRO,
        ),
        FeatureId.ADVANCED_DRAFT_INTELLIGENCE: FeatureDefinition(
            FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
            "Advanced draft intelligence",
            "Deeper recommendations, team-needs analysis, and roster optimization.",
            Plan.PRO,
        ),
        FeatureId.PREMIUM_EXPORTS: FeatureDefinition(
            FeatureId.PREMIUM_EXPORTS,
            "Premium exports",
            "Expanded and presentation-ready exports.",
            Plan.PRO,
        ),
        FeatureId.EXPANDED_WORKSPACES: FeatureDefinition(
            FeatureId.EXPANDED_WORKSPACES,
            "Expanded saved workspaces",
            "Additional persistent leagues and analysis workspaces.",
            Plan.PRO,
        ),
    }
)

PAGE_FEATURES: Mapping[str, FeatureId] = MappingProxyType(
    {
        "ML Predictions": FeatureId.ML_PREDICTIONS,
        "Draft Lab / Simulation": FeatureId.DRAFT_LAB,
    }
)

DEV_CONTROLS_ENV = "BASEBALL_ENTITLEMENT_DEV_CONTROLS"
DEV_RUNTIME_ENV = "BASEBALL_ENTITLEMENT_RUNTIME"


def development_overrides_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Require a server-owned opt-in and an explicitly non-production runtime."""
    env = os.environ if environ is None else environ
    enabled = str(env.get(DEV_CONTROLS_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    runtime = str(env.get(DEV_RUNTIME_ENV) or "").strip().lower()
    return enabled and runtime in {"local", "test"}


def feature_definition(feature_id: FeatureId) -> FeatureDefinition:
    return FEATURE_REGISTRY[FeatureId(feature_id)]


def can_use_feature(snapshot: EntitlementSnapshot, feature_id: FeatureId) -> bool:
    """Fail closed for unknown/unready state; never mutate caller state."""
    try:
        definition = feature_definition(feature_id)
    except (KeyError, ValueError, TypeError):
        return False
    if not snapshot.ready:
        return False
    if definition.required_plan is Plan.FREE:
        return True
    return snapshot.grants_pro


def entitlement_for_page(snapshot: EntitlementSnapshot, page: str) -> bool:
    feature_id = PAGE_FEATURES.get(str(page))
    return True if feature_id is None else can_use_feature(snapshot, feature_id)


def default_entitlement() -> EntitlementSnapshot:
    return EntitlementSnapshot()


def development_entitlement(plan: Plan | str) -> EntitlementSnapshot:
    """Explicit local/test projection; callers must enforce developer-only UI."""
    try:
        selected = Plan(str(getattr(plan, "value", plan)).lower())
    except ValueError:
        selected = Plan.FREE
    return EntitlementSnapshot(plan=selected, ready=True, source="development_override", status=SubscriptionStatus.DEVELOPMENT)

def authenticated_subject(session: Mapping) -> tuple[str,bool,str]:
    """Return only Supabase-validated identity; workspace/email are never authority."""
    try:
        from suite_auth import AUTH_TOKENS_KEY, AUTH_USER_ID_KEY, is_auth_enabled, is_authenticated
        if is_auth_enabled() and is_authenticated(dict(session)):
            tokens=session.get(AUTH_TOKENS_KEY) or {}
            return str(session.get(AUTH_USER_ID_KEY) or "").strip(), True, str(tokens.get("access_token") or "") if isinstance(tokens,Mapping) else ""
    except Exception: pass
    return "",False,""

def resolve_trusted_entitlement(session: Mapping, *, provider=None, environ: Mapping[str,str]|None=None) -> EntitlementSnapshot:
    """Resolve billing projection. Loading/provider failure is unready, never false Free."""
    env=os.environ if environ is None else environ
    user_id,authenticated,token=authenticated_subject(session)
    if not authenticated:
        return EntitlementSnapshot(status=SubscriptionStatus.ANONYMOUS)
    try:
        from baseball_billing_config import BillingConfig, RolloutMode
        config=BillingConfig.from_environ(env)
        if config.rollout in {RolloutMode.OFF,RolloutMode.PREVIEW}:
            return EntitlementSnapshot(status=SubscriptionStatus.AUTHENTICATED_FREE,user_id=user_id,source="billing_disabled")
        if provider is None:
            if not token: return EntitlementSnapshot(ready=False,source="identity_loading",status=SubscriptionStatus.UNKNOWN,user_id=user_id)
            from baseball_billing_supabase import SupabaseEntitlementProvider
            provider=SupabaseEntitlementProvider(config,token)
        value=provider.entitlement_for_user(user_id)
        return value if value is not None else EntitlementSnapshot(status=SubscriptionStatus.AUTHENTICATED_FREE,user_id=user_id,source="billing_database")
    except Exception:
        return EntitlementSnapshot(ready=False,source="billing_unavailable",status=SubscriptionStatus.UNKNOWN,user_id=user_id)
