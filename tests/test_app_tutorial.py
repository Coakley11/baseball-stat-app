"""Tutorial — fan-first onboarding copy and structure."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import app_tutorial as tut


def test_tutorial_has_action_first_steps():
    steps = tut.get_tutorial_steps()
    assert len(steps) >= 6
    ids = [s["id"] for s in steps]
    assert ids == ["welcome", "historical", "draft_prep", "live_draft", "fantasy_mgmt", "finish"]
    hist = next(s for s in steps if s["id"] == "historical")
    assert "Hank Aaron" in hist["headline"] or "Willie Mays" in hist["headline"]
    assert any(s.get("tries") for s in steps if s["kind"] == "normal")
    assert any("Aaron" in t or "mock" in t.lower() or "steals" in t.lower() for s in steps for t in s.get("tries", []))


def test_tutorial_covers_current_workflows():
    blob = json.dumps(tut.get_tutorial_steps()).lower()
    assert "live draft" in blob
    assert "waiver" in blob
    assert "trade center" in blob
    assert "draft lab" in blob
    assert "hall of fame" in blob
    assert "draft simulation test mode" not in blob
    assert "research mode" not in blob


def test_metrics_mostly_in_advanced():
    steps = tut.get_tutorial_steps()
    main_blob = json.dumps(
        [{k: v for k, v in s.items() if k != "advanced"} for s in steps]
    ).lower()
    assert "normalized" not in main_blob
    assert "unified" not in main_blob
    assert "session state" not in main_blob


def test_hide_button_prefs_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        prefs_path = Path(tmp) / "prefs.json"
        with mock.patch.object(tut, "_PREFS_PATH", prefs_path):
            tut._save_prefs({"hide_button": True})
            assert tut._load_prefs().get("hide_button") is True
