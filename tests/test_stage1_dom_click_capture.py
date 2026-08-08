"""Tests for frame-scoped DOM click capture helpers."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_dom_click_capture import _INSTALL_IN_DOC_JS  # noqa: PLC2701


def test_install_js_requires_player_scoped_rec_card_button() -> None:
    assert "ld-rec-card-meta" in _INSTALL_IN_DOC_JS
    assert "Add to Queue" in _INSTALL_IN_DOC_JS
    assert "pointerdown" in _INSTALL_IN_DOC_JS
    assert "__stage1DomClickCaptureLog" in _INSTALL_IN_DOC_JS


def test_install_js_supports_pause_mode() -> None:
    assert "Pause Draft" in _INSTALL_IN_DOC_JS
    assert "mode === 'pause'" in _INSTALL_IN_DOC_JS or "o.mode === 'pause'" in _INSTALL_IN_DOC_JS
