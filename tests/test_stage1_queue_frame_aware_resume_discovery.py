"""Frame-aware Resume Draft discovery — Stage 1A-QUEUE harness repair tests (browser-free)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load_resume():
    import importlib.util
    import sys

    path = SCRIPTS / "p8_proven_resume_delivery.py"
    name = "p8_proven_resume_delivery_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    # Ensure sibling pause module importable as p8_proven_pause_delivery
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


def test_is_timer_resume_label_accepts_product_rejects_sidebar() -> None:
    m = _load_resume()
    assert m.is_timer_resume_label("▶ Resume Draft") is True
    assert m.is_timer_resume_label("Resume Draft") is True
    assert m.is_timer_resume_label("Resume Live Draft") is False
    assert m.is_timer_resume_label("Something else") is False


def test_25e61776_frame_shape_selects_app_iframe_not_shell() -> None:
    """Forensic shape: main resumeCount=0, app iframe resumeCount=2, paused."""
    m = _load_resume()
    probes = [
        {
            "frameIndex": 0,
            "frameUrl": "https://example.streamlit.app/",
            "resumeCount": 0,
            "resumeEnabled": 0,
            "resumeDisabled": 0,
            "sidebarResumeCount": 0,
            "candidates": [],
            "hasLedger": False,
            "isAppFrame": False,
        },
        {
            "frameIndex": 1,
            "frameUrl": "https://example.streamlit.app/~/+/?active_page=Live+Draft+Room",
            "resumeCount": 2,
            "resumeEnabled": 1,
            "resumeDisabled": 1,
            "sidebarResumeCount": 0,
            "candidates": [
                {"text": "▶ Resume Draft", "disabled": False, "visible": True},
                {"text": "▶ Resume Draft", "disabled": True, "visible": True},
            ],
            "hasLedger": True,
            "isAppFrame": True,
        },
    ]
    sel = m.select_authoritative_resume_probe(probes)
    assert sel["ok"] is True
    assert sel["preferred"]["isAppFrame"] is True
    inv = sel["inventory"]
    assert inv["main_shell_resume_enabled"] == 0
    assert inv["app_iframe_resume_enabled"] == 1


def test_main_shell_only_resume_rejected() -> None:
    m = _load_resume()
    probes = [
        {
            "frameIndex": 0,
            "frameUrl": "https://example.streamlit.app/",
            "resumeCount": 1,
            "resumeEnabled": 1,
            "resumeDisabled": 0,
            "sidebarResumeCount": 0,
            "candidates": [{"text": "Resume Draft", "disabled": False, "visible": True}],
            "hasLedger": False,
            "isAppFrame": False,
        },
        {
            "frameIndex": 1,
            "frameUrl": "https://example.streamlit.app/~/+/",
            "resumeCount": 0,
            "resumeEnabled": 0,
            "resumeDisabled": 0,
            "sidebarResumeCount": 0,
            "candidates": [],
            "hasLedger": True,
            "isAppFrame": True,
        },
    ]
    sel = m.select_authoritative_resume_probe(probes)
    assert sel["ok"] is False
    assert sel["boundary"] == m.RESUME_CONTROL_NOT_FOUND


def test_disabled_resume_fail_closed() -> None:
    m = _load_resume()
    probes = [
        {
            "frameIndex": 1,
            "frameUrl": "https://example.streamlit.app/~/+/",
            "resumeCount": 1,
            "resumeEnabled": 0,
            "resumeDisabled": 1,
            "sidebarResumeCount": 0,
            "candidates": [{"text": "▶ Resume Draft", "disabled": True, "visible": True}],
            "hasLedger": True,
            "isAppFrame": True,
        },
    ]
    sel = m.select_authoritative_resume_probe(probes)
    assert sel["ok"] is False
    assert sel["boundary"] == m.RESUME_CONTROL_DISABLED


def test_missing_resume_fail_closed() -> None:
    m = _load_resume()
    probes = [
        {
            "frameIndex": 0,
            "frameUrl": "https://example.streamlit.app/",
            "resumeCount": 0,
            "resumeEnabled": 0,
            "resumeDisabled": 0,
            "sidebarResumeCount": 0,
            "candidates": [],
            "hasLedger": False,
            "isAppFrame": False,
        },
        {
            "frameIndex": 1,
            "frameUrl": "https://example.streamlit.app/~/+/",
            "resumeCount": 0,
            "resumeEnabled": 0,
            "resumeDisabled": 0,
            "sidebarResumeCount": 1,
            "candidates": [],
            "hasLedger": True,
            "isAppFrame": True,
        },
    ]
    sel = m.select_authoritative_resume_probe(probes)
    assert sel["ok"] is False
    assert sel["boundary"] == m.RESUME_CONTROL_NOT_FOUND
    assert sel.get("resume_error") == m.NO_RESUME_CONTROL


def test_sidebar_resume_not_counted_as_timer_resume() -> None:
    m = _load_resume()
    probes = [
        {
            "frameIndex": 1,
            "frameUrl": "https://example.streamlit.app/~/+/",
            "resumeCount": 0,
            "resumeEnabled": 0,
            "resumeDisabled": 0,
            "sidebarResumeCount": 1,
            "candidates": [],
            "hasLedger": True,
            "isAppFrame": True,
        },
    ]
    sel = m.select_authoritative_resume_probe(probes)
    assert sel["ok"] is False
    assert sel["inventory"]["sidebar_resume_total"] == 1


def test_ambiguous_enabled_resumes_in_one_frame_fail_closed() -> None:
    m = _load_resume()
    probes = [
        {
            "frameIndex": 1,
            "frameUrl": "https://example.streamlit.app/~/+/",
            "resumeCount": 2,
            "resumeEnabled": 2,
            "resumeDisabled": 0,
            "sidebarResumeCount": 0,
            "candidates": [
                {"text": "▶ Resume Draft", "disabled": False, "visible": True},
                {"text": "▶ Resume Draft", "disabled": False, "visible": True},
            ],
            "hasLedger": True,
            "isAppFrame": True,
        },
    ]
    sel = m.select_authoritative_resume_probe(probes)
    assert sel["ok"] is False
    assert sel["boundary"] == m.RESUME_AMBIGUOUS_CONTROLS


class _FakeBtn:
    def __init__(self, text: str, *, disabled: bool = False):
        self._text = text
        self._disabled = disabled
        self.clicks = 0

    def inner_text(self, timeout: int = 500) -> str:
        return self._text

    def is_disabled(self) -> bool:
        return self._disabled

    def scroll_into_view_if_needed(self, timeout: int = 8000) -> None:
        return None

    def click(self, timeout: int = 12000) -> None:
        if self._disabled:
            raise RuntimeError("disabled")
        self.clicks += 1


class _FakeLoc:
    def __init__(self, buttons: list[_FakeBtn]):
        self._buttons = buttons

    def count(self) -> int:
        return len(self._buttons)

    def nth(self, i: int) -> _FakeBtn:
        return self._buttons[i]

    @property
    def first(self) -> _FakeBtn:
        return self._buttons[0]


class _FakeFrame:
    def __init__(self, url: str, buttons: list[_FakeBtn]):
        self.url = url
        self._buttons = buttons

    def get_by_role(self, role: str, name: Any = None) -> _FakeLoc:
        assert role == "button"
        matched = []
        for b in self._buttons:
            if "Resume Draft" in b._text.replace("▶", "").strip() or (
                name is not None and name.search(b._text)
            ):
                matched.append(b)
        return _FakeLoc(matched)


class _FakePage:
    def __init__(self, frames: list[_FakeFrame], probes: list[dict[str, Any]]):
        self.frames = frames
        self._probes = probes
        self._closed = False
        self.wait_ms = 0

    def is_closed(self) -> bool:
        return self._closed

    def evaluate(self, _js: str) -> list[dict[str, Any]]:
        return self._probes

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_ms += int(ms)

    def get_by_role(self, role: str, name: Any = None) -> _FakeLoc:
        """Main-frame-only — shell frame buttons only (historical defect surface)."""
        shell = self.frames[0] if self.frames else _FakeFrame("", [])
        return shell.get_by_role(role, name=name)


def _shape_25e61776_page() -> tuple[_FakePage, _FakeBtn]:
    shell_btn = _FakeBtn("unrelated")
    app_enabled = _FakeBtn("▶ Resume Draft", disabled=False)
    app_disabled = _FakeBtn("▶ Resume Draft", disabled=True)
    page = _FakePage(
        frames=[
            _FakeFrame("https://example.streamlit.app/", []),
            _FakeFrame(
                "https://example.streamlit.app/~/+/?suite_sid=71559005",
                [app_enabled, app_disabled],
            ),
        ],
        probes=[
            {
                "frameIndex": 0,
                "frameUrl": "https://example.streamlit.app/",
                "resumeCount": 0,
                "resumeEnabled": 0,
                "resumeDisabled": 0,
                "sidebarResumeCount": 0,
                "candidates": [],
                "hasLedger": False,
                "isAppFrame": False,
            },
            {
                "frameIndex": 1,
                "frameUrl": "https://example.streamlit.app/~/+/?suite_sid=71559005",
                "resumeCount": 2,
                "resumeEnabled": 1,
                "resumeDisabled": 1,
                "sidebarResumeCount": 0,
                "candidates": [
                    {"text": "▶ Resume Draft", "disabled": False, "visible": True},
                    {"text": "▶ Resume Draft", "disabled": True, "visible": True},
                ],
                "hasLedger": True,
                "isAppFrame": True,
            },
        ],
    )
    return page, app_enabled


def test_legacy_main_frame_only_fails_25e61776_shape() -> None:
    m = _load_resume()
    page, app_btn = _shape_25e61776_page()
    legacy = m._legacy_main_frame_only_resume_click(page)
    assert legacy.get("resumed") is False
    assert legacy.get("resume_error") == m.NO_RESUME_CONTROL
    assert app_btn.clicks == 0


def test_frame_aware_resume_one_trusted_click_25e61776_shape() -> None:
    m = _load_resume()
    page, app_btn = _shape_25e61776_page()
    queue = ["Francisco Lindor", "Ketel Marte", "Pete Alonso"]

    def scrape_pre(_p):
        return {"room_id": "25E61776", "pick_index": 0, "paused": True}

    def scrape_post(_p):
        return {
            "room_id": "25E61776",
            "pick_index": 0,
            "status": "in_progress",
            "paused": False,
            "timer": "0:58",
            "timer_running": True,
            "require_timer": True,
        }

    out = m.proven_resume_single_click(
        page,
        expected_room_id="25E61776",
        queue_seed_resolved=True,
        paused=True,
        authenticated=True,
        pre_queue=queue,
        pre_pick_index=0,
        scrape_pre_state=scrape_pre,
        scrape_post_state=scrape_post,
        scrape_queue=lambda _p: list(queue),
        settle_ms=10,
    )
    assert out["resumed"] is True
    assert out["click_dispatched"] is True
    assert out["trusted_playwright_click"] is True
    assert out["retry_click"] is False
    assert out["js_synthetic_click"] is False
    assert app_btn.clicks == 1
    assert "/~/+/" in str(out.get("click_frame_url") or "")
    assert out["resume_boundary"] == m.RESUME_DELIVERY_RESOLVED
    assert out["product_control"]["key"] == "live_draft_resume"


def test_postcondition_failure_click_does_not_mark_resumed() -> None:
    m = _load_resume()
    page, app_btn = _shape_25e61776_page()

    out = m.proven_resume_single_click(
        page,
        expected_room_id="25E61776",
        queue_seed_resolved=True,
        paused=True,
        authenticated=True,
        pre_queue=["A"],
        scrape_pre_state=lambda _p: {"room_id": "25E61776", "pick_index": 0, "paused": True},
        scrape_post_state=lambda _p: {
            "room_id": "25E61776",
            "pick_index": 0,
            "status": "paused",
            "paused": True,
            "timer_running": False,
            "require_timer": True,
        },
        scrape_queue=lambda _p: ["A"],
        settle_ms=10,
    )
    assert app_btn.clicks == 1
    assert out["click_dispatched"] is True
    assert out["resumed"] is False
    assert out["resume_boundary"] == m.RESUME_POSTCONDITION_NOT_PROVEN


def test_disabled_button_no_click_via_helper() -> None:
    m = _load_resume()
    disabled = _FakeBtn("▶ Resume Draft", disabled=True)
    page = _FakePage(
        frames=[
            _FakeFrame("https://example.streamlit.app/", []),
            _FakeFrame("https://example.streamlit.app/~/+/", [disabled]),
        ],
        probes=[
            {
                "frameIndex": 0,
                "frameUrl": "https://example.streamlit.app/",
                "resumeCount": 0,
                "resumeEnabled": 0,
                "resumeDisabled": 0,
                "sidebarResumeCount": 0,
                "candidates": [],
                "hasLedger": False,
                "isAppFrame": False,
            },
            {
                "frameIndex": 1,
                "frameUrl": "https://example.streamlit.app/~/+/",
                "resumeCount": 1,
                "resumeEnabled": 0,
                "resumeDisabled": 1,
                "sidebarResumeCount": 0,
                "candidates": [{"text": "▶ Resume Draft", "disabled": True, "visible": True}],
                "hasLedger": True,
                "isAppFrame": True,
            },
        ],
    )
    out = m.proven_resume_single_click(
        page,
        expected_room_id="25E61776",
        queue_seed_resolved=True,
        paused=True,
        authenticated=True,
        settle_ms=1,
    )
    assert disabled.clicks == 0
    assert out["resumed"] is False
    assert out["resume_boundary"] == m.RESUME_CONTROL_DISABLED


def test_runner_resume_abort_not_hardcoded_queueui1() -> None:
    src = (SCRIPTS / "run_production_stage1_authenticated.py").read_text(encoding="utf-8")
    # Resume abort must use resume_boundary, not first_boundary=QUEUEUI1
    assert "queue_setup_resume_after_seeding" in src
    assert "proven_resume_single_click" in src
    assert "resume_boundary" in src
    # The stale hardcoded mapping for resume failure must be gone
    assert 'first_boundary=QUEUEUI1,\n                        reason="resume_after_queue_setup_failed"' not in src
    assert 'reason="resume_after_queue_setup_failed"' in src
    # Guard: if somehow QUEUEUI1 appears, runner remaps it
    assert 'if resume_boundary == QUEUEUI1:' in src


def test_build_precondition_block_preserves_resume_boundary() -> None:
    import sys

    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from stage1_harness_observability import QUEUEUI1, build_stage1a_queue_precondition_block

    block = build_stage1a_queue_precondition_block(
        first_boundary="resume_control_not_found",
        reason="resume_after_queue_setup_failed",
        active_live_page_gate={"passed": True, "classification": "ACTIVE_QUEUE_SURFACE_RESOLVED"},
        queue_meta={"classification": "QUEUE_SEED_RESOLVED", "ok": True},
    )
    assert block["first_boundary"] == "resume_control_not_found"
    assert block["first_boundary"] != QUEUEUI1
    assert block["active_live_page_gate"]["classification"] == "ACTIVE_QUEUE_SURFACE_RESOLVED"


def test_postcondition_success_helper() -> None:
    m = _load_resume()
    proof = m._postcondition_resume_ok(
        pre={"room_id": "25E61776", "pick_index": 0},
        post={
            "room_id": "25E61776",
            "pick_index": 0,
            "status": "in_progress",
            "paused": False,
            "timer_running": True,
            "require_timer": True,
        },
        expected_room_id="25E61776",
        pre_queue=["A", "B", "C"],
        post_queue=["A", "B", "C"],
    )
    assert proof["ok"] is True


def test_queue_seed_not_resolved_precondition() -> None:
    m = _load_resume()
    page, _ = _shape_25e61776_page()
    out = m.proven_resume_single_click(
        page,
        expected_room_id="25E61776",
        queue_seed_resolved=False,
        paused=True,
        authenticated=True,
    )
    assert out["resumed"] is False
    assert out["resume_boundary"] == m.RESUME_QUEUE_SEED_NOT_RESOLVED
