"""Tutorial — fan-first onboarding copy and structure."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import app_tutorial as tut


def test_tutorial_has_action_first_steps():
    steps = tut.get_tutorial_steps()
    assert len(steps) >= 15
    hist = next(s for s in steps if s["id"] == "historical")
    assert hist["steps"][0].startswith("Open")
    assert any("Try" in t or "try" in t.lower() for s in steps for t in s.get("tries", []))


def test_metrics_mostly_in_advanced():
    steps = tut.get_tutorial_steps()
    main_blob = json.dumps(
        [{k: v for k, v in s.items() if k != "advanced"} for s in steps]
    ).lower()
    assert "normalized" not in main_blob
    assert "unified" not in main_blob
    assert "session state" not in main_blob
    trends = next(s for s in steps if s["id"] == "trends")
    assert trends.get("advanced")


def test_hide_button_prefs_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        prefs_path = Path(tmp) / "prefs.json"
        with mock.patch.object(tut, "_PREFS_PATH", prefs_path):
            tut._save_prefs({"hide_button": True})
            assert tut._load_prefs().get("hide_button") is True
