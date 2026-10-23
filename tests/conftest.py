"""Pytest hooks to reduce cross-test module pollution in combined suites."""

from __future__ import annotations

import os
import sys

import pytest

# Subprocesses that tests start inherit this, so none of them can reach a real sibling Command Center store.
os.environ["SUITE_STORAGE_ISOLATED"] = "1"


@pytest.fixture(autouse=True)
def _isolate_partial_streamlit_app_import() -> None:
    """Drop a broken partial streamlit_app import between tests."""
    yield
    mod = sys.modules.get("streamlit_app")
    if mod is not None and not hasattr(mod, "live_draft_recommendations"):
        sys.modules.pop("streamlit_app", None)
