"""Paywall gate under the real app's widget ordering.

The production sidebar radio is keyed "main_sidebar_page" and is instantiated
BEFORE the page body, where the gate's buttons live. M3's original fixture used
a radio keyed "test_page", which hid that schedule_page() wrote the live widget
key and raised StreamlitAPIException. This fixture mirrors the real ordering and
consumes the schedule at the top of the run, like _consume_scheduled_navigation.
"""

import streamlit as st

from baseball_monetization import entitlement_for_page
from baseball_monetization_ui import current_entitlement, render_feature_gate, render_pricing_page

PAGES = ["Historical Explorer", "ML Predictions", "Draft Lab / Simulation", "Pricing & Upgrade"]

scheduled = st.session_state.pop("_navigate_to_page", None)
if scheduled in PAGES:
    st.session_state["main_sidebar_page"] = scheduled  # before the widget exists: allowed

page = st.sidebar.radio("Choose Page", PAGES, key="main_sidebar_page")
snapshot = current_entitlement(st.session_state, developer_mode=False, environ={})
if page == "Pricing & Upgrade":
    render_pricing_page(st, st.session_state, snapshot)
elif not entitlement_for_page(snapshot, page):
    render_feature_gate(st, st.session_state, page)
else:
    st.title(page)
