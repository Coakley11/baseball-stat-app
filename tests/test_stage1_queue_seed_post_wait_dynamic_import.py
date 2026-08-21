"""Browser-free tests: Stage1 seed post-wait dynamic-import sys.modules repair.

Proves BD5F1E7C defect: dataclass-bearing Francisco module must be registered in
sys.modules BEFORE exec_module under Python 3.13.

NO network/browser. NO product mutation.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_francisco_native_click_consumption import (  # noqa: E402
    evaluate_francisco_native_click_consumption_ack,
)
from stage1_queue_seed_harness import (  # noqa: E402
    STAGE1_SEED_POST_WAIT_MODULE_NAME,
    load_stage1_seed_post_wait_module,
    prove_seed_membership_after_click,
    seed_queue_distinct_players,
)


class _FakePage:
    def wait_for_timeout(self, _ms: int) -> None:
        return None


def _purge_post_wait_module() -> None:
    sys.modules.pop(STAGE1_SEED_POST_WAIT_MODULE_NAME, None)


def test_historical_defect_exec_without_sys_modules_registration() -> None:
    """Reproduce BD5F1E7C class failure against the real dataclass-bearing Francisco module."""
    path = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
    name = "stage1_seed_post_wait_shared_defect_repro"
    sys.modules.pop(name, None)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        # Deliberately omit sys.modules[name] = mod (historical Stage1 defect).
        raised: Exception | None = None
        try:
            spec.loader.exec_module(mod)
        except AttributeError as exc:
            raised = exc
        assert raised is not None, "expected AttributeError without sys.modules registration"
        assert "__dict__" in str(raised)
    finally:
        sys.modules.pop(name, None)


def test_repaired_loader_registers_before_exec_and_loads_dataclass() -> None:
    _purge_post_wait_module()
    mod = load_stage1_seed_post_wait_module(force_reload=True)
    assert sys.modules[STAGE1_SEED_POST_WAIT_MODULE_NAME] is mod
    assert callable(mod.wait_for_authoritative_post_queue_scrape)
    assert callable(mod.select_authoritative_post_queues)
    ports_cls = getattr(mod, "MutationCloudPorts", None)
    assert ports_cls is not None
    assert ports_cls.__module__ == STAGE1_SEED_POST_WAIT_MODULE_NAME
    assert hasattr(ports_cls, "__dataclass_fields__")


def test_loader_source_registers_sys_modules_before_exec_module() -> None:
    src = inspect.getsource(load_stage1_seed_post_wait_module)
    assert "sys.modules[name] = mod" in src
    assert src.index("sys.modules[name] = mod") < src.index("spec.loader.exec_module(mod)")


def test_loader_cleanup_removes_partial_module_on_exec_failure() -> None:
    name = STAGE1_SEED_POST_WAIT_MODULE_NAME
    _purge_post_wait_module()
    bad_path = ROOT / "data" / "_tmp_stage1_post_wait_broken.py"
    bad_path.write_text("raise RuntimeError('forced_loader_failure')\n", encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(name, bad_path)
        mod = importlib.util.module_from_spec(spec)
        previous = sys.modules.get(name)
        sys.modules[name] = mod
        try:
            assert spec.loader is not None
            spec.loader.exec_module(mod)
            raise AssertionError("expected forced_loader_failure")
        except RuntimeError as exc:
            assert "forced_loader_failure" in str(exc)
            if sys.modules.get(name) is mod:
                if previous is None:
                    del sys.modules[name]
                else:
                    sys.modules[name] = previous
        assert name not in sys.modules
    finally:
        sys.modules.pop(name, None)
        bad_path.unlink(missing_ok=True)


def test_load_stage1_cleanup_on_exec_failure_via_loader() -> None:
    """load_stage1_seed_post_wait_module must not leave a broken binding authoritative."""
    _purge_post_wait_module()
    name = STAGE1_SEED_POST_WAIT_MODULE_NAME
    real_path = ROOT / "data" / "_stage1_francisco_queue_mutation_proof_d664924.py"
    bad_path = ROOT / "data" / "_tmp_stage1_post_wait_broken2.py"
    bad_path.write_text("raise RuntimeError('forced_loader_failure')\n", encoding="utf-8")
    try:
        # Build broken spec BEFORE patching so we do not call the MagicMock.
        broken_spec = importlib.util.spec_from_file_location(name, bad_path)
        with mock.patch("importlib.util.spec_from_file_location", return_value=broken_spec):
            try:
                load_stage1_seed_post_wait_module(force_reload=True)
                raise AssertionError("expected RuntimeError")
            except RuntimeError as exc:
                assert "forced_loader_failure" in str(exc)
            assert name not in sys.modules
    finally:
        sys.modules.pop(name, None)
        bad_path.unlink(missing_ok=True)
        assert real_path.is_file()


def test_loader_cleanup_on_unresolved_callable_path() -> None:
    """If exec succeeds but required callable missing, binding must not remain authoritative."""
    name = "stage1_seed_post_wait_shared_incomplete_probe"
    path = ROOT / "data" / "_tmp_stage1_post_wait_incomplete.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    sys.modules.pop(name, None)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        previous = None
        sys.modules[name] = mod
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "wait_for_authoritative_post_queue_scrape", None)):
            if sys.modules.get(name) is mod:
                if previous is None:
                    del sys.modules[name]
        assert name not in sys.modules
    finally:
        sys.modules.pop(name, None)
        path.unlink(missing_ok=True)


def test_default_membership_path_loads_real_module_without_membership_wait_fn() -> None:
    """Integration: prove_seed_membership_after_click default path (no membership_wait_fn)."""
    _purge_post_wait_module()
    calls: dict[str, Any] = {"wait": 0, "select": 0}

    mod = load_stage1_seed_post_wait_module(force_reload=True)
    assert sys.modules[STAGE1_SEED_POST_WAIT_MODULE_NAME] is mod

    def fake_wait(page, *, production_sid, room_id, after_ts, timeout_s):
        calls["wait"] += 1
        calls["wait_args"] = {
            "production_sid": production_sid,
            "room_id": room_id,
            "after_ts": after_ts,
            "timeout_s": timeout_s,
        }
        return {
            "ok": True,
            "accepted_post": {
                "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
                "streamlit_session_id": production_sid,
                "room_id": room_id,
                "ts": float(after_ts or 0) + 1.0,
                "session_queue": ["Francisco Lindor"],
                "canonical_queue": ["Francisco Lindor"],
            },
            "stale_baseline_only": False,
        }

    def fake_select(*, production_sid, room_id="", after_ts=None, snapshots=None, ui_queue=None, **_k):
        calls["select"] += 1
        snap = (snapshots or [None])[0] or {}
        return {
            "session_queue": list(snap.get("session_queue") or []),
            "canonical_queue": list(snap.get("canonical_queue") or []),
            "rejection": None,
        }

    with mock.patch.object(mod, "wait_for_authoritative_post_queue_scrape", side_effect=fake_wait):
        with mock.patch.object(mod, "select_authoritative_post_queues", side_effect=fake_select):
            result = prove_seed_membership_after_click(
                _FakePage(),
                queue_before=[],
                player_name="Francisco Lindor",
                room_id="BD5F1E7C",
                production_sid="03247a11-4a3d-458c-b1bd-3e83878d6ad7",
                click_ts=100.0,
                timeout_s=5.0,
                # membership_wait_fn deliberately omitted — default loader path
            )
    assert calls["wait"] == 1
    assert calls["select"] == 1
    assert calls["wait_args"]["room_id"] == "BD5F1E7C"
    assert calls["wait_args"]["production_sid"] == "03247a11-4a3d-458c-b1bd-3e83878d6ad7"
    assert result["ok"] is True
    assert result["authoritative"] is True
    assert "authoritative_post_wait_unavailable" not in (result.get("failures") or [])
    assert result["session_after"] == ["Francisco Lindor"]
    assert result["canonical_after"] == ["Francisco Lindor"]


def test_seed_loop_default_membership_reaches_real_post_wait_callable() -> None:
    """seed_queue_distinct_players without membership_wait_fn uses repaired loader."""
    _purge_post_wait_module()
    room = "BD5F1E7C"
    key = f"rec_card_queue_{room}_0_231_rec_card"
    state = {"queue": []}
    wait_hits = {"n": 0}

    def discover(_page):
        return [{"player_name": "Francisco Lindor", "binding_confidence": "unique", "global_index": 0}]

    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        assert playwright_only is True
        assert authorized_rec_card_key == key
        return {
            "click_dispatched": True,
            "authorized_rec_card_key": authorized_rec_card_key,
            "playwright_only": True,
            "delivery_method": "playwright_ld_rec_card_meta_native_stbutton",
            "live_reacquired_before_click": True,
            "live_reacquisition_probe": {"key_match": True, "probe_present": True},
            "consumption_ack": evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=authorized_rec_card_key,
                post_click_transport={"ws_log_sample": [{"payload_text": authorized_rec_card_key}]},
                callback_entered_observed=True,
            ),
            "click_start_ts": 50.0,
        }

    def render_trace(_page, player_name=""):
        return {
            "room_id": room,
            "player_name": "Francisco Lindor",
            "player_id": "231",
            "pick_index": "0",
            "widget_key": key,
            "widget_liveness": "live_this_run",
        }

    mod = load_stage1_seed_post_wait_module(force_reload=True)

    def fake_wait(page, *, production_sid, room_id, after_ts, timeout_s):
        wait_hits["n"] += 1
        after = ["Francisco Lindor"]
        state["queue"] = after
        return {
            "ok": True,
            "accepted_post": {
                "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
                "streamlit_session_id": production_sid,
                "room_id": room_id,
                "ts": float(after_ts or 0) + 1.0,
                "session_queue": after,
                "canonical_queue": after,
            },
            "stale_baseline_only": False,
        }

    def fake_select(*, production_sid, room_id="", after_ts=None, snapshots=None, ui_queue=None, **_k):
        snap = (snapshots or [None])[0] or {}
        return {
            "session_queue": list(snap.get("session_queue") or []),
            "canonical_queue": list(snap.get("canonical_queue") or []),
            "rejection": None,
        }

    with mock.patch.object(mod, "wait_for_authoritative_post_queue_scrape", side_effect=fake_wait):
        with mock.patch.object(mod, "select_authoritative_post_queues", side_effect=fake_select):
            meta = seed_queue_distinct_players(
                _FakePage(),
                scrape_container_fn=lambda _p: {
                    "found": True,
                    "empty": not state["queue"],
                    "players": [{"name": n} for n in state["queue"]],
                    "excerpt": "Draft queue\n" + "\n".join(state["queue"]) + "\nClear Draft Queue\n",
                },
                min_players=1,
                discover_fn=discover,
                deliver_fn=deliver,
                render_trace_fn=render_trace,
                # NO membership_wait_fn
                expected_room_id=room,
                expected_pick_index=0,
                production_sid="03247a11-4a3d-458c-b1bd-3e83878d6ad7",
            )
    assert wait_hits["n"] == 1
    assert meta["seed_steps"][0]["widget_consumption_ack"] is True
    assert meta["seed_steps"][0]["mutation_proven"] is True
    assert "authoritative_post_wait_unavailable" not in str(meta.get("classification") or "")


def test_missing_membership_still_fail_closed_after_loader_ok() -> None:
    _purge_post_wait_module()
    mod = load_stage1_seed_post_wait_module(force_reload=True)

    def fake_wait(*_a, **_k):
        return {"ok": False, "accepted_post": None, "stale_baseline_only": True}

    def fake_select(**_k):
        return {
            "session_queue": None,
            "canonical_queue": None,
            "rejection": "stale_baseline_cannot_act_as_post",
        }

    with mock.patch.object(mod, "wait_for_authoritative_post_queue_scrape", side_effect=fake_wait):
        with mock.patch.object(mod, "select_authoritative_post_queues", side_effect=fake_select):
            result = prove_seed_membership_after_click(
                _FakePage(),
                queue_before=[],
                player_name="A",
                room_id="BD5F1E7C",
                production_sid="sid-1",
                click_ts=1.0,
            )
    assert result["ok"] is False
    assert "authoritative_post_wait_unavailable" not in (result.get("failures") or [])
