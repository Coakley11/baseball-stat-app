"""Streamlit adapter for Baseball pricing, paywalls, and local plan testing."""

from __future__ import annotations

from typing import Mapping, MutableMapping

from baseball_monetization import (
    PAGE_FEATURES,
    EntitlementSnapshot,
    Plan,
    default_entitlement,
    development_overrides_enabled,
    development_entitlement,
    feature_definition,
)

PRICING_PAGE = "Pricing & Upgrade"
RETURN_PAGE_KEY = "monetization_return_page"
DEV_PLAN_KEY = "_dev_monetization_plan"


def current_entitlement(
    session: MutableMapping,
    *,
    developer_mode: bool = False,
    environ: Mapping[str, str] | None = None,
) -> EntitlementSnapshot:
    if developer_mode and development_overrides_enabled(environ):
        return development_entitlement(session.get(DEV_PLAN_KEY, Plan.FREE.value))
    return default_entitlement()


def remember_paywall_context(session: MutableMapping, page: str) -> None:
    """Remember navigation context only; never initialize or alter feature state."""
    if page in PAGE_FEATURES:
        session[RETURN_PAGE_KEY] = page


def pricing_return_page(session: MutableMapping, fallback: str = "Historical Explorer") -> str:
    page = str(session.get(RETURN_PAGE_KEY) or "").strip()
    return page if page in PAGE_FEATURES else fallback


def schedule_page(session: MutableMapping, page: str) -> None:
    session["_navigate_to_page"] = page
    session["main_sidebar_page"] = page
    session["_suite_page_user_nav"] = True


def render_development_plan_control(st, *, enabled: bool) -> None:
    if not enabled or not development_overrides_enabled():
        return
    st.sidebar.selectbox(
        "Dev entitlement",
        [Plan.FREE.value, Plan.PRO.value],
        key=DEV_PLAN_KEY,
        format_func=lambda value: f"{str(value).title()} (local simulation)",
        help="Developer-only session simulation. It cannot grant a production entitlement.",
    )


def render_pricing_page(st, session: MutableMapping, snapshot: EntitlementSnapshot) -> None:
    st.title("Baseball Free & Pro")
    st.caption("Choose the level that fits how deeply you analyze and manage baseball.")
    free_col, pro_col = st.columns(2)
    with free_col:
        st.subheader("Free")
        st.markdown(
            "Explore player history, career totals, rankings, comparisons, trends, "
            "valuation, fantasy sleepers, standard draft tools, Live Draft, saved drafts, "
            "standings, lineups, and waiver workflows."
        )
        st.caption("$0 · useful core analytics and fantasy workflows")
    with pro_col:
        st.subheader("Pro")
        st.markdown(
            "Add ML Predictions and Draft Lab today, with advanced draft intelligence, "
            "expanded workspaces, and premium exports planned for later phases."
        )
        st.caption("Price to be announced · billing is not active in M1")
    st.info(f"Current plan: **{snapshot.plan.value.title()}**")
    if snapshot.plan is Plan.PRO:
        st.success("Pro simulation is active. Premium tools are available.")
    else:
        st.warning("Checkout is not available yet. This page previews the planned Pro offering.")
    target = pricing_return_page(session)
    if st.button(f"Back to {target}", key="monetization_pricing_back"):
        schedule_page(session, target)
        st.rerun()


def render_feature_gate(st, session: MutableMapping, page: str) -> None:
    definition = feature_definition(PAGE_FEATURES[page])
    st.title(f"{definition.name} is a Pro feature")
    st.write(definition.description)
    st.info("Your page context is preserved. The premium tool has not been initialized or changed.")
    left, right = st.columns(2)
    with left:
        if st.button("View Pricing & Upgrade", type="primary", key="monetization_gate_pricing"):
            schedule_page(session, PRICING_PAGE)
            st.rerun()
    with right:
        if st.button("Back to Historical Explorer", key="monetization_gate_back"):
            schedule_page(session, "Historical Explorer")
            st.rerun()
