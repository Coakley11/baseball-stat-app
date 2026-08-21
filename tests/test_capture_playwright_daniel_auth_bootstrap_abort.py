"""Browser-free tests: Context A capture bootstrap abort reporting.

Proves catchable Playwright/bootstrap exceptions persist phase=bootstrap_abort
with non-empty failure (070a20d7 reporting gap). NO network/browser.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import capture_playwright_daniel_auth_once as cap  # noqa: E402
from playwright_auth_capture_diag import CaptureTraceCollector  # noqa: E402


class _EmptyMsgError(Exception):
    def __str__(self) -> str:
        return ""


class _FakeChromium:
    def __init__(self, *, launch_exc: Exception | None = None):
        self._launch_exc = launch_exc

    def launch(self, **_kwargs: Any) -> Any:
        if self._launch_exc is not None:
            raise self._launch_exc
        return _FakeBrowser()


class _FakeBrowser:
    process = None

    def new_context(self, **_kwargs: Any) -> Any:
        return _FakeContext()


class _FakeContext:
    def new_page(self) -> Any:
        return _FakePage()


class _FakePage:
    url = "https://example.invalid/"

    def screenshot(self, **_kwargs: Any) -> None:
        return None


class _FakePlaywright:
    def __init__(self, *, chromium: _FakeChromium | None = None):
        self.chromium = chromium or _FakeChromium()


class _FakeMonitor:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    def wire(self, _page: Any) -> None:
        return None


def _identity() -> dict[str, Any]:
    return {
        "suite_sid": "00000000-1111-2222-3333-444444444444",
        "suite_sid_prefix": "00000000",
        "ok": False,
        "failure": "",
        "capture_ended_at": "",
        "phase": "started",
    }


def test_empty_exception_message_still_nonempty_failure() -> None:
    fail = cap.classify_bootstrap_failure(_EmptyMsgError())
    assert fail
    assert "bootstrap_abort" in fail
    assert "_EmptyMsgError" in fail


def test_secret_bearing_message_redacted() -> None:
    jwtish = "eyJhbGciOiJIUzI1NiJ9." + ("a" * 12) + "." + ("b" * 12)
    msg = cap.sanitize_bootstrap_exception_message(
        Exception(f"auth Bearer SECRETTOKEN123 and {jwtish}")
    )
    assert "SECRETTOKEN123" not in msg
    assert jwtish not in msg
    assert "[redacted]" in msg


def test_persist_bootstrap_abort_writes_contract(tmp_path: Path, monkeypatch) -> None:
    art = tmp_path / "result.json"
    monkeypatch.setattr(cap, "RESULT_PATH", art)
    monkeypatch.setattr("playwright_auth_capture_diag.RESULT_PATH", art)

    # Route writer through our patched path
    def _write(payload: dict[str, Any]) -> Path:
        art.write_text(json.dumps(payload), encoding="utf-8")
        return art

    monkeypatch.setattr(cap, "write_result_artifact", _write)
    identity = _identity()
    path = cap.persist_bootstrap_abort_artifact(
        identity,
        bootstrap_stage="browser_launch_start",
        exc=RuntimeError("launch exploded"),
        required_cloud_sha="948a051",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["ok"] is False
    assert data["phase"] == "bootstrap_abort"
    assert data["failure"]
    assert data["capture_ended_at"]
    assert data["bootstrap_stage"] == "browser_launch_start"
    assert data["exception_type"] == "RuntimeError"
    assert "launch exploded" in data["exception_message"]
    assert data["required_cloud_sha"] == "948a051"
    assert "Bearer" not in json.dumps(data)


def test_historical_070a_shape_repaired(tmp_path: Path, monkeypatch) -> None:
    """phase=started + failure='' must not survive a catchable bootstrap exception."""
    art = tmp_path / "result.json"
    art.write_text(
        json.dumps(
            {
                "suite_sid": "070a20d7-ad29-42f5-a1d3-d080bb2c97b5",
                "phase": "started",
                "ok": False,
                "failure": "",
                "capture_ended_at": "",
            }
        ),
        encoding="utf-8",
    )

    def _write(payload: dict[str, Any]) -> Path:
        art.write_text(json.dumps(payload), encoding="utf-8")
        return art

    monkeypatch.setattr(cap, "write_result_artifact", _write)
    identity = json.loads(art.read_text(encoding="utf-8"))
    code = cap.handle_bootstrap_exception(
        identity,
        bootstrap_stage="browser_launch_start",
        exc=RuntimeError("chromium.launch failed"),
        sign_in_wait_entered=False,
    )
    assert code == 1
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["phase"] == "bootstrap_abort"
    assert data["failure"]
    assert data["capture_ended_at"]
    assert data["phase"] != "started" or data["failure"] != ""


def test_sync_playwright_style_failure_via_handler(tmp_path: Path, monkeypatch) -> None:
    art = tmp_path / "r.json"

    def _write(payload: dict[str, Any]) -> Path:
        art.write_text(json.dumps(payload), encoding="utf-8")
        return art

    monkeypatch.setattr(cap, "write_result_artifact", _write)
    identity = _identity()
    identity["bootstrap_stage"] = "playwright_starting"
    code = cap.handle_bootstrap_exception(
        identity,
        bootstrap_stage="playwright_starting",
        exc=RuntimeError("sync_playwright failed"),
        sign_in_wait_entered=False,
    )
    assert code == 1
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["phase"] == "bootstrap_abort"
    assert data["bootstrap_stage"] == "playwright_starting"
    assert data["failure"]


def _raise_on_call(exc: Exception):
    def _fn(*_a: Any, **_k: Any) -> Any:
        raise exc

    return _fn


def test_chromium_launch_failure_stage(tmp_path: Path, monkeypatch) -> None:
    art = tmp_path / "r.json"

    def _write(payload: dict[str, Any]) -> Path:
        art.write_text(json.dumps(payload), encoding="utf-8")
        return art

    monkeypatch.setattr(cap, "write_result_artifact", _write)
    monkeypatch.setattr(cap, "TRACE_ROOT", tmp_path)
    identity = _identity()
    pw = _FakePlaywright(chromium=_FakeChromium(launch_exc=RuntimeError("launch boom")))
    try:
        cap.run_playwright_bootstrap_to_sign_in_wait(
            pw,
            identity=identity,
            target_sid=identity["suite_sid"],
            start_url="https://example.invalid/",
            collector=CaptureTraceCollector(),
            goto_and_wake_fn=lambda *a, **k: None,
            surface_monitor_cls=_FakeMonitor,
        )
        raise AssertionError("expected launch boom")
    except RuntimeError:
        assert identity["bootstrap_stage"] == "browser_launch_start"
        cap.handle_bootstrap_exception(
            identity,
            bootstrap_stage=identity["bootstrap_stage"],
            exc=RuntimeError("launch boom"),
            sign_in_wait_entered=False,
        )
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["bootstrap_stage"] == "browser_launch_start"
    assert data["phase"] == "bootstrap_abort"


def test_context_create_failure_stage(tmp_path: Path, monkeypatch) -> None:
    art = tmp_path / "r.json"

    def _write(payload: dict[str, Any]) -> Path:
        art.write_text(json.dumps(payload), encoding="utf-8")
        return art

    monkeypatch.setattr(cap, "write_result_artifact", _write)
    monkeypatch.setattr(cap, "TRACE_ROOT", tmp_path)

    class BoomBrowser(_FakeBrowser):
        def new_context(self, **_k: Any) -> Any:
            raise RuntimeError("context boom")

    class Chromium:
        def launch(self, **_k: Any) -> Any:
            return BoomBrowser()

    identity = _identity()
    pw = _FakePlaywright(chromium=Chromium())  # type: ignore[arg-type]
    try:
        cap.run_playwright_bootstrap_to_sign_in_wait(
            pw,
            identity=identity,
            target_sid=identity["suite_sid"],
            start_url="https://example.invalid/",
            collector=CaptureTraceCollector(),
            goto_and_wake_fn=lambda *a, **k: None,
            surface_monitor_cls=_FakeMonitor,
        )
        raise AssertionError("expected context boom")
    except RuntimeError:
        assert identity["bootstrap_stage"] == "context_create_start"
        cap.persist_bootstrap_abort_artifact(
            identity, bootstrap_stage=identity["bootstrap_stage"], exc=RuntimeError("context boom")
        )
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["bootstrap_stage"] == "context_create_start"


def test_page_create_failure_stage(tmp_path: Path, monkeypatch) -> None:
    art = tmp_path / "r.json"

    def _write(payload: dict[str, Any]) -> Path:
        art.write_text(json.dumps(payload), encoding="utf-8")
        return art

    monkeypatch.setattr(cap, "write_result_artifact", _write)
    monkeypatch.setattr(cap, "TRACE_ROOT", tmp_path)

    class BoomContext(_FakeContext):
        def new_page(self) -> Any:
            raise RuntimeError("page boom")

    class OkBrowser(_FakeBrowser):
        def new_context(self, **_k: Any) -> Any:
            return BoomContext()

    class Chromium:
        def launch(self, **_k: Any) -> Any:
            return OkBrowser()

    identity = _identity()
    pw = _FakePlaywright(chromium=Chromium())  # type: ignore[arg-type]
    try:
        cap.run_playwright_bootstrap_to_sign_in_wait(
            pw,
            identity=identity,
            target_sid=identity["suite_sid"],
            start_url="https://example.invalid/",
            collector=CaptureTraceCollector(),
            goto_and_wake_fn=lambda *a, **k: None,
            surface_monitor_cls=_FakeMonitor,
        )
        raise AssertionError("expected page boom")
    except RuntimeError:
        assert identity["bootstrap_stage"] == "page_create_start"
        cap.persist_bootstrap_abort_artifact(
            identity, bootstrap_stage=identity["bootstrap_stage"], exc=RuntimeError("page boom")
        )
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["bootstrap_stage"] == "page_create_start"


def test_navigation_failure_stage(tmp_path: Path, monkeypatch) -> None:
    art = tmp_path / "r.json"

    def _write(payload: dict[str, Any]) -> Path:
        art.write_text(json.dumps(payload), encoding="utf-8")
        return art

    monkeypatch.setattr(cap, "write_result_artifact", _write)
    monkeypatch.setattr(cap, "TRACE_ROOT", tmp_path)
    identity = _identity()
    pw = _FakePlaywright()
    try:
        cap.run_playwright_bootstrap_to_sign_in_wait(
            pw,
            identity=identity,
            target_sid=identity["suite_sid"],
            start_url="https://example.invalid/",
            collector=CaptureTraceCollector(),
            goto_and_wake_fn=_raise_on_call(RuntimeError("nav boom")),
            surface_monitor_cls=_FakeMonitor,
        )
        raise AssertionError("expected nav boom")
    except RuntimeError:
        assert identity["bootstrap_stage"] == "navigation_start"
        cap.persist_bootstrap_abort_artifact(
            identity, bootstrap_stage=identity["bootstrap_stage"], exc=RuntimeError("nav boom")
        )
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["bootstrap_stage"] == "navigation_start"
    assert data["phase"] == "bootstrap_abort"


def test_successful_bootstrap_reaches_sign_in_wait(tmp_path: Path, monkeypatch) -> None:
    art = tmp_path / "r.json"

    def _write(payload: dict[str, Any]) -> Path:
        art.write_text(json.dumps(payload), encoding="utf-8")
        return art

    monkeypatch.setattr(cap, "write_result_artifact", _write)
    monkeypatch.setattr(cap, "TRACE_ROOT", tmp_path)
    identity = _identity()
    browser, context, page, monitor = cap.run_playwright_bootstrap_to_sign_in_wait(
        _FakePlaywright(),
        identity=identity,
        target_sid=identity["suite_sid"],
        start_url="https://example.invalid/",
        collector=CaptureTraceCollector(),
        goto_and_wake_fn=lambda *a, **k: None,
        surface_monitor_cls=_FakeMonitor,
    )
    assert browser is not None and context is not None and page is not None
    assert isinstance(monitor, _FakeMonitor)
    assert identity["bootstrap_stage"] == "sign_in_wait_entered"
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["phase"] == "sign_in_wait"
    assert data.get("ok") is False  # identity seed; wait path not success yet
    # Must not look like historical blank abort
    assert not (data.get("phase") == "started" and data.get("failure") == "")


def test_post_wait_exception_not_converted_to_bootstrap_abort() -> None:
    identity = _identity()
    try:
        cap.handle_bootstrap_exception(
            identity,
            bootstrap_stage="sign_in_wait_entered",
            exc=RuntimeError("later failure"),
            sign_in_wait_entered=True,
        )
        raise AssertionError("expected re-raise")
    except RuntimeError as exc:
        assert "later failure" in str(exc)


def test_source_wraps_bootstrap_and_does_not_catch_baseexception() -> None:
    src = Path(cap.__file__).read_text(encoding="utf-8")
    assert "run_playwright_bootstrap_to_sign_in_wait" in src
    assert "handle_bootstrap_exception" in src
    assert "except Exception as exc:" in src
    assert "except BaseException" not in src
    assert "phase\": \"bootstrap_abort\"" in src or "phase': 'bootstrap_abort'" in src
    # Hard-kill limit documented
    assert "Hard/native/OS kills remain unobservable" in src or "Does NOT cover hard kill" in src
