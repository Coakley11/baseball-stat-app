"""Tutorial module — fan-focused content and prefs."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import app_tutorial as tut


def test_tutorial_steps_fan_flow():
    steps = tut.get_tutorial_steps()
    assert len(steps) == 16
    titles = [s["title"] for s in steps]
    assert titles[0] == "Welcome"
    assert titles[-1] == "You are all set"
    assert "How to use filters" in titles
    assert "Comparison Tool" in titles
    assert "Trends and Valuation" in titles
    assert "Sending filters to another page" in titles
    assert "Tracked Players" in titles


def test_no_developer_jargon_in_copy():
    steps = tut.get_tutorial_steps()
    blob = json.dumps(steps).lower()
    banned = (
        "session state",
        "pipeline",
        "helper function",
        "architecture",
        "unified pool",
        "lahman",
        "widget",
        "debug",
    )
    for term in banned:
        assert term not in blob, f"developer term found: {term}"


def test_hide_button_prefs_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        prefs_path = Path(tmp) / "prefs.json"
        with mock.patch.object(tut, "_PREFS_PATH", prefs_path):
            tut._save_prefs({"hide_button": True})
            loaded = tut._load_prefs()
            assert loaded.get("hide_button") is True
