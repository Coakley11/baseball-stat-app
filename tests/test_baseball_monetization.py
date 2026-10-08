from copy import deepcopy

from baseball_monetization import (
    FEATURE_REGISTRY,
    PAGE_FEATURES,
    EntitlementSnapshot,
    FeatureId,
    Plan,
    can_use_feature,
    default_entitlement,
    development_overrides_enabled,
    development_entitlement,
    entitlement_for_page,
)
from baseball_monetization_ui import (
    PRICING_PAGE,
    RETURN_PAGE_KEY,
    current_entitlement,
    pricing_return_page,
    remember_paywall_context,
    schedule_page,
)


def test_default_entitlement_is_free():
    assert default_entitlement() == EntitlementSnapshot(Plan.FREE, True, "default")


def test_development_override_simulates_pro_only_when_enabled():
    session = {"_dev_monetization_plan": "pro"}
    assert current_entitlement(session, developer_mode=False).plan is Plan.FREE
    assert current_entitlement(session, developer_mode=True).plan is Plan.FREE
    env = {
        "BASEBALL_ENTITLEMENT_DEV_CONTROLS": "1",
        "BASEBALL_ENTITLEMENT_RUNTIME": "test",
    }
    assert development_overrides_enabled(env)
    assert current_entitlement(session, developer_mode=True, environ=env) == development_entitlement(Plan.PRO)


def test_development_override_cannot_be_enabled_in_production():
    env = {
        "BASEBALL_ENTITLEMENT_DEV_CONTROLS": "1",
        "BASEBALL_ENTITLEMENT_RUNTIME": "production",
    }
    session = {"_dev_monetization_plan": "pro"}
    assert not development_overrides_enabled(env)
    assert current_entitlement(session, developer_mode=True, environ=env).plan is Plan.FREE


def test_free_blocked_and_pro_allowed_for_representative_features():
    for feature in (FeatureId.ML_PREDICTIONS, FeatureId.DRAFT_LAB):
        assert not can_use_feature(default_entitlement(), feature)
        assert can_use_feature(development_entitlement("pro"), feature)


def test_unknown_and_unready_fail_closed():
    assert not can_use_feature(EntitlementSnapshot(Plan.PRO, False, "loading"), FeatureId.ML_PREDICTIONS)
    assert not can_use_feature(default_entitlement(), "not_registered")


def test_registry_is_centralized_and_every_page_gate_is_registered():
    assert FEATURE_REGISTRY
    assert all(feature in FEATURE_REGISTRY for feature in PAGE_FEATURES.values())
    assert entitlement_for_page(default_entitlement(), "Historical Explorer")


def test_entitlement_checks_do_not_mutate_business_or_session_state():
    business = {"draft_queue": ["Player A"], "room": {"status": "active"}}
    before = deepcopy(business)
    assert entitlement_for_page(default_entitlement(), "ML Predictions")
    assert business == before


def test_page_gates_are_not_enforced_until_product_split_is_approved():
    from baseball_monetization import ENFORCED_PAGE_FEATURES

    assert not ENFORCED_PAGE_FEATURES
    assert entitlement_for_page(default_entitlement(), "ML Predictions")


def test_pricing_navigation_and_safe_return_preserve_context():
    session = {"ml_sort_by": "Predicted OPS"}
    remember_paywall_context(session, "ML Predictions")
    schedule_page(session, PRICING_PAGE)
    assert session[RETURN_PAGE_KEY] == "ML Predictions"
    assert pricing_return_page(session) == "ML Predictions"
    assert session["ml_sort_by"] == "Predicted OPS"
    assert session["_navigate_to_page"] == PRICING_PAGE


def test_invalid_return_context_falls_back_safely():
    assert pricing_return_page({RETURN_PAGE_KEY: "Live Draft Room"}) == "Historical Explorer"
