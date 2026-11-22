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


class EntitlementLevel(str, Enum):
    FREE = "free"
    PRO_ACTIVE = "pro_active"
    PRO_INACTIVE = "pro_inactive"


class SubscriptionStatus(str, Enum):
    ANONYMOUS="anonymous"
    AUTHENTICATED_FREE="authenticated_free"
    TRIALING="trialing"
    ACTIVE="active"
    CANCELED_PERIOD_END="canceled_period_end"
    PAST_DUE="past_due"
    INACTIVE="inactive"
    CANCELED="canceled"
    EXPIRED="expired"
    UNKNOWN="unknown"
    DEVELOPMENT="development"


class FeatureId(str, Enum):
    ML_PREDICTIONS = "ml_predictions"
    DRAFT_LAB = "draft_lab"
    ADVANCED_DRAFT_INTELLIGENCE = "advanced_draft_intelligence"
    PREMIUM_EXPORTS = "premium_exports"
    EXPANDED_WORKSPACES = "expanded_workspaces"
    DRAFT_STRATEGIES = "draft_strategies"
    ADVANCED_ANALYTICS = "advanced_analytics"
    LINEUP_INTELLIGENCE = "lineup_intelligence"
    TRADE_INTELLIGENCE = "trade_intelligence"
    WAIVER_INTELLIGENCE = "waiver_intelligence"
    AMI_STRATEGY_COACHING = "ami_strategy_coaching"


class FeatureStatus(str, Enum):
    """Implementation status, shown to users. Only AVAILABLE items are presented as included."""

    AVAILABLE = "available"  # built and working in this build
    PREVIEW = "preview"  # built, still being refined; shown with a preview label
    PLANNED = "planned"  # not built yet; shown only as "coming later", never as included


class Category(str, Enum):
    """Upgrade-page benefit groups, in display order."""

    DRAFT = "Smarter Draft Decisions"
    FORECASTING = "Advanced Player Forecasting"
    ANALYTICS = "Advanced Baseball Analytics"
    LINEUP = "Lineup Intelligence"
    TRADE_WAIVER = "Trade and Waiver Strategy"
    AMI = "AMI Strategy Coaching"
    LATER = "Planned"


@dataclass(frozen=True)
class FeatureItem:
    """One concrete thing a feature includes, with its own implementation status."""

    text: str
    status: FeatureStatus = FeatureStatus.AVAILABLE


@dataclass(frozen=True)
class FeatureDefinition:
    """The single definition of a plan feature: the Upgrade page, Pro labels and the gates read it.

    ``status`` is the feature's overall implementation status; ``includes`` lists the concrete
    parts, each with its own status, so a feature can be available while some parts are planned.
    ``free_keeps`` says what Free users keep in the same area. ``surfaces`` names the pages, Player
    Actions and AMI where the feature appears. The shared backend capabilities come from
    ``CAPABILITY_FEATURES`` (see :func:`capabilities_for`); ``requires`` names other features it
    builds on. Enforcement is never stored here: it comes from :func:`enforced_features`.
    """

    feature_id: FeatureId
    name: str
    description: str
    required_plan: Plan
    category: Category = Category.LATER
    benefit: str = ""
    status: FeatureStatus = FeatureStatus.PLANNED
    includes: tuple[FeatureItem, ...] = ()
    free_keeps: str = ""
    surfaces: tuple[str, ...] = ()
    requires: tuple[FeatureId, ...] = ()

    @property
    def available_items(self) -> tuple[FeatureItem, ...]:
        return tuple(i for i in self.includes if i.status is not FeatureStatus.PLANNED)

    @property
    def planned_items(self) -> tuple[FeatureItem, ...]:
        return tuple(i for i in self.includes if i.status is FeatureStatus.PLANNED)


@dataclass(frozen=True)
class EntitlementSnapshot:
    plan: Plan = Plan.FREE
    ready: bool = True
    source: str = "default"
    status: SubscriptionStatus = SubscriptionStatus.ANONYMOUS
    user_id: str = ""
    current_period_end: str = ""
    has_stripe_customer: bool = False

    @property
    def grants_pro(self) -> bool:
        return self.ready and self.plan is Plan.PRO and self.status in {
            SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE,
            SubscriptionStatus.CANCELED_PERIOD_END, SubscriptionStatus.DEVELOPMENT,
        }

    @property
    def entitlement(self) -> EntitlementLevel:
        if self.grants_pro:
            return EntitlementLevel.PRO_ACTIVE
        if self.plan is Plan.PRO:
            return EntitlementLevel.PRO_INACTIVE
        return EntitlementLevel.FREE


_A, _P = FeatureStatus.AVAILABLE, FeatureStatus.PLANNED

# The one Free/Pro feature catalogue. Proposed classification (docs/BASEBALL_FREE_PRO_MATRIX.md),
# awaiting owner approval; nothing here is enforced (see ENFORCED_* below). Only describe what the
# app really does: anything not built is FeatureStatus.PLANNED and is never shown as included.
FEATURE_REGISTRY: Mapping[FeatureId, FeatureDefinition] = MappingProxyType(
    {
        FeatureId.DRAFT_STRATEGIES: FeatureDefinition(
            FeatureId.DRAFT_STRATEGIES,
            "Saved Draft Strategies",
            "Named, reusable draft plans with their own rankings, pins, notes and research, loadable into any draft.",
            Plan.PRO,
            category=Category.DRAFT,
            benefit="Keep several named draft plans, each with its own ranking and research, and use any of them in a draft.",
            status=_A,
            includes=(
                FeatureItem("Named strategies, each with its own player ranking and queue"),
                FeatureItem("Pinned players, strategy notes and research"),
                FeatureItem("Load a strategy into any draft and save your changes back"),
                FeatureItem("Copy between a strategy and your Global Queue, with confirmation"),
            ),
            free_keeps="Your personal Global Queue and the in-draft approaches (Balanced, Best available, Value, Scarcity, Roster-aware).",
            surfaces=("Draft Strategy", "Draft rooms: starting plan, load and save back", "Ask AMI"),
        ),
        FeatureId.DRAFT_LAB: FeatureDefinition(
            FeatureId.DRAFT_LAB,
            "Draft Lab",
            "Computer-drafted league simulations with pick-by-pick verdicts and team analysis.",
            Plan.PRO,
            category=Category.DRAFT,
            benefit="Rehearse a draft: the computer drafts a full league, then grades every pick and team.",
            status=_A,
            includes=(
                FeatureItem("Computer-drafted 4-team league simulations"),
                FeatureItem("Pick-by-pick verdicts with the reason for each pick"),
                FeatureItem("Team score breakdown, roster needs, and best and questionable picks"),
                FeatureItem("Full CSV and Excel export of each simulation"),
                FeatureItem("Simulate a draft with one of your saved strategies", _P),
            ),
            free_keeps="The Draft Room Simulator, Live Drafts and the Draft Assistant.",
            surfaces=("Draft Lab / Simulation", "Analyze Draft after a Live draft"),
        ),
        FeatureId.ADVANCED_DRAFT_INTELLIGENCE: FeatureDefinition(
            FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
            "Advanced draft intelligence",
            "Tunable draft recommendations, extra ranking modes, player insight and post-draft grades.",
            Plan.PRO,
            category=Category.DRAFT,
            benefit="Tune recommendations to your league and see the model's reasoning.",
            status=_A,
            includes=(
                FeatureItem("Category priorities and positions to prioritize"),
                FeatureItem("Seven more ways to rank recommendations, including model value and scarcity"),
                FeatureItem("Selected Player Insight and the positional scarcity heatmap"),
                FeatureItem("Advanced columns and post-draft grades in the Draft Room Simulator"),
            ),
            free_keeps="Team needs, recommendation cards in Roster Fit order, roster tables and projections.",
            surfaces=("Draft Assistant", "Draft Room Simulator: Rosters & grades", "Ask AMI (outside live rooms)"),
        ),
        FeatureId.ML_PREDICTIONS: FeatureDefinition(
            FeatureId.ML_PREDICTIONS,
            "Advanced ML Predictions",
            "The full prediction list, projection tuning and model diagnostics.",
            Plan.PRO,
            category=Category.FORECASTING,
            benefit="Go beyond the top predictions: tune the model and check how accurate it is.",
            status=_A,
            includes=(
                FeatureItem("The full prediction list for your filters"),
                FeatureItem("Projection tuning: style, regression, age and similar-player weights"),
                FeatureItem("Model accuracy check, age curve and feature importance"),
                FeatureItem("Prediction ranges (how uncertain each forecast is)", _P),
            ),
            free_keeps="The top 25 predictions for your filters, with the model's summary.",
            surfaces=("ML Predictions",),
        ),
        FeatureId.ADVANCED_ANALYTICS: FeatureDefinition(
            FeatureId.ADVANCED_ANALYTICS,
            "Advanced analytics",
            "Regression trendlines, relationship scans, significance tests and custom scoring weights.",
            Plan.PRO,
            category=Category.ANALYTICS,
            benefit="Model how stats relate, test whether differences are real, and build your own scores.",
            status=_A,
            includes=(
                FeatureItem("Regression trendlines (polynomial, log, exponential, best fit) with fit statistics"),
                FeatureItem("Relationship Finder, with a check against the following season"),
                FeatureItem("Significance tests and Advanced Trend Intelligence"),
                FeatureItem("Custom leaderboard and valuation weights"),
                FeatureItem("Curve-adjusted sleepers and custom points scoring"),
                FeatureItem("Multi-variable regression and valuation scenarios", _P),
            ),
            free_keeps="Every research page, scatterplots with any X and Y and a straight trendline, comparisons, trends, valuation and sleepers lists.",
            surfaces=("Historical Explorer", "Career Totals", "Leaderboards", "Compare Players", "Trend Value",
                      "Valuation", "Fantasy Sleepers & Busts"),
        ),
        FeatureId.LINEUP_INTELLIGENCE: FeatureDefinition(
            FeatureId.LINEUP_INTELLIGENCE,
            "Lineup intelligence",
            "Suggested lineups, start/sit recommendations and lineup diagnosis.",
            Plan.PRO,
            category=Category.LINEUP,
            benefit="Let the app suggest your best lineup and explain who to start or sit.",
            status=_A,
            includes=(
                FeatureItem("Use Suggested Lineup (position-aware optimization)"),
                FeatureItem("Recommended starters and a bench, sit and watch list"),
                FeatureItem("Lineup diagnosis with ways to improve"),
                FeatureItem("Matchup-aware and category-targeted start/sit", _P),
            ),
            free_keeps="Viewing, editing and saving your own lineups.",
            surfaces=("Lineup & Trades: Lineup Management", "Ask AMI"),
        ),
        FeatureId.TRADE_INTELLIGENCE: FeatureDefinition(
            FeatureId.TRADE_INTELLIGENCE,
            "Trade intelligence",
            "Trade ideas with fairness scores and exact-trade analysis by category.",
            Plan.PRO,
            category=Category.TRADE_WAIVER,
            benefit="Find trades worth making and see how a trade changes each category.",
            status=_A,
            includes=(
                FeatureItem("Trade ideas: players to target and players to move, with a fairness score"),
                FeatureItem("Exact trade analysis with the impact on each category"),
                FeatureItem("Projected standings impact of a trade", _P),
            ),
            free_keeps="Proposing, accepting, declining, countering and cancelling trades, with roster legality checks.",
            surfaces=("Lineup & Trades: Trade Center", "Trade offers: Analyze This Trade", "Ask AMI"),
        ),
        FeatureId.WAIVER_INTELLIGENCE: FeatureDefinition(
            FeatureId.WAIVER_INTELLIGENCE,
            "Personalized waiver recommendations",
            "Waiver pickups weighted by your roster's positional needs and weak categories.",
            Plan.PRO,
            category=Category.TRADE_WAIVER,
            benefit="Pickups chosen for your roster's needs, not just the best numbers.",
            status=_A,
            includes=(
                FeatureItem("Recommendations weighted by your positional needs and weak categories"),
                FeatureItem("An upgrade check against your weakest starter"),
                FeatureItem("Rest-of-season projections and a replacement-level baseline", _P),
            ),
            free_keeps="The waiver pool, standard recommendations, the projected impact of a move and every add and drop.",
            surfaces=("Waiver Wire", "Lineup & Trades: Actionable Recommendations", "Ask AMI"),
        ),
        FeatureId.AMI_STRATEGY_COACHING: FeatureDefinition(
            FeatureId.AMI_STRATEGY_COACHING,
            "AMI strategy coaching",
            "Ask AMI about your own saved Draft Strategies.",
            Plan.PRO,
            category=Category.AMI,
            benefit="Advice that considers your own saved Draft Strategies, not just general baseball information.",
            status=_A,
            includes=(
                FeatureItem("Ask AMI to list, open and compare your strategies with your Global Queue"),
                FeatureItem("Research answers that show where players rank in your selected strategy", _P),
                FeatureItem("AMI suggests notes and findings to save, only when you confirm", _P),
            ),
            free_keeps="Ask AMI for page help, stats, comparisons, trends, standings and lineup facts.",
            surfaces=("Ask AMI",),
            requires=(FeatureId.DRAFT_STRATEGIES,),
        ),
        FeatureId.PREMIUM_EXPORTS: FeatureDefinition(
            FeatureId.PREMIUM_EXPORTS,
            "Premium exports",
            "Expanded and presentation-ready exports.",
            Plan.PRO,
            status=_P,
        ),
        FeatureId.EXPANDED_WORKSPACES: FeatureDefinition(
            FeatureId.EXPANDED_WORKSPACES,
            "Expanded saved workspaces",
            "Additional persistent leagues and analysis workspaces.",
            Plan.PRO,
            status=_P,
        ),
    }
)

PAGE_FEATURES: Mapping[str, FeatureId] = MappingProxyType(
    {
        "ML Predictions": FeatureId.ML_PREDICTIONS,
        "Draft Lab / Simulation": FeatureId.DRAFT_LAB,
    }
)

# The reusable candidates stay registered, but no product page is enforced during
# billing acceptance. The Free-vs-Pro product split will be selected separately.
ENFORCED_PAGE_FEATURES: Mapping[str, FeatureId] = MappingProxyType({})

# Features enforced wherever they appear (not tied to one page), e.g. advanced draft
# intelligence inside the Draft Assistant and any assistant tool that serves it. Empty: nothing
# is enforced during billing acceptance. The UI and assistant tools read the same set.
ENFORCED_FEATURES: frozenset[FeatureId] = frozenset()

# Which shared capabilities belong to a plan feature, so every surface that serves one (page,
# assistant tool, API) can apply the same gate. Capabilities not listed are free.
CAPABILITY_FEATURES: Mapping[str, FeatureId] = MappingProxyType(
    {
        "draft_recommendations": FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
        "draft_recommendation_explanation": FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
        "draft_team_needs": FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
        "draft_lab_simulation": FeatureId.DRAFT_LAB,
        "ml_predictions": FeatureId.ML_PREDICTIONS,
        "draft_strategy_library": FeatureId.DRAFT_STRATEGIES,
        # Proposed capability names for the gates in docs/BASEBALL_FREE_PRO_MATRIX.md. Registered so
        # every surface can name the same check; nothing calls or enforces them yet.
        "advanced_analytics": FeatureId.ADVANCED_ANALYTICS,
        "lineup_suggestions": FeatureId.LINEUP_INTELLIGENCE,
        "lineup_diagnosis": FeatureId.LINEUP_INTELLIGENCE,
        "trade_ideas": FeatureId.TRADE_INTELLIGENCE,
        "trade_analysis": FeatureId.TRADE_INTELLIGENCE,
        "waiver_personalized_adds": FeatureId.WAIVER_INTELLIGENCE,
    }
)


def capabilities_for(feature_id: FeatureId) -> tuple[str, ...]:
    """The shared backend capabilities that require this feature (every entry point checks these)."""
    return tuple(sorted(cap for cap, fid in CAPABILITY_FEATURES.items() if fid is FeatureId(feature_id)))


def is_enforced(feature_id: FeatureId) -> bool:
    """Whether the app restricts this feature right now (from the ENFORCED_* sets, never the registry)."""
    return FeatureId(feature_id) in enforced_features()


def catalog() -> tuple[FeatureDefinition, ...]:
    """Every Pro feature for presentation, in category order then registry order."""
    order = list(Category)
    pro = [d for d in FEATURE_REGISTRY.values() if d.required_plan is Plan.PRO]
    return tuple(sorted(pro, key=lambda d: order.index(d.category)))


def features_in(category: Category, *, include_planned: bool = False) -> tuple[FeatureDefinition, ...]:
    """Features in one Upgrade-page category; planned-only features are left out unless asked for."""
    return tuple(d for d in catalog() if d.category is category
                 and (include_planned or d.status is not FeatureStatus.PLANNED))

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
    feature_id = ENFORCED_PAGE_FEATURES.get(str(page))
    return True if feature_id is None else can_use_feature(snapshot, feature_id)


def enforced_features() -> frozenset[FeatureId]:
    """Every feature the app enforces right now: page features plus feature-level ones."""
    return frozenset(ENFORCED_PAGE_FEATURES.values()) | ENFORCED_FEATURES


def feature_for_capability(capability: str) -> FeatureId | None:
    return CAPABILITY_FEATURES.get(str(capability or ""))


def entitlement_for_capability(snapshot: EntitlementSnapshot, capability: str) -> bool:
    """The gate for one shared capability: free or not enforced → allowed; otherwise the same
    ``can_use_feature`` the page gate uses (fails closed while the snapshot isn't ready)."""
    feature_id = feature_for_capability(capability)
    if feature_id is None or feature_id not in enforced_features():
        return True
    return can_use_feature(snapshot, feature_id)


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
        from suite_auth import AUTH_TOKENS_KEY, AUTH_USER_ID_KEY, auth_session_complete, is_auth_enabled
        if is_auth_enabled() and auth_session_complete(dict(session)):
            tokens=session.get(AUTH_TOKENS_KEY) or {}
            user_id = str(session.get(AUTH_USER_ID_KEY) or "").strip()
            token = str(tokens.get("access_token") or "").strip() if isinstance(tokens,Mapping) else ""
            if user_id and token:
                return user_id, True, token
    except Exception: pass
    return "",False,""

def resolve_trusted_entitlement(session: Mapping, *, provider=None, environ: Mapping[str,str]|None=None) -> EntitlementSnapshot:
    """Resolve billing projection. Loading/provider failure is unready, never false Free."""
    env=os.environ if environ is None else environ
    user_id,authenticated,token=authenticated_subject(session)
    if not authenticated:
        return EntitlementSnapshot(status=SubscriptionStatus.ANONYMOUS)
    try:
        from baseball_billing_config import RolloutMode, load_client_billing_config
        config=load_client_billing_config(environ if environ is not None else None)
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
