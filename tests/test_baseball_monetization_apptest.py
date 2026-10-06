from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "monetization_ui_apptest.py"


def _text(elements):
    return " ".join(str(getattr(element, "value", "")) for element in elements)


def test_rendered_free_gate_pricing_and_back_navigation():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(FIXTURE), default_timeout=30).run()
    assert not at.exception
    assert "ALLOWED:free:Historical Explorer" in _text(at.success)

    at.radio(key="test_page").set_value("ML Predictions").run()
    assert not at.exception
    assert "ML Predictions is a Pro feature" in _text(at.title)
    assert "ml_lookback" not in at.session_state

    at.button(key="monetization_gate_pricing").click().run()
    assert not at.exception
    assert "Baseball Free & Pro" in _text(at.title)
    assert "Current plan: **Free**" in _text(at.info)

    at.button(key="monetization_pricing_back").click().run()
    assert not at.exception
    assert "ML Predictions is a Pro feature" in _text(at.title)


def test_rendered_pro_refresh_and_navigation_consistency():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(FIXTURE), default_timeout=30).run()
    at.selectbox(key="_dev_monetization_plan").set_value("pro").run()
    at.radio(key="test_page").set_value("ML Predictions").run()
    assert not at.exception
    assert "ALLOWED:pro:ML Predictions" in _text(at.success)

    at.run()  # refresh/rerun
    assert "ALLOWED:pro:ML Predictions" in _text(at.success)
    at.radio(key="test_page").set_value("Historical Explorer").run()
    at.radio(key="test_page").set_value("ML Predictions").run()
    assert "ALLOWED:pro:ML Predictions" in _text(at.success)


def test_live_draft_is_not_monetized_in_rendered_free_flow():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(FIXTURE), default_timeout=30).run()
    at.radio(key="test_page").set_value("Live Draft Room").run()
    assert not at.exception
    assert "ALLOWED:free:Live Draft Room" in _text(at.success)
    assert "monetization_return_page" not in at.session_state
