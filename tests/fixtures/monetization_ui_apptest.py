"""Rendered Free/Pro monetization fixture for Streamlit AppTest."""

import os

import streamlit as st

from baseball_monetization import entitlement_for_page
from baseball_monetization_ui import (
    current_entitlement,
    remember_paywall_context,
    render_development_plan_control,
    render_feature_gate,
    render_pricing_page,
)

os.environ["BASEBALL_ENTITLEMENT_DEV_CONTROLS"] = "1"
os.environ["BASEBALL_ENTITLEMENT_RUNTIME"] = "test"
render_development_plan_control(st, enabled=True)
snapshot = current_entitlement(st.session_state, developer_mode=True)
if st.session_state.get("_navigate_to_page"):
    st.session_state["test_page"] = st.session_state.pop("_navigate_to_page")
page = st.radio(
    "Test page",
    ["Historical Explorer", "ML Predictions", "Live Draft Room", "Pricing & Upgrade"],
    key="test_page",
)
if page == "Pricing & Upgrade":
    render_pricing_page(st, st.session_state, snapshot)
elif not entitlement_for_page(snapshot, page):
    remember_paywall_context(st.session_state, page)
    render_feature_gate(st, st.session_state, page)
else:
    st.title(page)
    st.success(f"ALLOWED:{snapshot.plan.value}:{page}")
