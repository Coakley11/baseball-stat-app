"""Browser-free Stage1 queue-seed authorized-widget delivery repair tests.

Covers D3EA9619 key-wiring defect replay and sequential membership contract.
NO network/browser. NO product mutation.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_francisco_native_click_consumption import (  # noqa: E402
    evaluate_francisco_native_click_consumption_ack,
)
from stage1_queue_seed_harness import (  # noqa: E402
    QUEUE_SEED_RESOLVED,
    QUEUE1C3A2K,
    STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY,
    STAGE1_QUEUE_SEED_WIDGET_CONSUMPTION_BOUNDARY,
    authorize_seed_widget_identity,
    build_queue_seed_evidence,
    evaluate_seed_queue_membership_delta,
    map_widget_consumption_ack,
    parse_rec_card_queue_widget_key,
    seed_queue_distinct_players,
)
from stage1_rec_queue_click_trace_scrape import merge_render_trace_into_step  # noqa: E402


D3_KEY = "rec_card_queue_D3EA9619_0_231_rec_card"
D3_ROOM = "D3EA9619"


class _FakePage:
    def wait_for_timeout(self, _ms: int) -> None:
        return None


def _trace(
    *,
    player_name: str,
    player_id: str,
    room: str = D3_ROOM,
    pick: int = 0,
    key: str | None = None,
    liveness: str = "live_this_run",
) -> dict[str, Any]:
    widget_key = key if key is not None else f"rec_card_queue_{room}_{pick}_{player_id}_rec_card"
    return {
        "room_id": room,
        "player_name": player_name,
        "player_id": player_id,
        "pick_index": str(pick),
        "widget_key": widget_key,
        "widget_liveness": liveness,
        "surface": "rec_card",
        "callback_id": "_on_rec_queue_click",
    }


def _step_from_trace(player_name: str, trace: dict[str, Any], candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    step = {
        "player_name": player_name,
        "intended_player": player_name,
        "pre_click_record": candidate
        or {
            "player_name": player_name,
            "binding_confidence": "unique",
            "binding_via": "ld_rec_card_meta",
            "global_index": 0,
        },
    }
    merge_render_trace_into_step(step, trace)
    return step


def test_parse_rec_card_queue_widget_key_d3ea9619() -> None:
    parsed = parse_rec_card_queue_widget_key(D3_KEY)
    assert parsed["ok"] is True
    assert parsed["room_id"] == D3_ROOM
    assert parsed["pick_index"] == 0
    assert parsed["player_id"] == "231"


def test_authorize_passes_known_render_trace_key() -> None:
    step = _step_from_trace("Francisco Lindor", _trace(player_name="Francisco Lindor", player_id="231"))
    authz = authorize_seed_widget_identity(step, expected_room_id=D3_ROOM, expected_pick_index=0)
    assert authz["ok"] is True
    assert authz["authorized_rec_card_key"] == D3_KEY


def test_missing_widget_key_no_click_authorization() -> None:
    step = _step_from_trace(
        "Francisco Lindor",
        {
            "room_id": D3_ROOM,
            "player_name": "Francisco Lindor",
            "player_id": "231",
            "pick_index": "0",
            "widget_key": "",
            "widget_liveness": "live_this_run",
        },
    )
    authz = authorize_seed_widget_identity(step)
    assert authz["ok"] is False
    assert "widget_key_missing" in authz["failures"]
    assert authz["classification"] == QUEUE1C3A2K


def test_mismatched_candidate_widget_key_fails() -> None:
    step = _step_from_trace(
        "Francisco Lindor",
        _trace(player_name="Francisco Lindor", player_id="231"),
        candidate={
            "player_name": "Francisco Lindor",
            "binding_confidence": "unique",
            "widget_key": "rec_card_queue_D3EA9619_0_999_rec_card",
        },
    )
    authz = authorize_seed_widget_identity(step)
    assert authz["ok"] is False
    assert "candidate_widget_key_mismatch" in authz["failures"]


def test_stale_room_fails() -> None:
    step = _step_from_trace("Francisco Lindor", _trace(player_name="Francisco Lindor", player_id="231"))
    authz = authorize_seed_widget_identity(step, expected_room_id="DEADBEEF", expected_pick_index=0)
    assert authz["ok"] is False
    assert "stale_room" in authz["failures"]


def test_stale_pick_fails() -> None:
    step = _step_from_trace("Francisco Lindor", _trace(player_name="Francisco Lindor", player_id="231"))
    authz = authorize_seed_widget_identity(step, expected_room_id=D3_ROOM, expected_pick_index=7)
    assert authz["ok"] is False
    assert "stale_pick" in authz["failures"]


def test_wrong_player_card_key_fails() -> None:
    step = _step_from_trace(
        "Francisco Lindor",
        _trace(player_name="Pete Alonso", player_id="1", key="rec_card_queue_D3EA9619_0_1_rec_card"),
    )
    authz = authorize_seed_widget_identity(step)
    assert authz["ok"] is False
    assert "trace_player_mismatch" in authz["failures"]


def test_stale_liveness_fails() -> None:
    step = _step_from_trace(
        "Francisco Lindor",
        _trace(player_name="Francisco Lindor", player_id="231", liveness="stale_retained_dom"),
    )
    authz = authorize_seed_widget_identity(step)
    assert authz["ok"] is False
    assert "stale_widget_liveness" in authz["failures"]


def test_d3ea9619_old_path_would_dispatch_without_key_repaired_stops() -> None:
    """Replay: candidate lacked key; render trace knew key — repaired path still requires authz ok.

    Old path called deliver without authorized_rec_card_key. Repaired path refuses click when
    expected_widget_key cannot be bound (simulate missing key on step).
    """
    candidate = {
        "player_name": "Francisco Lindor",
        "binding_confidence": "unique",
        "binding_via": "ld_rec_card_meta",
        "global_index": 0,
        # deliberately no widget_key — matches production discovery shape
    }
    # Defect shape: trace had the key, but if merge never ran / key stripped → no click.
    step_missing = {
        "player_name": "Francisco Lindor",
        "intended_player": "Francisco Lindor",
        "pre_click_record": candidate,
        "render_trace_present": True,
        "expected_widget_key": "",
        "app_render_trace": {"player_name": "Francisco Lindor", "widget_key": ""},
    }
    assert authorize_seed_widget_identity(step_missing)["ok"] is False

    # Correct path: merge supplies current key → authorize ok → key must be passed to deliver.
    step_ok = _step_from_trace("Francisco Lindor", _trace(player_name="Francisco Lindor", player_id="231"), candidate)
    authz = authorize_seed_widget_identity(step_ok, expected_room_id=D3_ROOM, expected_pick_index=0)
    assert authz["ok"] is True
    assert authz["authorized_rec_card_key"] == D3_KEY

    calls: list[dict[str, Any]] = []

    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        calls.append(
            {
                "pick": pick,
                "playwright_only": playwright_only,
                "authorized_rec_card_key": authorized_rec_card_key,
            }
        )
        return {
            "click_dispatched": True,
            "playwright_only": playwright_only,
            "authorized_rec_card_key": authorized_rec_card_key,
            "delivery_method": "playwright_ld_rec_card_meta_native_stbutton",
            "live_reacquired_before_click": True,
            "live_reacquisition_probe": {"key_match": True, "probe_present": True},
            "consumption_ack": evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=authorized_rec_card_key,
                post_click_transport={
                    "ws_log_sample": [{"payload_text": authorized_rec_card_key}],
                    "streamlit_backmsg_sent": True,
                },
                callback_entered_observed=True,
                trusted_dom_click=True,
            ),
            "click_start_ts": 100.0,
        }

    queues = {"session": [], "canonical": []}

    def membership_wait(_page, **kwargs):
        player = kwargs["player_name"]
        before = list(kwargs["queue_before"])
        after = before + [player]
        queues["session"] = after
        queues["canonical"] = list(after)
        return {
            "session_queue": list(after),
            "canonical_queue": list(after),
            "stale_baseline_rejected": True,
            "ok": True,
        }

    def discover(_page):
        return [candidate]

    def scrape(_page):
        return {"found": True, "empty": not queues["session"], "players": [{"name": n} for n in queues["session"]], "excerpt": "Draft queue\n"}

    def render_trace(_page, player_name=""):
        return _trace(player_name="Francisco Lindor", player_id="231")

    meta = seed_queue_distinct_players(
        _FakePage(),
        scrape_container_fn=scrape,
        min_players=1,
        discover_fn=discover,
        deliver_fn=deliver,
        render_trace_fn=render_trace,
        membership_wait_fn=membership_wait,
        expected_room_id=D3_ROOM,
        expected_pick_index=0,
    )
    assert len(calls) == 1
    assert calls[0]["authorized_rec_card_key"] == D3_KEY
    assert calls[0]["playwright_only"] is True
    assert meta["seed_steps"][0]["widget_consumption_ack"] is True
    assert meta["seed_steps"][0]["mutation_proven"] is True
    assert meta["seed_steps"][0]["retry"] == 0
    assert meta["seed_steps"][0]["js_fallback_used"] is False


def test_click_dispatched_false_fails() -> None:
    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        return {
            "click_dispatched": False,
            "authorized_rec_card_key": authorized_rec_card_key,
            "playwright_only": playwright_only,
            "delivery_method": "",
            "error": "button_not_enabled",
            "consumption_ack": evaluate_francisco_native_click_consumption_ack(
                click_dispatched=False, authorized_rec_card_key=authorized_rec_card_key
            ),
        }

    meta = seed_queue_distinct_players(
        _FakePage(),
        scrape_container_fn=lambda _p: {"found": True, "empty": True, "players": [], "excerpt": "Draft queue\n"},
        min_players=1,
        discover_fn=lambda _p: [
            {"player_name": "Francisco Lindor", "binding_confidence": "unique", "global_index": 0, "player_id": "231", "binding_via": "ld_rec_card_meta", "structured_identity_source": "ld_rec_card_meta+render_trace", "widget_key": "rec_card_queue_TESTROOM_0_231_rec_card", "visible": True}
        ],
        deliver_fn=deliver,
        render_trace_fn=lambda _p, player_name="": _trace(player_name="Francisco Lindor", player_id="231"),
        membership_wait_fn=lambda *_a, **_k: {"session_queue": ["Francisco Lindor"], "canonical_queue": ["Francisco Lindor"]},
        expected_room_id=D3_ROOM,
        expected_pick_index=0,
    )
    assert meta["ok"] is False
    assert meta["seed_steps"][0]["click_dispatched"] is False
    assert meta["seed_steps"][0]["helper_invocations"] == 1


def test_click_dispatched_true_consumption_ack_false_fails() -> None:
    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        return {
            "click_dispatched": True,
            "authorized_rec_card_key": authorized_rec_card_key,
            "playwright_only": playwright_only,
            "delivery_method": "playwright_ld_rec_card_meta_native_stbutton",
            "consumption_ack": evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=authorized_rec_card_key,
                post_click_transport={
                    "streamlit_backmsg_sent": True,
                    "native_widget_event_observed": True,
                    "ws_log_sample": [{"payload_text": "unrelated_widget", "widget_key_bytes_present": False}],
                },
                callback_entered_observed=False,
                trusted_dom_click=True,
            ),
        }

    membership_calls = {"n": 0}

    def membership_wait(*_a, **_k):
        membership_calls["n"] += 1
        return {"session_queue": [], "canonical_queue": []}

    meta = seed_queue_distinct_players(
        _FakePage(),
        scrape_container_fn=lambda _p: {"found": True, "empty": True, "players": [], "excerpt": "Draft queue\n"},
        min_players=1,
        discover_fn=lambda _p: [
            {"player_name": "Francisco Lindor", "binding_confidence": "unique", "global_index": 0, "player_id": "231", "binding_via": "ld_rec_card_meta", "structured_identity_source": "ld_rec_card_meta+render_trace", "widget_key": "rec_card_queue_TESTROOM_0_231_rec_card", "visible": True}
        ],
        deliver_fn=deliver,
        render_trace_fn=lambda _p, player_name="": _trace(player_name="Francisco Lindor", player_id="231"),
        membership_wait_fn=membership_wait,
        expected_room_id=D3_ROOM,
        expected_pick_index=0,
    )
    assert meta["classification"] == STAGE1_QUEUE_SEED_WIDGET_CONSUMPTION_BOUNDARY
    assert meta["seed_steps"][0]["widget_consumption_ack"] is False
    assert membership_calls["n"] == 0  # must not proceed to membership / player #2


def test_generic_ws_only_does_not_satisfy_ack() -> None:
    ack = evaluate_francisco_native_click_consumption_ack(
        click_dispatched=True,
        authorized_rec_card_key=D3_KEY,
        post_click_transport={
            "streamlit_backmsg_sent": True,
            "native_widget_event_observed": True,
            "script_run_seq_changed": False,
            "ws_log_sample": [{"payload_text": "generic", "widget_key_bytes_present": False}],
        },
        callback_entered_observed=False,
    )
    mapped = map_widget_consumption_ack(
        {"click_dispatched": True, "authorized_rec_card_key": D3_KEY, "consumption_ack": ack}
    )
    assert mapped["widget_consumption_ack"] is False
    assert mapped["generic_ws_satisfies_ack"] is False
    assert mapped["generic_only_traffic"] is True


def test_exact_widget_key_consumption_ack_passes_delivery_boundary() -> None:
    ack = evaluate_francisco_native_click_consumption_ack(
        click_dispatched=True,
        authorized_rec_card_key=D3_KEY,
        post_click_transport={"ws_log_sample": [{"payload_text": D3_KEY}]},
        callback_entered_observed=False,
        trusted_dom_click=True,
    )
    mapped = map_widget_consumption_ack(
        {"click_dispatched": True, "authorized_rec_card_key": D3_KEY, "consumption_ack": ack}
    )
    assert mapped["ok"] is True
    assert mapped["widget_consumption_ack"] is True


def test_membership_absent_after_ack_fails_before_next_player() -> None:
    deliver_calls = {"n": 0}

    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        deliver_calls["n"] += 1
        return {
            "click_dispatched": True,
            "authorized_rec_card_key": authorized_rec_card_key,
            "playwright_only": True,
            "delivery_method": "playwright_ld_rec_card_meta_native_stbutton",
            "consumption_ack": evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=authorized_rec_card_key,
                post_click_transport={"ws_log_sample": [{"payload_text": authorized_rec_card_key}]},
                callback_entered_observed=True,
            ),
            "click_start_ts": 1.0,
        }

    players = [
        {"player_name": "Francisco Lindor", "binding_confidence": "unique", "global_index": 0, "player_id": "231", "binding_via": "ld_rec_card_meta", "structured_identity_source": "ld_rec_card_meta+render_trace", "widget_key": "rec_card_queue_TESTROOM_0_231_rec_card", "visible": True},
        {"player_name": "Pete Alonso", "binding_confidence": "unique", "global_index": 1},
    ]

    meta = seed_queue_distinct_players(
        _FakePage(),
        scrape_container_fn=lambda _p: {"found": True, "empty": True, "players": [], "excerpt": "Draft queue\n"},
        min_players=2,
        discover_fn=lambda _p: players,
        deliver_fn=deliver,
        render_trace_fn=lambda _p, player_name="": _trace(
            player_name=player_name or "Francisco Lindor",
            player_id="231" if "Francisco" in (player_name or "Francisco") else "10",
        ),
        membership_wait_fn=lambda *_a, **_k: {
            "session_queue": [],
            "canonical_queue": [],
            "stale_baseline_rejected": True,
        },
        expected_room_id=D3_ROOM,
        expected_pick_index=0,
    )
    assert meta["classification"] == STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY
    assert deliver_calls["n"] == 1  # player #2 never clicked


def test_membership_delta_stale_baseline_and_agreement() -> None:
    assert evaluate_seed_queue_membership_delta(
        queue_before=[],
        session_after=None,
        canonical_after=None,
        player_name="A",
    )["ok"] is False

    disagree = evaluate_seed_queue_membership_delta(
        queue_before=[],
        session_after=["A"],
        canonical_after=["B"],
        player_name="A",
    )
    assert disagree["ok"] is False
    assert "session_canonical_disagreement" in disagree["failures"]

    unrelated = evaluate_seed_queue_membership_delta(
        queue_before=[],
        session_after=["B"],
        canonical_after=["B"],
        player_name="A",
    )
    assert unrelated["ok"] is False
    assert "intended_player_not_sole_addition" in unrelated["failures"]

    removal = evaluate_seed_queue_membership_delta(
        queue_before=["A", "B"],
        session_after=["A", "C"],
        canonical_after=["A", "C"],
        player_name="C",
    )
    assert removal["ok"] is False
    assert "unexpected_removal" in removal["failures"]

    ok = evaluate_seed_queue_membership_delta(
        queue_before=["A"],
        session_after=["A", "B"],
        canonical_after=["A", "B"],
        player_name="B",
    )
    assert ok["ok"] is True


def test_sequential_three_player_seed_preserves_order() -> None:
    roster = [
        ("Francisco Lindor", "231"),
        ("Pete Alonso", "10"),
        ("Juan Soto", "22"),
    ]
    state = {"queue": [], "deliver_names": []}

    def discover(_page):
        return [
            {"player_name": n, "binding_confidence": "unique", "global_index": i}
            for i, (n, _) in enumerate(roster)
        ]

    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        name = pick["player_name"]
        state["deliver_names"].append(name)
        assert playwright_only is True
        assert authorized_rec_card_key
        # Runtime-derived identity: key embeds player_id for this candidate, not a Francisco hardcode.
        pid = next(p for n, p in roster if n == name)
        assert f"_{pid}_" in authorized_rec_card_key
        assert authorized_rec_card_key.startswith("rec_card_queue_")
        return {
            "click_dispatched": True,
            "authorized_rec_card_key": authorized_rec_card_key,
            "playwright_only": True,
            "delivery_method": "playwright_ld_rec_card_meta_native_stbutton",
            "consumption_ack": evaluate_francisco_native_click_consumption_ack(
                click_dispatched=True,
                authorized_rec_card_key=authorized_rec_card_key,
                post_click_transport={"ws_log_sample": [{"payload_text": authorized_rec_card_key}]},
                callback_entered_observed=True,
            ),
            "click_start_ts": float(len(state["deliver_names"])),
        }

    def membership_wait(_page, **kwargs):
        player = kwargs["player_name"]
        before = list(kwargs["queue_before"])
        assert before == list(state["queue"])
        after = before + [player]
        state["queue"] = after
        return {
            "session_queue": list(after),
            "canonical_queue": list(after),
            "stale_baseline_rejected": True,
        }

    def render_trace(_page, player_name=""):
        for n, pid in roster:
            if n == player_name:
                return _trace(player_name=n, player_id=pid)
        raise AssertionError(f"unexpected player {player_name}")

    meta = seed_queue_distinct_players(
        _FakePage(),
        scrape_container_fn=lambda _p: {
            "found": True,
            "empty": not state["queue"],
            "players": [{"name": n} for n in state["queue"]],
            "excerpt": "Draft queue\n" + "\n".join(state["queue"]) + "\nClear Draft Queue\n",
        },
        min_players=3,
        discover_fn=discover,
        deliver_fn=deliver,
        render_trace_fn=render_trace,
        membership_wait_fn=membership_wait,
        expected_room_id=D3_ROOM,
        expected_pick_index=0,
    )
    assert state["deliver_names"] == ["Francisco Lindor", "Pete Alonso", "Juan Soto"]
    assert state["queue"] == ["Francisco Lindor", "Pete Alonso", "Juan Soto"]
    assert meta.get("ok") is True or build_queue_seed_evidence(meta, min_players=3).get("queue_seed_resolved")
    # Ensure player N+1 waited: deliver order equals membership order
    assert [s["player_name"] for s in meta["seed_steps"] if s.get("mutation_proven")] == state["queue"]
    assert all(s.get("helper_invocations") == 1 for s in meta["seed_steps"])
    assert all(s.get("retry") == 0 for s in meta["seed_steps"])
    assert all(s.get("js_fallback_used") is False for s in meta["seed_steps"])


def test_duplicate_candidate_not_used_as_second_distinct_seed() -> None:
    """After player #1 proven, same name must be excluded from next candidate selection."""
    from stage1_add_to_queue_delivery import select_next_seed_candidate

    candidates = [
        {
            "player_name": "Francisco Lindor",
            "binding_confidence": "unique",
            "global_index": 0,
            "player_id": "231",
            "binding_via": "ld_rec_card_meta",
            "structured_identity_source": "ld_rec_card_meta+render_trace",
            "widget_key": "rec_card_queue_TESTROOM_0_231_rec_card",
        },
        {
            "player_name": "Francisco Lindor",
            "binding_confidence": "unique",
            "global_index": 1,
            "player_id": "231",
            "binding_via": "ld_rec_card_meta",
            "structured_identity_source": "ld_rec_card_meta+render_trace",
            "widget_key": "rec_card_queue_TESTROOM_0_231_rec_card",
        },
        {
            "player_name": "Pete Alonso",
            "binding_confidence": "unique",
            "global_index": 2,
            "player_id": "592789",
            "binding_via": "ld_rec_card_meta",
            "structured_identity_source": "ld_rec_card_meta+render_trace",
            "widget_key": "rec_card_queue_TESTROOM_0_592789_rec_card",
        },
    ]
    pick, _ = select_next_seed_candidate(candidates, exclude_player_names={"francisco lindor"})
    assert pick is not None
    assert pick["player_name"] == "Pete Alonso"


def test_no_hardcoded_francisco_player_id_in_seed_harness_source() -> None:
    src = (SCRIPTS / "stage1_queue_seed_harness.py").read_text(encoding="utf-8")
    # Repair must not hardcode Francisco identity into seed loop.
    assert "player_id=\"231\"" not in src
    assert "Francisco Lindor" not in src.split("def seed_queue_distinct_players")[1].split("def ")[0]


def test_paused_state_does_not_disable_authorization_contract() -> None:
    step = _step_from_trace("Juan Soto", _trace(player_name="Juan Soto", player_id="22", room="AAAA1111"))
    authz = authorize_seed_widget_identity(step, expected_room_id="AAAA1111", expected_pick_index=0)
    assert authz["ok"] is True
    assert authz["paused_compatible"] is True


def test_francisco_consumption_helper_regression() -> None:
    ok = evaluate_francisco_native_click_consumption_ack(
        click_dispatched=True,
        authorized_rec_card_key=D3_KEY,
        post_click_transport={"ws_log_sample": [{"payload_text": D3_KEY}]},
        callback_entered_observed=False,
    )
    assert ok["francisco_widget_consumption_ack"] is True
    assert ok["click_dispatch_alone_proves_mutation"] is False


def test_classifier_still_requires_three_proven_identities() -> None:
    meta = {
        "seed_steps": [
            {"click_dispatched": True, "mutation_proven": True, "player_name": "A"},
            {"click_dispatched": True, "mutation_proven": True, "player_name": "B"},
            {"click_dispatched": True, "mutation_proven": True, "player_name": "C"},
        ],
        "queue_order_established": True,
        "queue_container": {"excerpt": "Draft queue\nA\nB\nC\nClear Draft Queue\n", "players": []},
        "pick_index_zero_after_setup": True,
        "paused_state_maintained": True,
    }
    ev = build_queue_seed_evidence(meta, min_players=3)
    assert ev["queue_seed_resolved"] is True
    assert QUEUE_SEED_RESOLVED


def test_seed_source_mentions_authorize_path() -> None:
    src = inspect.getsource(seed_queue_distinct_players)
    assert "authorized_rec_card_key" in src
    assert "widget_consumption_ack" in src
    assert "prove_seed_membership_after_click" in src
