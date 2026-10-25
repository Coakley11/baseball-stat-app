"""Pytest hooks to reduce cross-test module pollution in combined suites."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate_partial_streamlit_app_import() -> None:
    """Drop a broken partial streamlit_app import between tests."""
    yield
    mod = sys.modules.get("streamlit_app")
    if mod is not None and not hasattr(mod, "live_draft_recommendations"):
        sys.modules.pop("streamlit_app", None)
