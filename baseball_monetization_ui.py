"""Streamlit adapter for Baseball pricing, paywalls, Pro indicators, and local plan testing.

Everything a user reads about Free and Pro comes from ``baseball_monetization.FEATURE_REGISTRY``
(names, benefits, what each feature includes and whether it is built) and from billing
configuration (the price label). Nothing here grants or refuses access: indicators only describe
the state :func:`pro_state` derives from the trusted snapshot and the ``ENFORCED_*`` sets.
"""

from __future__ import annotations

import html
import os

import action_icons as _icons

from typing import Mapping, MutableMapping

from baseball_monetization import (
    PAGE_FEATURES,
    Category,
    EntitlementSnapshot,
    FeatureId,
    FeatureStatus,
    Plan,
    catalog,
    default_entitlement,
    development_overrides_enabled,
    enforced_features,
    features_in,
    is_enforced,
    resolve_trusted_entitlement,
    development_entitlement,
    feature_definition,
)

PRICING_PAGE = "Pricing & Upgrade"
RETURN_PAGE_KEY = "monetization_return_page"
DEV_PLAN_KEY = "_dev_monetization_plan"

PRICING_TITLE = "Unlock Baseball Explorer Pro"
PRICING_CAPTION = "Choose the level that fits how deeply you analyze and manage baseball."  # = AMI page help purpose
LOCKED_SENTENCE = "This feature is included with Baseball Explorer Pro."
PRICE_FALLBACK = "Price shown at secure checkout"
PRO_BADGE = ":orange-badge[✨ PRO]"
PREVIEW_NOTE = "open to everyone while billing is in preview"
PRICE_LABEL_ENV = "BASEBALL_PRO_PRICE_LABEL"  # same setting as fix/billing-portal-completion
PRICE_LABEL_MAX = 40
RUN_SNAPSHOT_KEY = "_monetization_run_snapshot"  # this run's trusted snapshot, set by streamlit_app


def pro_price_label(environ: Mapping[str, str] | None = None) -> str:
    """The display price from billing configuration (amount and period), or "" when none is set.

    Display only: Checkout always charges the server's configured Stripe price and shows its real
    amount. With no configured label the app shows no price rather than a possibly wrong one.
    Read from ``BASEBALL_PRO_PRICE_LABEL`` or ``[baseball_billing] pro_price_label`` (secrets).
    """
    source = os.environ if environ is None else environ
    label = str(source.get(PRICE_LABEL_ENV) or "").strip()
    if not label and environ is None:
        try:
            import streamlit as st  # noqa: WPS433

            billing = st.secrets.get("baseball_billing")
            label = str((billing or {}).get("pro_price_label") or "").strip()
        except Exception:
            label = ""
    return label[:PRICE_LABEL_MAX]


def pro_state(snapshot: EntitlementSnapshot | None, feature_id: FeatureId) -> str:
    """How a Pro feature presents for this account right now.

    ``included``: the account has active Pro. ``preview``: the feature is not enforced, so it is
    open to everyone (today: every feature). ``checking``: enforced, membership still loading.
    ``locked``: enforced and the account does not have Pro.
    """
    snap = snapshot or default_entitlement()
    if snap.grants_pro:
        return "included"
    if not is_enforced(feature_id):
        return "preview"
    if not snap.ready:
        return "checking"
    return "locked"


def pro_note_text(feature_id: FeatureId, state: str, label: str = "") -> str:
    name = label or feature_definition(feature_id).name
    if state == "included":
        return f"{PRO_BADGE} {name} · included in your plan"
    if state == "checking":
        return f"{PRO_BADGE} {name} · checking your membership…"
    if state == "locked":
        return f"{PRO_BADGE} {name}"
    return f"{PRO_BADGE} {name} · {PREVIEW_NOTE}"


def render_pro_note(
    st,
    session: MutableMapping,
    feature_id: FeatureId | str,
    *,
    key: str,
    label: str = "",
    snapshot: EntitlementSnapshot | None = None,
) -> bool:
    """One restrained Pro indicator next to a Pro control. Returns whether the control may run.

    Preview and included show a single caption line. Locked shows :func:`render_locked_feature`
    (what it does + Upgrade) instead of the control; the caller must not compute the Pro result
    when this returns False. The real check stays in the operation (the capability gate).
    Uses this run's snapshot (``RUN_SNAPSHOT_KEY``, set by the app) unless one is passed.
    """
    feature_id = FeatureId(feature_id)  # a typo fails loudly in tests
    try:
        snap = snapshot if snapshot is not None else session.get(RUN_SNAPSHOT_KEY)
        if not isinstance(snap, EntitlementSnapshot):
            snap = current_entitlement(session)
        state = pro_state(snap, feature_id)
        if state == "locked":
            render_locked_feature(st, session, feature_id, key=key)
            return False
        st.caption(pro_note_text(feature_id, state, label))
        return state != "checking"
    except Exception:
        # A label must never break the page it sits on. Fail closed only for an enforced feature.
        return not is_enforced(feature_id)


def render_locked_feature(st, session: MutableMapping, feature_id: FeatureId, *, key: str) -> None:
    """Discoverable lock: the feature's name, the standard sentence, what it does, and Upgrade.
    Shows no Pro result and no subscriber data."""
    definition = feature_definition(feature_id)
    with st.container(border=True):
        st.markdown(f"{PRO_BADGE} **{definition.name}**")
        st.write(LOCKED_SENTENCE)
        st.caption(definition.benefit or definition.description)
        if st.button("See Pro plans", key=f"{key}__pro_upgrade", icon=_icons.UPGRADE, type="primary"):
            schedule_page(session, PRICING_PAGE)
            st.rerun()


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


# Upgrade-page look per benefit group: icon, accent (>= 4.5:1 on white), tint, border.
_CATEGORY_STYLE: dict[Category, tuple[str, str, str, str]] = {
    Category.DRAFT: ("📝", "#b45309", "#fdf3e7", "#f3d3ad"),
    Category.FORECASTING: ("🤖", "#0f766e", "#e8f6f4", "#bfe5df"),
    Category.ANALYTICS: ("📈", "#1f5fa8", "#edf4fc", "#c9dcf2"),
    Category.LINEUP: ("📋", "#2e7d4f", "#ebf6ef", "#c3e3cf"),
    Category.TRADE_WAIVER: ("🔄", "#be123c", "#fdf0f2", "#f5c9d1"),
    Category.AMI: ("💬", "#6d28d9", "#f3effd", "#d9ccf6"),
}

_FREE_INCLUDES = (
    "Every season since 1871: Historical Explorer, Career Totals and Leaderboards",
    "Player search, profiles, side-by-side comparisons and charts",
    "Trend Value, Valuation and the Sleepers & Busts lists",
    "The top 25 ML projections for your filters",
    "Live Drafts, the Draft Room Simulator and Draft Assistant recommendations",
    "Your Global Queue: one personal ranked list for every draft",
    "Setting lineups, making trades, waiver pickups and league standings",
    "Ask AMI for help with any page, stat or player",
)

_PRICING_CSS = """<style>
.bxp-hero{border-radius:16px;padding:18px 20px;margin:4px 0 14px;color:#fff;
  background:linear-gradient(135deg,#0f2747 0%,#1f4f86 60%,#6d28d9 100%);}
.bxp-hero p{margin:0 0 6px;font-size:1.02rem;line-height:1.45;color:#f1f5f9;}
.bxp-price{display:inline-block;margin-top:6px;padding:4px 12px;border-radius:999px;
  background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.35);font-weight:700;}
.bxp-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:6px 0 16px;}
.bxp-card{border-radius:14px;padding:14px 16px;border:1px solid var(--bxp-border);background:var(--bxp-tint);}
.bxp-card h4{margin:0 0 8px;font-size:1.02rem;color:var(--bxp-accent);}
.bxp-feat{margin:8px 0 0;}
.bxp-feat b{color:#0f172a;}
.bxp-feat .bxp-benefit{display:block;color:#334155;font-size:.92rem;margin:2px 0 4px;}
.bxp-feat ul{margin:2px 0 0 1.1rem;padding:0;}
.bxp-feat li{font-size:.9rem;color:#1e293b;margin:1px 0;}
.bxp-chip{display:inline-block;font-size:.72rem;font-weight:700;padding:1px 8px;border-radius:999px;
  background:#e2e8f0;color:#334155;margin-left:4px;vertical-align:middle;}
.bxp-table{width:100%;border-collapse:collapse;margin:4px 0 14px;font-size:.92rem;}
.bxp-table th{text-align:left;background:#f1f5f9;color:#0f172a;padding:8px;border-bottom:2px solid #cbd5e1;}
.bxp-table td{vertical-align:top;padding:8px;border-bottom:1px solid #e2e8f0;color:#1e293b;}
.bxp-table td.bxp-area{font-weight:700;white-space:nowrap;}
@media (max-width:640px){
  .bxp-table thead{display:none;}
  .bxp-table tr{display:block;border:1px solid #e2e8f0;border-radius:10px;margin:0 0 10px;padding:4px 0;}
  .bxp-table td{display:block;border:none;padding:4px 10px;}
  .bxp-table td[data-label]::before{content:attr(data-label);display:block;font-size:.72rem;
    font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#64748b;}
}
</style>"""


def _esc(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def pricing_cards_html() -> str:
    """Benefit groups with the features they include. Planned parts are marked "Coming later";
    planned-only features are left out (they appear in the separate planned list)."""
    cards = []
    for category, (icon, accent, tint, border) in _CATEGORY_STYLE.items():
        feats = features_in(category)
        if not feats:
            continue
        body = []
        for d in feats:
            items = "".join(f"<li>{_esc(i.text)}</li>" for i in d.available_items)
            items += "".join(f"<li>{_esc(i.text)} <span class='bxp-chip'>Coming later</span></li>"
                             for i in d.planned_items)
            preview = " <span class='bxp-chip'>Preview</span>" if d.status is FeatureStatus.PREVIEW else ""
            body.append(f"<div class='bxp-feat'><b>{_esc(d.name)}</b>{preview}"
                        f"<span class='bxp-benefit'>{_esc(d.benefit)}</span><ul>{items}</ul></div>")
        cards.append(f"<div class='bxp-card' style='--bxp-accent:{accent};--bxp-tint:{tint};--bxp-border:{border}'>"
                     f"<h4>{icon} {_esc(category.value)}</h4>{''.join(body)}</div>")
    return "<div class='bxp-grid'>" + "".join(cards) + "</div>"


def free_card_html() -> str:
    """What every account can use, free: the same card style as the Pro groups, in green."""
    items = "".join(f"<li>{_esc(t)}</li>" for t in _FREE_INCLUDES)
    return ("<div class='bxp-card' style='--bxp-accent:#2e7d4f;--bxp-tint:#ebf6ef;--bxp-border:#c3e3cf;margin:6px 0 12px'>"
            "<h4>✅ Free for everyone</h4><div class='bxp-feat'><ul>" + items + "</ul></div></div>")


def comparison_table_html() -> str:
    """Free vs Pro, one row per Pro feature: what Free keeps in that area and what Pro adds."""
    rows = []
    for d in catalog():
        if d.status is FeatureStatus.PLANNED:
            continue
        adds = "; ".join(i.text for i in d.available_items) or d.description
        rows.append(f"<tr><td class='bxp-area' data-label='Area'>{_esc(d.name)}</td>"
                    f"<td data-label='Free'>{_esc(d.free_keeps)}</td>"
                    f"<td data-label='Pro adds'>{_esc(adds)}</td></tr>")
    return ("<table class='bxp-table'><thead><tr><th>Area</th><th>Free</th><th>Pro adds</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table>")


def planned_items() -> list[str]:
    """Everything listed as planned in the registry: never sold as included."""
    out: list[str] = []
    for d in catalog():
        if d.status is FeatureStatus.PLANNED:
            out.append(d.name)
        else:
            out.extend(i.text for i in d.planned_items)
    return out


def render_pricing_page(st, session: MutableMapping, snapshot: EntitlementSnapshot) -> None:
    label = pro_price_label()
    st.markdown(_PRICING_CSS, unsafe_allow_html=True)
    st.title(PRICING_TITLE)
    st.caption(PRICING_CAPTION)
    st.markdown(
        "<div class='bxp-hero'><p>Baseball Explorer stays free for research, drafting and running your "
        "league. <b>Pro</b> adds advanced analytics, forecasting and strategy tools for serious fantasy "
        "managers.</p>"
        f"<span class='bxp-price'>{_esc(label or PRICE_FALLBACK)}</span></div>",
        unsafe_allow_html=True,
    )
    if not enforced_features():
        st.info("Billing is in preview: every Pro feature below is open to all accounts for now. "
                "Pro tools carry a Pro label in the app.", icon="ℹ️")
    render_subscription_actions(st, session, snapshot, key_prefix="pricing")

    st.subheader("What Pro adds")
    st.markdown(pricing_cards_html(), unsafe_allow_html=True)

    st.subheader("Free vs Pro")
    st.caption("Free stays a complete app. Pro adds the advanced layer in each area.")
    st.markdown(free_card_html(), unsafe_allow_html=True)
    st.markdown(comparison_table_html(), unsafe_allow_html=True)

    later = planned_items()
    if later:
        with st.expander("Planned for Pro — not included yet", icon="🛠️"):
            st.caption("These are being built. They are not part of Pro until they are released.")
            st.markdown("\n".join(f"- {item}" for item in later))

    with st.expander("Billing, renewal and cancellation", icon="💳", expanded=False):
        st.markdown(
            f"- **Price and billing period:** {label or 'shown on the secure Stripe Checkout page before you pay'}."
            " Checkout always shows the exact amount and how often you are billed.\n"
            "- **When Pro starts:** as soon as Stripe confirms your payment.\n"
            "- **Managing your subscription:** Account & Workspace → Subscription → **Manage Subscription** "
            "opens the secure Stripe billing portal (payment method, invoices, cancellation).\n"
            "- **Cancelling:** cancel any time in the billing portal. Pro stays active until the end of the "
            "period you have paid for, then your account returns to Free.\n"
            "- **If a renewal payment fails:** Pro pauses until the payment succeeds. Manage Subscription "
            "stays available so you can update your card.\n"
            "- **Going back to Free:** nothing is deleted. Your saved strategies, notes and settings are kept "
            "and are there again if you upgrade.\n"
            "- **Live drafts:** a plan change never interrupts a draft in progress."
        )

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
        _label = pro_price_label()
        if billing.get("action") == "checkout" and st.button(
            f"Upgrade to Pro — {_label}" if _label else "Upgrade to Pro",
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
            icon=_icons.SUBSCRIPTION,
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
        if st.button("View Pricing & Upgrade", type="primary", key="monetization_gate_pricing", icon=_icons.UPGRADE):
            schedule_page(session, PRICING_PAGE)
            st.rerun()
    with right:
        if st.button("Back to Historical Explorer", key="monetization_gate_back"):
            schedule_page(session, "Historical Explorer")
            st.rerun()
