"""The paywall's own navigation buttons must work under the real widget order."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "monetization_gate_real_order_apptest.py"


def _titles(at):
    return " | ".join(t.value for t in at.title)


def _start(page):
    at = AppTest.from_file(str(FIXTURE), default_timeout=60)
    at.session_state["main_sidebar_page"] = page
    at.run()
    assert not at.exception, at.exception
    return at


def test_gate_view_pricing_button_reaches_pricing():
    at = _start("ML Predictions")
    assert "ML Predictions is a Pro feature" in _titles(at)
    at.button(key="monetization_gate_pricing").click().run()
    assert not at.exception, at.exception
    assert "Baseball Free & Pro" in _titles(at)


def test_gate_back_button_returns_to_historical_explorer():
    at = _start("Draft Lab / Simulation")
    assert "is a Pro feature" in _titles(at)
    at.button(key="monetization_gate_back").click().run()
    assert not at.exception, at.exception
    assert "Historical Explorer" in _titles(at)
    assert "is a Pro feature" not in _titles(at)


def test_schedule_page_never_writes_the_live_radio_key():
    from baseball_monetization_ui import schedule_page

    session = {}
    schedule_page(session, "Pricing & Upgrade")
    assert session["_navigate_to_page"] == "Pricing & Upgrade"
    assert "main_sidebar_page" not in session
