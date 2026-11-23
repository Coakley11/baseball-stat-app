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

# The one Free/Pro feature catalogue. Classification per docs/BASEBALL_FREE_PRO_MATRIX.md (owner
# decisions 2026-11-22); nothing here is enforced (see ENFORCED_* below). Only describe what the
# app really does: anything not built is FeatureStatus.PLANNED and is never shown as included.
FEATURE_REGISTRY: Mapping[FeatureId, FeatureDefinition] = MappingProxyType(
    {
        FeatureId.DRAFT_STRATEGIES: FeatureDefinition(
            FeatureId.DRAFT_STRATEGIES,
            "Saved Draft Strategies",
            "Named, reusable draft plans with their own rankings, pins, notes and research, loadable into any draft.",
            Plan.PRO,
            category=Category.DRAFT,
            benefit="Plan different drafts your way: keep several named strategies, each with its own ranked list, "
                    "must-have players and notes, and bring any of them into a draft.",
            status=_A,
            includes=(
                FeatureItem("Several named strategies, each with its own ranked player list"),
                FeatureItem("Pin must-have players and keep notes and research on each one"),
                FeatureItem("Bring a strategy into any draft, then save what you changed back to it"),
                FeatureItem("Move players between a strategy and your Global Queue, only when you confirm"),
            ),
            free_keeps="Your Global Queue (one personal ranked list) and the in-draft ranking styles: Balanced, "
                       "Best available, Value, Positional scarcity and Roster-aware.",
            surfaces=("Draft Strategy", "Draft rooms: starting plan, load and save back", "Ask AMI"),
        ),
        FeatureId.DRAFT_LAB: FeatureDefinition(
            FeatureId.DRAFT_LAB,
            "Draft Lab",
            "Computer-drafted league simulations and graded drafts, including your own completed Live drafts.",
            Plan.PRO,
            category=Category.DRAFT,
            benefit="Practise before draft day: the computer drafts a whole league and grades every pick and team. "
                    "It can grade your real Live drafts the same way.",
            status=_A,
            includes=(
                FeatureItem("A full mock draft where the computer picks for all four teams"),
                FeatureItem("A verdict and the reason for every pick"),
                FeatureItem("Team scores, remaining roster needs, and the best and most questionable picks"),
                FeatureItem("The same grading for your own completed Live drafts"),
                FeatureItem("The whole simulation as a CSV or Excel download"),
                FeatureItem("A mock draft run with one of your saved strategies", _P),
            ),
            free_keeps="The Draft Room Simulator, Live Drafts, and viewing, saving and exporting your completed drafts.",
            surfaces=("Draft Lab / Simulation", "Live Draft: Analyze Draft (grading)"),
        ),
        FeatureId.ADVANCED_DRAFT_INTELLIGENCE: FeatureDefinition(
            FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
            "Advanced draft intelligence",
            "Tunable draft recommendations, extra ranking modes, player insight, pick simulation and draft grades.",
            Plan.PRO,
            category=Category.DRAFT,
            benefit="Recommendations tuned to your league, with the reasoning behind each pick.",
            status=_A,
            includes=(
                FeatureItem("Tell the Draft Assistant which categories and positions matter most to you"),
                FeatureItem("Sort recommendations seven more ways, such as model value or positional scarcity"),
                FeatureItem("A plain-language insight on any player you are considering, and a scarcity heat map"),
                FeatureItem("Simulate Draft Pick: see how taking a player would change your roster"),
                FeatureItem("Draft grades and advanced value columns in the Draft Room Simulator"),
            ),
            free_keeps="Your team's needs and recommendation cards ranked by roster fit, plus roster tables and projections.",
            surfaces=("Draft Assistant", "Draft Room Simulator: Rosters & grades", "Player Actions: Simulate Draft Pick",
                      "Ask AMI (outside live rooms)"),
        ),
        FeatureId.ML_PREDICTIONS: FeatureDefinition(
            FeatureId.ML_PREDICTIONS,
            "Advanced ML Predictions",
            "The full projection list, model tuning and model diagnostics.",
            Plan.PRO,
            category=Category.FORECASTING,
            benefit="See every projection, adjust how the model forecasts, and check how accurate it has been.",
            status=_A,
            includes=(
                FeatureItem("Every projection for your filters, not just the top 25"),
                FeatureItem("Adjust the model: how much it leans on past seasons, age and similar players"),
                FeatureItem("Check the model's accuracy, how age changes production, and which stats drive each forecast"),
                FeatureItem("A likely range for each projection, not just one number", _P),
            ),
            free_keeps="The top 25 projections for your filters and sort order, with a plain summary of each.",
            surfaces=("ML Predictions",),
        ),
        FeatureId.ADVANCED_ANALYTICS: FeatureDefinition(
            FeatureId.ADVANCED_ANALYTICS,
            "Advanced analytics",
            "Curved trend lines, relationship scans, significance tests and custom scoring weights.",
            Plan.PRO,
            category=Category.ANALYTICS,
            benefit="Go beyond the charts: find which stats really move together, test whether differences are "
                    "real, and build your own rankings.",
            status=_A,
            includes=(
                FeatureItem("Curved trend lines on any chart, with a score for how well they fit"),
                FeatureItem("Relationship Finder: scan for stats that move together, then check them against the next season"),
                FeatureItem("Significance tests and Advanced Trend Intelligence on comparisons and trends"),
                FeatureItem("Your own weights for leaderboard and valuation scores"),
                FeatureItem("Sleepers adjusted for the market curve, and your own points scoring"),
                FeatureItem("Models that combine several stats at once, and what-if valuation scenarios", _P),
            ),
            free_keeps="Every research page, charts of any two stats with a straight trend line, comparisons, trends, "
                       "valuation and the sleepers and busts lists.",
            surfaces=("Historical Explorer", "Career Totals", "Leaderboards", "Compare Players", "Trend Value",
                      "Valuation", "Fantasy Sleepers & Busts"),
        ),
        FeatureId.LINEUP_INTELLIGENCE: FeatureDefinition(
            FeatureId.LINEUP_INTELLIGENCE,
            "Lineup intelligence",
            "Suggested lineups, start/sit recommendations and lineup diagnosis.",
            Plan.PRO,
            category=Category.LINEUP,
            benefit="Get a suggested best lineup each week and a clear start-or-sit call for every player.",
            status=_A,
            includes=(
                FeatureItem("A one-click suggested lineup that fills every position"),
                FeatureItem("Who to start, who to sit and who to watch, with the reason"),
                FeatureItem("A lineup check-up with specific ways to improve your team"),
                FeatureItem("Start/sit advice based on this week's matchups and your weakest categories", _P),
            ),
            free_keeps="Seeing, editing and saving your own lineup every week.",
            surfaces=("Lineup & Trades: Lineup Management", "Ask AMI"),
        ),
        FeatureId.TRADE_INTELLIGENCE: FeatureDefinition(
            FeatureId.TRADE_INTELLIGENCE,
            "Trade intelligence",
            "Trade ideas with fairness scores and exact-trade analysis by category.",
            Plan.PRO,
            category=Category.TRADE_WAIVER,
            benefit="Find trades that help your team and see exactly what each one does to your categories.",
            status=_A,
            includes=(
                FeatureItem("Trade ideas: who to target and who to offer, with a fairness score"),
                FeatureItem("Analyze any trade: how it changes each of your categories"),
                FeatureItem("How a trade would move you in the standings", _P),
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
            benefit="Pickups chosen for your team's needs, not just the best numbers on the wire.",
            status=_A,
            includes=(
                FeatureItem("Pickups ranked by the positions and categories your team needs most"),
                FeatureItem("A check of whether each pickup beats your weakest starter"),
                FeatureItem("Rest-of-season projections for pickups and a replacement-level comparison", _P),
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
            benefit="Ask AMI about your own draft plans and get answers that use your saved strategies, "
                    "not just general baseball facts.",
            status=_A,
            includes=(
                FeatureItem("Ask AMI what is in your strategies and how one compares with your Global Queue"),
                FeatureItem("See where players rank in your strategy right inside research answers", _P),
                FeatureItem("AMI suggests notes to save to your strategy, saved only when you confirm", _P),
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

# E0 switch. A feature whose gates are built and tested is added to READY_FEATURES (one approved
# feature at a time). It is enforced only while the server-side switch is "on":
#   BASEBALL_ENTITLEMENT_ENFORCEMENT = off (default) | preview | on
# Streamlit exposes top-level secrets as environment variables, so the switch can live in secrets.
# "preview" shows Pro labels and never locks; any unknown value counts as "off".
ENFORCEMENT_ENV = "BASEBALL_ENTITLEMENT_ENFORCEMENT"
# E1 (built, not active): Saved Draft Strategies and AMI strategy coaching share the
# draft_strategy_library capability (store, page, in-draft plans, AMI A1/A2 tools).
READY_FEATURES: frozenset[FeatureId] = frozenset({FeatureId.DRAFT_STRATEGIES})


class EnforcementMode(str, Enum):
    OFF = "off"
    PREVIEW = "preview"
    ON = "on"


def enforcement_mode(environ: Mapping[str, str] | None = None) -> EnforcementMode:
    env = os.environ if environ is None else environ
    try:
        return EnforcementMode(str(env.get(ENFORCEMENT_ENV) or "off").strip().lower())
    except ValueError:
        return EnforcementMode.OFF


class ProFeatureRequired(Exception):
    """A typed refusal from :func:`require`: the operation needs Pro (or membership is still loading).
    It carries the feature so the UI can show the lock component with its benefit text."""

    def __init__(self, feature_id: "FeatureId", *, loading: bool = False) -> None:
        self.feature_id = feature_id
        self.loading = loading
        name = FEATURE_REGISTRY[feature_id].name if feature_id in FEATURE_REGISTRY else str(feature_id)
        super().__init__("Checking your membership…" if loading else f"{name} is included with Baseball Explorer Pro.")

# Which shared capabilities belong to a plan feature, so every surface that serves one (page,
# assistant tool, API) can apply the same gate. Capabilities not listed are free.
CAPABILITY_FEATURES: Mapping[str, FeatureId] = MappingProxyType(
    {
        "draft_recommendations": FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
        "draft_recommendation_explanation": FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
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
        "draft_pick_simulation": FeatureId.ADVANCED_DRAFT_INTELLIGENCE,
        "draft_lab_live_analysis": FeatureId.DRAFT_LAB,
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


def enforced_features(environ: Mapping[str, str] | None = None) -> frozenset[FeatureId]:
    """Every feature the app enforces right now: page features, feature-level ones, and the
    READY_FEATURES while the enforcement switch is "on"."""
    ready = READY_FEATURES if enforcement_mode(environ) is EnforcementMode.ON else frozenset()
    return frozenset(ENFORCED_PAGE_FEATURES.values()) | ENFORCED_FEATURES | ready


def feature_for_capability(capability: str) -> FeatureId | None:
    return CAPABILITY_FEATURES.get(str(capability or ""))


def entitlement_for_capability(snapshot: EntitlementSnapshot, capability: str) -> bool:
    """The gate for one shared capability: free or not enforced → allowed; otherwise the same
    ``can_use_feature`` the page gate uses (fails closed while the snapshot isn't ready)."""
    feature_id = feature_for_capability(capability)
    if feature_id is None or feature_id not in enforced_features():
        return True
    return can_use_feature(snapshot, feature_id)


def allows(snapshot: EntitlementSnapshot, capability: str) -> bool:
    """May this snapshot use the capability right now? (Free, not enforced, or entitled Pro.)"""
    return entitlement_for_capability(snapshot, capability)


def require(snapshot: EntitlementSnapshot, capability: str) -> None:
    """Gate an operation (kind A): raise :class:`ProFeatureRequired` before computing anything."""
    if not entitlement_for_capability(snapshot, capability):
        raise ProFeatureRequired(feature_for_capability(capability), loading=not snapshot.ready)


def effective(snapshot: EntitlementSnapshot, capability: str, value, default):
    """Gate a saved setting (kind B): the user's value when allowed, otherwise the Free default.
    The saved value itself is never changed, so it comes back on upgrade."""
    return value if entitlement_for_capability(snapshot, capability) else default


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
