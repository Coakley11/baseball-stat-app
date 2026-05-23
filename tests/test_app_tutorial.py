"""Tutorial module — static content and prefs."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import app_tutorial as tut


def test_tutorial_steps_cover_main_flow():
    steps = tut.get_tutorial_steps()
    assert len(steps) >= 10
    titles = {s["title"] for s in steps}
    assert "Historical Explorer" in titles
    assert "Live Draft Room" in titles
    assert "Key metrics glossary" in titles


def test_hide_button_prefs_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        prefs_path = Path(tmp) / "prefs.json"
        with mock.patch.object(tut, "_PREFS_PATH", prefs_path):
            tut._save_prefs({"hide_button": True})
            loaded = tut._load_prefs()
            assert loaded.get("hide_button") is True
            assert json.loads(prefs_path.read_text())["hide_button"] is True
