"""Streamlit adapter for Baseball pricing, paywalls, and local plan testing."""

from __future__ import annotations

from typing import Mapping, MutableMapping

from baseball_monetization import (
    PAGE_FEATURES,
    EntitlementSnapshot,
    Plan,
    default_entitlement,
    development_overrides_enabled,
    resolve_trusted_entitlement,
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
    return resolve_trusted_entitlement(session, environ=environ)


def remember_paywall_context(session: MutableMapping, page: str) -> None:
    """Remember navigation context only; never initialize or alter feature state."""
    if page in PAGE_FEATURES:
        session[RETURN_PAGE_KEY] = page


def pricing_return_page(session: MutableMapping, fallback: str = "Historical Explorer") -> str:
    page = str(session.get(RETURN_PAGE_KEY) or "").strip()
    return page if page in PAGE_FEATURES else fallback


def schedule_page(session: MutableMapping, page: str) -> None:
    """Queue a page change for the next run.

    Writes only the schedule key. The app applies it in
    _consume_scheduled_navigation() at the top of the next run, before the
    sidebar radio exists -- the same contract as streamlit_app.navigate_to_page.
    Writing "main_sidebar_page" here directly raised StreamlitAPIException in the
    real app: the paywall buttons render in the main area AFTER the sidebar radio
    keyed main_sidebar_page is instantiated, so both gate buttons died before
    st.rerun(). The isolated AppTest fixture never saw it because its radio is
    keyed "test_page".
    """
    session["_navigate_to_page"] = page
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
        st.caption("$14.99/month · secure checkout powered by Stripe")
    render_subscription_actions(st, session, snapshot, key_prefix="pricing")
    target = pricing_return_page(session)
    if st.button(f"Back to {target}", key="monetization_pricing_back"):
        schedule_page(session, target)
        st.rerun()


def render_subscription_actions(
    st,
    session: MutableMapping,
    snapshot: EntitlementSnapshot,
    *,
    key_prefix: str,
) -> None:
    """Render billing actions from trusted state; never mutate entitlement state."""
    st.info(
        f"Current plan: **{snapshot.entitlement.value.replace('_', ' ').title()}**"
    )
    if not snapshot.ready:
        st.info(
            "Checking your membership… Access will not be decided until the trusted "
            "account state is ready."
        )
        return
    if snapshot.grants_pro:
        st.success(
            f"Pro is active ({snapshot.status.value.replace('_', ' ')})."
        )
    elif snapshot.plan is Plan.PRO:
        st.warning(
            f"Pro is not active ({snapshot.status.value.replace('_', ' ')})."
        )
    try:
        from baseball_billing_client import billing_ui_state

        billing = billing_ui_state(session)
    except Exception:
        billing = {"action": "disabled", "message": "Billing is currently unavailable."}
    if not snapshot.grants_pro:
        if billing.get("action") == "signin":
            st.caption(str(billing.get("message") or "Sign in to upgrade."))
        elif billing.get("action") != "checkout":
            st.caption(str(billing.get("message") or "Checkout is not available."))
        if billing.get("action") == "checkout" and st.button(
            "Upgrade to Pro — $14.99/month",
            type="primary",
            key=f"{key_prefix}_billing_checkout_start",
            use_container_width=True,
        ):
            try:
                from baseball_billing_client import create_checkout_url

                st.session_state[f"_{key_prefix}_billing_checkout_url"] = (
                    create_checkout_url(session)
                )
            except Exception as exc:
                st.error(str(exc))
        checkout_url = str(
            st.session_state.pop(f"_{key_prefix}_billing_checkout_url", "") or ""
        )
        if checkout_url:
            st.link_button(
                "Continue to secure Stripe Checkout",
                checkout_url,
                type="primary",
                key=f"{key_prefix}_billing_checkout_link",
                use_container_width=True,
            )
    if snapshot.has_stripe_customer and snapshot.status.value != "development":
        if st.button(
            "Manage Subscription",
            key=f"{key_prefix}_billing_portal_start",
            use_container_width=True,
        ):
            try:
                from baseball_billing_client import create_portal_url

                st.session_state[f"_{key_prefix}_billing_portal_url"] = (
                    create_portal_url(session)
                )
            except Exception as exc:
                st.error(str(exc))
        portal_url = str(
            st.session_state.pop(f"_{key_prefix}_billing_portal_url", "") or ""
        )
        if portal_url:
            st.link_button(
                "Continue to secure Stripe billing portal",
                portal_url,
                key=f"{key_prefix}_billing_portal_link",
                use_container_width=True,
            )


def render_account_subscription(st, session: MutableMapping) -> None:
    """Account & Workspace subscription block for an authenticated user."""
    st.markdown("**Subscription**")
    snapshot = current_entitlement(session)
    render_subscription_actions(st, session, snapshot, key_prefix="account")


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
