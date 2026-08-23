"""Stage1A queue-seed delivery-authority contract regressions (local harness only)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from stage1_francisco_native_click_consumption import (  # noqa: E402
    evaluate_francisco_native_click_consumption_ack,
)
from stage1_queue_seed_harness import (  # noqa: E402
    DELIVERY_AUTHORITY_CALLBACK_ENTRY,
    DELIVERY_AUTHORITY_CLIENT_TRANSPORT_ONLY,
    DELIVERY_AUTHORITY_POST_MUTATION_SNAPSHOT,
    STAGE1_QUEUE_SEED_CALLBACK_ENTERED_WITHOUT_POST_MUTATION_SNAPSHOT,
    STAGE1_QUEUE_SEED_CLIENT_TRANSPORT_WITHOUT_CALLBACK_ENTRY,
    STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY,
    STAGE1_QUEUE_SEED_POST_NO_ADD,
    callback_entry_observed_from_step,
    evaluate_seed_delivery_authority,
    evaluate_seed_queue_membership_delta,
    format_delivery_authority_summary,
    map_widget_consumption_ack,
    post_mutation_snapshot_observed_from_membership,
    seed_queue_distinct_players,
)

C82_ROOM = "C82EA3A2"
C82_KEY = f"rec_card_queue_{C82_ROOM}_0_231_rec_card"
FRANCISCO = "Francisco Lindor"


class _FakePage:
    def wait_for_timeout(self, _ms: int) -> None:
        return None


def _trace(*, player_name: str = FRANCISCO, player_id: str = "231", room: str = C82_ROOM) -> dict[str, Any]:
    return {
        "room_id": room,
        "player_name": player_name,
        "player_id": player_id,
        "pick_index": "0",
        "widget_key": f"rec_card_queue_{room}_0_{player_id}_rec_card",
        "widget_liveness": "live_this_run",
        "surface": "rec_card",
        "callback_id": "_on_rec_queue_click",
    }


def _cand(*, room: str = C82_ROOM) -> dict[str, Any]:
    return {
        "player_name": FRANCISCO,
        "binding_confidence": "unique",
        "global_index": 0,
        "player_id": "231",
        "binding_via": "ld_rec_card_meta",
        "structured_identity_source": "ld_rec_card_meta+render_trace",
        "widget_key": f"rec_card_queue_{room}_0_231_rec_card",
        "visible": True,
    }


def _deliver(*, key: str, callback: bool) -> dict[str, Any]:
    return {
        "click_dispatched": True,
        "authorized_rec_card_key": key,
        "playwright_only": True,
        "delivery_method": "playwright_ld_rec_card_meta_native_stbutton",
        "live_reacquired_before_click": True,
        "live_reacquisition_probe": {"key_match": True, "probe_present": True},
        "consumption_ack": evaluate_francisco_native_click_consumption_ack(
            click_dispatched=True,
            authorized_rec_card_key=key,
            post_click_transport={
                "ws_log_sample": [{"payload_text": key}],
                "streamlit_backmsg_sent": True,
                "script_run_seq_changed": False,
            },
            callback_entered_observed=callback,
            trusted_dom_click=True,
        ),
        "click_start_ts": 1.0,
    }


def test_c82_client_transport_without_callback_entry() -> None:
    membership_calls = {"n": 0}

    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        out = _deliver(key=authorized_rec_card_key, callback=False)
        out["playwright_only"] = playwright_only
        return out

    def membership_wait(*_a, **_k):
        membership_calls["n"] += 1
        return {
            "session_queue": None,
            "canonical_queue": None,
            "stale_baseline_rejected": True,
            "stale_baseline_only": True,
            "accepted_post": None,
        }

    meta = seed_queue_distinct_players(
        _FakePage(),
        scrape_container_fn=lambda _p: {
            "found": True,
            "empty": True,
            "players": [],
            "excerpt": "Draft queue\n",
        },
        min_players=1,
        discover_fn=lambda _p: [_cand()],
        deliver_fn=deliver,
        render_trace_fn=lambda _p, player_name="": _trace(),
        membership_wait_fn=membership_wait,
        expected_room_id=C82_ROOM,
        expected_pick_index=0,
    )
    step = meta["seed_steps"][0]
    assert step["click_dispatched"] is True
    assert step["client_widget_transport_emitted"] is True
    assert step["callback_entry_observed"] is False
    assert step["post_mutation_snapshot_observed"] is False
    assert step["delivery_authority"] == DELIVERY_AUTHORITY_CLIENT_TRANSPORT_ONLY
    assert step["mutation_proven"] is False
    assert step.get("membership_skipped_fail_fast") is True
    assert membership_calls["n"] == 0
    assert str(meta["classification"]).startswith(
        "STAGE1_QUEUE_SEED_CLIENT_TRANSPORT_WITHOUT_CALLBACK_ENTRY"
    )
    assert "widget consumed" not in str(meta["classification"]).lower()
    assert "widget consumed" not in str(step.get("delivery_authority_summary") or "").lower()
    assert "insufficient_deliberate_seed_clicks" not in str(meta["classification"])
    assert step.get("queue_after") is None
    assert step.get("queue_after_unavailable") is True
    summary = str(step.get("delivery_authority_summary") or "")
    assert "client transport" in summary.lower()
    assert "callback entry not observed" in summary.lower()
    assert step.get("widget_consumption_ack") is True  # legacy retained, not success gate
    diag = step.get("attempt_diagnostics") or {}
    assert diag.get("player_id") == "231"
    assert diag.get("attempt_number") == 1


def test_c50832_transport_only_click1_continues_to_three_structured_seeds() -> None:
    """Regression for production c50832d5: transport-only click #1 must not abort the 3-click loop.

    First structured candidate emits client transport without server progress; harness fail-fasts
    (no long membership wait), rediscovers, and deliberately seeds three distinct player_ids.
    """
    roster = [
        ("Francisco Lindor", "231"),
        ("Pete Alonso", "592789"),
        ("Juan Soto", "665742"),
        ("Mookie Betts", "605141"),
    ]
    state = {"queue": [], "deliveries": [], "discovers": 0, "membership_calls": 0}

    def discover(_page):
        state["discovers"] += 1
        return [
            {
                "player_name": n,
                "binding_confidence": "unique",
                "global_index": i,
                "player_id": pid,
                "binding_via": "ld_rec_card_meta",
                "structured_identity_source": "ld_rec_card_meta+render_trace",
                "widget_key": f"rec_card_queue_{C82_ROOM}_0_{pid}_rec_card",
                "visible": True,
            }
            for i, (n, pid) in enumerate(roster)
        ]

    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        name = str(pick.get("player_name") or "")
        state["deliveries"].append(name)
        # Click #1: client transport only (production c50832d5 Lindor pattern).
        callback = len(state["deliveries"]) > 1
        out = _deliver(key=authorized_rec_card_key, callback=callback)
        if callback:
            # Server progress signal so membership wait is entered for proven seeds.
            out["post_click_transport"] = {
                "ws_log_sample": [{"payload_text": authorized_rec_card_key}],
                "streamlit_backmsg_sent": True,
                "script_run_seq_changed": True,
                "python_rerun_started": True,
            }
        out["playwright_only"] = playwright_only
        return out

    def membership_wait(_page, **kwargs):
        state["membership_calls"] += 1
        player = kwargs["player_name"]
        before = list(kwargs.get("queue_before") or [])
        after = before + [player]
        state["queue"] = after
        return {
            "session_queue": list(after),
            "canonical_queue": list(after),
            "stale_baseline_rejected": True,
            "accepted_post": {
                "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
                "session_queue": list(after),
                "canonical_queue": list(after),
            },
            "post_mutation_snapshot_observed": True,
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
            "excerpt": "Draft queue\n" + ("\n".join(state["queue"]) + "\n" if state["queue"] else ""),
        },
        min_players=3,
        discover_fn=discover,
        deliver_fn=deliver,
        render_trace_fn=render_trace,
        membership_wait_fn=membership_wait,
        expected_room_id=C82_ROOM,
        expected_pick_index=0,
    )
    assert state["deliveries"][0] == "Francisco Lindor"
    assert state["deliveries"][1:] == ["Pete Alonso", "Juan Soto", "Mookie Betts"]
    assert state["discovers"] >= 4  # rediscovery after each attempt
    assert state["membership_calls"] == 3  # fail-fast skipped membership for click #1
    assert meta.get("ok") is True
    proven = [s for s in meta["seed_steps"] if s.get("mutation_proven")]
    assert len(proven) == 3
    assert [s["player_name"] for s in proven] == ["Pete Alonso", "Juan Soto", "Mookie Betts"]
    assert all(
        str((s.get("pre_click_record") or {}).get("player_id") or "").isdigit() for s in proven
    )
    fail_step = meta["seed_steps"][0]
    assert fail_step.get("membership_skipped_fail_fast") is True
    assert fail_step.get("delivery_authority") == DELIVERY_AUTHORITY_CLIENT_TRANSPORT_ONLY
    assert state["queue"] == ["Pete Alonso", "Juan Soto", "Mookie Betts"]
    # No display-name-only path: every proven step carries structured player_id.
    for s in proven:
        assert str((s.get("attempt_diagnostics") or {}).get("player_id") or "").isdigit()


def test_historical_callback_and_post_success() -> None:
    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        out = _deliver(key=authorized_rec_card_key, callback=True)
        out["playwright_only"] = playwright_only
        return out

    queues = {"names": []}

    def membership_wait(_page, **kwargs):
        player = kwargs["player_name"]
        before = list(kwargs.get("queue_before") or [])
        after = before + [player]
        queues["names"] = after
        return {
            "session_queue": list(after),
            "canonical_queue": list(after),
            "stale_baseline_rejected": True,
            "accepted_post": {
                "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
                "session_queue": list(after),
                "canonical_queue": list(after),
            },
            "post_mutation_snapshot_observed": True,
        }

    def scrape(_page):
        names = list(queues["names"])
        return {
            "found": True,
            "empty": not names,
            "players": [{"name": n} for n in names],
            "excerpt": "Draft queue\n" + ("\n".join(names) + "\n" if names else ""),
        }

    meta = seed_queue_distinct_players(
        _FakePage(),
        scrape_container_fn=scrape,
        min_players=1,
        discover_fn=lambda _p: [_cand()],
        deliver_fn=deliver,
        render_trace_fn=lambda _p, player_name="": _trace(),
        membership_wait_fn=membership_wait,
        expected_room_id=C82_ROOM,
        expected_pick_index=0,
    )
    step = meta["seed_steps"][0]
    assert step["client_widget_transport_emitted"] is True
    assert step["callback_entry_observed"] is True
    assert step["post_mutation_snapshot_observed"] is True
    assert step["delivery_authority"] == DELIVERY_AUTHORITY_POST_MUTATION_SNAPSHOT
    assert step["mutation_proven"] is True
    assert step["retry"] == 0
    assert step["js_fallback_used"] is False


def test_callback_entered_without_post_mutation_snapshot() -> None:
    def deliver(_page, pick, *, playwright_only=False, authorized_rec_card_key=""):
        out = _deliver(key=authorized_rec_card_key, callback=True)
        out["playwright_only"] = playwright_only
        return out

    meta = seed_queue_distinct_players(
        _FakePage(),
        scrape_container_fn=lambda _p: {
            "found": True,
            "empty": True,
            "players": [],
            "excerpt": "Draft queue\n",
        },
        min_players=1,
        discover_fn=lambda _p: [_cand()],
        deliver_fn=deliver,
        render_trace_fn=lambda _p, player_name="": _trace(),
        membership_wait_fn=lambda *_a, **_k: {
            "session_queue": None,
            "canonical_queue": None,
            "stale_baseline_only": True,
            "accepted_post": None,
        },
        expected_room_id=C82_ROOM,
        expected_pick_index=0,
    )
    step = meta["seed_steps"][0]
    assert step["callback_entry_observed"] is True
    assert step["post_mutation_snapshot_observed"] is False
    assert step["delivery_authority"] == DELIVERY_AUTHORITY_CALLBACK_ENTRY
    assert str(meta["classification"]).startswith(
        "STAGE1_QUEUE_SEED_CALLBACK_ENTERED_WITHOUT_POST_MUTATION_SNAPSHOT"
    )
    assert "CLIENT_TRANSPORT_WITHOUT_CALLBACK" not in str(meta["classification"])


def test_post_present_queues_unavailable_uses_membership_boundary() -> None:
    auth = evaluate_seed_delivery_authority(
        click_dispatched=True,
        client_widget_transport_emitted=True,
        callback_entry_observed=True,
        post_mutation_snapshot_observed=True,
        membership_ok=False,
        membership_failures=["authoritative_queues_unavailable"],
    )
    assert auth["delivery_authority"] == DELIVERY_AUTHORITY_POST_MUTATION_SNAPSHOT
    assert str(auth["first_boundary"]).startswith("STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY")
    assert auth["authoritative_queues_unavailable"] is True

    delta = evaluate_seed_queue_membership_delta(
        queue_before=[],
        session_after=None,
        canonical_after=None,
        player_name=FRANCISCO,
    )
    assert "authoritative_queues_unavailable" in delta["failures"]
    membership = {
        **delta,
        "post_wait": {
            "accepted_post": {
                "phase": "QUEUE_STATE_POST_MUTATION_ADDED",
                "session_queue": None,
                "canonical_queue": None,
            }
        },
        "session_after": None,
        "canonical_after": None,
    }
    assert post_mutation_snapshot_observed_from_membership(membership) is True


def test_post_no_add_classification() -> None:
    auth = evaluate_seed_delivery_authority(
        click_dispatched=True,
        client_widget_transport_emitted=True,
        callback_entry_observed=True,
        post_mutation_snapshot_observed=True,
        membership_ok=False,
        membership_failures=["length_not_plus_one"],
        post_no_add_observed=True,
    )
    assert auth["delivery_authority"] == DELIVERY_AUTHORITY_POST_MUTATION_SNAPSHOT
    assert str(auth["first_boundary"]).startswith("STAGE1_QUEUE_SEED_POST_NO_ADD")

    membership = {
        "ok": False,
        "failures": ["length_not_plus_one"],
        "session_after": [],
        "canonical_after": [],
        "post_wait": {
            "accepted_post": {
                "phase": "QUEUE_STATE_POST_NO_ADD",
                "session_queue": [],
                "canonical_queue": [],
            },
            "observations": [{"candidate_phase": "QUEUE_STATE_POST_NO_ADD"}],
        },
    }
    assert post_mutation_snapshot_observed_from_membership(membership) is True


def test_outbound_key_alone_never_proves_callback() -> None:
    ack = evaluate_francisco_native_click_consumption_ack(
        click_dispatched=True,
        authorized_rec_card_key=C82_KEY,
        post_click_transport={"ws_log_sample": [{"payload_text": C82_KEY}]},
        callback_entered_observed=False,
    )
    assert ack["client_widget_transport_emitted"] is True
    assert ack["callback_entered_observed"] is False
    assert ack["outbound_widget_key_alone_proves_callback"] is False
    assert ack["legacy_ack_proves_callback_entry"] is False
    assert ack["francisco_widget_consumption_ack"] is True
    mapped = map_widget_consumption_ack({"click_dispatched": True, "consumption_ack": ack})
    assert mapped["client_widget_transport_emitted"] is True
    assert mapped["legacy_ack_proves_callback_entry"] is False
    assert mapped["callback_entered_observed"] is False


def test_callback_entry_alone_does_not_prove_membership() -> None:
    auth = evaluate_seed_delivery_authority(
        click_dispatched=True,
        client_widget_transport_emitted=True,
        callback_entry_observed=True,
        post_mutation_snapshot_observed=False,
        membership_ok=False,
    )
    assert auth["seed_mutation_proven"] is False
    assert auth["delivery_authority"] == DELIVERY_AUTHORITY_CALLBACK_ENTRY
    assert str(auth["first_boundary"]).startswith(
        "STAGE1_QUEUE_SEED_CALLBACK_ENTERED_WITHOUT_POST_MUTATION_SNAPSHOT"
    )


def test_callback_ledger_authority_not_inferred_from_ws_or_seq() -> None:
    step = {
        "click_dispatched": True,
        "client_widget_transport_emitted": True,
        "consumption_ack": {
            "callback_entered_observed": False,
            "script_run_seq_changed": True,
            "expected_widget_key_present_in_transport": True,
        },
        "app_callback_entered": False,
        "app_classification": "QUEUE1C3",
        "app_queue_trace": {"payload": {"last": {}}},
    }
    assert callback_entry_observed_from_step(step) is False
    step["app_callback_entered"] = True
    assert callback_entry_observed_from_step(step) is True
    step["app_callback_entered"] = False
    step["app_classification"] = "QUEUE1C3D — app callback entered"
    assert callback_entry_observed_from_step(step) is True


def test_summary_never_says_widget_consumed_for_transport_only() -> None:
    summary = format_delivery_authority_summary(
        {
            "delivery_authority": DELIVERY_AUTHORITY_CLIENT_TRANSPORT_ONLY,
            "client_widget_transport_emitted": True,
            "callback_entry_observed": False,
            "post_mutation_snapshot_observed": False,
        },
        click_dispatched=True,
    )
    assert "widget consumed" not in summary.lower()
    assert "callback entry not observed" in summary.lower()


def test_constants_exported() -> None:
    assert STAGE1_QUEUE_SEED_CLIENT_TRANSPORT_WITHOUT_CALLBACK_ENTRY
    assert STAGE1_QUEUE_SEED_CALLBACK_ENTERED_WITHOUT_POST_MUTATION_SNAPSHOT
    assert STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY
    assert STAGE1_QUEUE_SEED_POST_NO_ADD
    assert "widget consumed" not in STAGE1_QUEUE_SEED_MEMBERSHIP_BOUNDARY.lower()
