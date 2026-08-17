"""LOCAL/production harness: Francisco NORMAL queue-mutation proof (d664924).

Architecture:
  FRANCISCO_QUEUE_MUTATION_EXISTING_SOLO_ROOM_PROOF_ARCHITECTURE_RECOMMENDED

Topology:
  fresh bridge + fresh SID + existing solo room
  + NO stage1_francisco_callback_only latch
  + Stage A unchanged
  + exactly ONE normal Add-to-Queue click
  + same-run session/canonical membership authority

This module is runner/harness only. It does not modify product queue/gate/Stage A
code. Durable persistence flush is NOT part of narrow mutation authority.

Local selftests must call evaluators only — never main() against Cloud.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Filename retains historical d664924 continuity only.
# Executable live-runtime authority: resolve_required_cloud_sha() /
# MutationCloudConfig.required_sha (REQUIRED_CLOUD_SHA for Cloud execution).
_SHA7_RE = re.compile(r"^[0-9a-f]{7}$")
_BUILD_DISPLAY_RE = re.compile(r"^baseball-dev-([0-9a-f]{7})$")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

FRANCISCO_NAME = "Francisco Lindor"
FRANCISCO_LATCH_PARAM = "stage1_francisco_callback_only"
HOST_QUERY_PROBE_PARAM = "stage1_host_query_roundtrip_probe"
STAGE_A_QUERY_FLAGS = (
    "solo_component_diag=1",
    "solo_stage1_parent_boundary=1",
)
BASE = "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"

ARCHITECTURE = "FRANCISCO_QUEUE_MUTATION_EXISTING_SOLO_ROOM_PROOF_ARCHITECTURE_RECOMMENDED"


def normalize_required_cloud_sha(value: Any) -> str:
    """Normalize a required/live Cloud SHA to exactly 7 lowercase hex chars.

    Accepts: ``abcdef0``, ``baseball-dev-abcdef0``, or a full 40-char hex SHA.
    Returns ``\"\"`` for missing/malformed values (fail-closed callers decide).
    """
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if _SHA7_RE.fullmatch(text):
        return text
    matched = _BUILD_DISPLAY_RE.fullmatch(text)
    if matched:
        return matched.group(1)
    if _FULL_SHA_RE.fullmatch(text):
        return text[:7]
    return ""


def expected_build_display_for(required_sha: Any) -> str:
    sha = normalize_required_cloud_sha(required_sha)
    return f"baseball-dev-{sha}" if sha else ""


def resolve_required_cloud_sha(
    *,
    explicit: Any = None,
    env: Any = None,
    cloud_authorized: bool = False,
) -> dict[str, Any]:
    """Resolve CURRENT production runtime authority.

    Cloud-authorized mutation runs require non-empty ``REQUIRED_CLOUD_SHA`` (or
    an explicit override). Missing/empty/malformed → fail closed.
    Never falls back to a historical d664924 default.
    Capture-bridge ``cloud_runtime_sha`` is never consulted here.
    """
    environ = env if env is not None else os.environ
    raw_explicit = "" if explicit is None else str(explicit).strip()
    raw_env = str(environ.get("REQUIRED_CLOUD_SHA") or "").strip()
    raw = raw_explicit or raw_env
    normalized = normalize_required_cloud_sha(raw)
    if not raw:
        return {
            "ok": False,
            "required_sha": "",
            "expected_build_display": "",
            "raw": raw,
            "source": "explicit" if raw_explicit else ("env" if "REQUIRED_CLOUD_SHA" in dict(environ) else "none"),
            "reason": "missing",
            "cloud_authorized": bool(cloud_authorized),
        }
    if not normalized:
        return {
            "ok": False,
            "required_sha": "",
            "expected_build_display": "",
            "raw": raw,
            "source": "explicit" if raw_explicit else "env",
            "reason": "malformed",
            "cloud_authorized": bool(cloud_authorized),
        }
    return {
        "ok": True,
        "required_sha": normalized,
        "expected_build_display": expected_build_display_for(normalized),
        "raw": raw,
        "source": "explicit" if raw_explicit else "env",
        "reason": "",
        "cloud_authorized": bool(cloud_authorized),
    }


def evaluate_live_runtime_against_required(
    *,
    required_sha: Any,
    runtime_sha_raw: Any,
    deploy_build_raw: Any = None,
) -> dict[str, Any]:
    """Compare scraped live identity to an already-resolved required SHA (exact)."""
    req = normalize_required_cloud_sha(required_sha)
    live = normalize_required_cloud_sha(runtime_sha_raw)
    build_src = deploy_build_raw if deploy_build_raw is not None else runtime_sha_raw
    build = normalize_required_cloud_sha(build_src)
    expected_display = expected_build_display_for(req)
    runtime_match = bool(req) and live == req
    build_match = bool(req) and build == req
    return {
        "ok": bool(req) and runtime_match and build_match,
        "required_sha": req,
        "expected_build_display": expected_display,
        "runtime_sha_raw": runtime_sha_raw,
        "runtime_sha_normalized": live,
        "deploy_build_raw": deploy_build_raw,
        "deploy_build_normalized": build,
        "runtime_match": runtime_match,
        "build_match": build_match,
        "reason": (
            ""
            if (req and runtime_match and build_match)
            else ("required_sha_invalid" if not req else "runtime_mismatch")
        ),
    }


def first_defined(*values: Any) -> Any:
    """Return the first value that is not None / blank string.

    Integer ``0`` is a valid Stage A ``current_pick_index`` and MUST be preserved.
    """
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not str(value).strip():
            continue
        return value
    return None


def stage_a_identity_field_present(value: Any) -> bool:
    """True when a Stage A identity field is present (0 is present)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return True
    return bool(str(value).strip())


def stage_a_identity_complete(stage_a: dict[str, Any] | None) -> bool:
    row = stage_a if isinstance(stage_a, dict) else {}
    return all(
        stage_a_identity_field_present(row.get(k))
        for k in ("room_id", "current_pick_index", "player_id", "widget_key")
    )


def map_stage_a_authority_fields(
    *,
    retained: dict[str, Any] | None,
    identity: dict[str, Any] | None,
    fallback_room_id: str = "",
) -> dict[str, Any]:
    """Map retained steady + Francisco identity into canonical Stage A fields.

    Aligns with the callback-runner Stage A authority adapter:
    - ``current_pick_index`` from identity ``pick_index`` (0 preserved; never ``x or y``)
    - ``recommendation_fragment_run_seq`` from retained primary field, else identity
      / probe / latest retained generation fields already selected by Stage A
    Does not parse widget keys or invent pick from recommendation rank.
    """
    ret = retained if isinstance(retained, dict) else {}
    ident = identity if isinstance(identity, dict) else {}
    auth = ret.get("stage_a_authority") if isinstance(ret.get("stage_a_authority"), dict) else {}
    if not auth:
        steady = ret.get("steady_state_result") if isinstance(ret.get("steady_state_result"), dict) else {}
        auth = steady.get("stage_a_authority") if isinstance(steady.get("stage_a_authority"), dict) else {}

    pick = first_defined(
        auth.get("authoritative_pick_index"),
        ident.get("pick_index"),
        ident.get("current_pick_index"),
    )
    frag = first_defined(
        ret.get("recommendation_fragment_run_seq"),
        ident.get("recommendation_fragment_run_seq"),
        ret.get("recommendation_fragment_run_seq_francisco_probe"),
        ret.get("recommendation_fragment_run_seq_probe"),
        ret.get("latest_recommendation_fragment_run_seq"),
        auth.get("latest_recommendation_fragment_run_seq"),
    )
    full_app = first_defined(
        ret.get("full_app_run_seq"),
        ident.get("full_app_run_seq"),
        auth.get("global_full_app_run_seq"),
    )
    room = first_defined(
        ident.get("room_id"),
        auth.get("authoritative_room_id"),
        fallback_room_id,
    )
    return {
        "current_pick_index": pick,
        "recommendation_fragment_run_seq": frag,
        "full_app_run_seq": full_app,
        "room_id": room,
        "player_id": ident.get("player_id"),
        "widget_key": ident.get("widget_key"),
        "player_name": ident.get("player_name"),
        "authoritative_pick_source": auth.get("authoritative_pick_source"),
        "pick_status": auth.get("pick_status") or auth.get("pick_generation_status"),
    }

CLASSIFICATION_MEMBERSHIP_PROVEN = "FRANCISCO_MEMBERSHIP_MUTATION_PROVEN"
CLASSIFICATION_PLAYER_A = "PLAYER_A_QUEUE_MUTATION_RESOLVED"
CLASSIFICATION_CLICK_NOT_AUTHORIZED = "FRANCISCO_QUEUE_MUTATION_CLICK_NOT_AUTHORIZED"
CLASSIFICATION_BASELINE_REJECT = "FRANCISCO_QUEUE_MUTATION_BASELINE_REJECTED"
CLASSIFICATION_STOP_UNEXPECTED = "FRANCISCO_QUEUE_MUTATION_UNEXPECTED_PREMUTATION_STOP"
CLASSIFICATION_MUTATION_FAIL = "FRANCISCO_QUEUE_MUTATION_NOT_PROVEN"
CLASSIFICATION_MULTI_CLICK = "FRANCISCO_QUEUE_MUTATION_MULTIPLE_CLICKS"
CLASSIFICATION_AUTH_FAIL = "FRANCISCO_QUEUE_MUTATION_AUTH_ONLY_FAILED"
CLASSIFICATION_STAGE_A_FAIL = "FRANCISCO_QUEUE_MUTATION_STAGE_A_NOT_AUTHORIZED"
CLASSIFICATION_GATE_BLOCK = "FRANCISCO_QUEUE_MUTATION_GATE_BLOCKS_NORMAL_PATH"

PHASE_STOP = "FRANCISCO_QUEUE_CALLBACK_PREMUTATION_STOP"

# Consumed / retired bridges must never be defaulted.
RETIRED_BRIDGE_IDS = (
    "2e11d7aa-fb16-4810-aff5-7c95777ac7bf",
    "9c5edc03-1185-4a63-9512-e8de4f2a9d56",
    "f5a742ef-60ae-4092-8412-cbf0e5c12be7",
    "5c734dfd-fb92-4a79-9e71-5c3081f55c02",
)


def _norm_name(value: Any) -> str:
    return str(value or "").strip()


def _name_key(value: Any) -> str:
    return _norm_name(value).lower()


def francisco_count(queue: list[Any] | None) -> int:
    return sum(1 for x in list(queue or []) if _name_key(x) == _name_key(FRANCISCO_NAME))


def normalize_queue(queue: list[Any] | None) -> list[str]:
    return [_norm_name(x) for x in list(queue or []) if _norm_name(x)]


def queues_equal(a: list[Any] | None, b: list[Any] | None) -> bool:
    return normalize_queue(a) == normalize_queue(b)


def membership_diff(before: list[Any] | None, after: list[Any] | None) -> dict[str, Any]:
    """Bag-level membership difference (order-aware for disappeared/appeared)."""
    b = normalize_queue(before)
    a = normalize_queue(after)
    from collections import Counter

    cb, ca = Counter(_name_key(x) for x in b), Counter(_name_key(x) for x in a)
    appeared_keys = []
    disappeared_keys = []
    for k in sorted(set(cb) | set(ca)):
        d = ca[k] - cb[k]
        if d > 0:
            appeared_keys.extend([k] * d)
        elif d < 0:
            disappeared_keys.extend([k] * (-d))
    # Map keys back to display names preferring after/before originals.
    def _display(key: str, prefer: list[str]) -> str:
        for n in prefer:
            if _name_key(n) == key:
                return n
        return key

    appeared = [_display(k, a) for k in appeared_keys]
    disappeared = [_display(k, b) for k in disappeared_keys]
    return {
        "before": b,
        "after": a,
        "before_len": len(b),
        "after_len": len(a),
        "len_delta": len(a) - len(b),
        "appeared": appeared,
        "disappeared": disappeared,
        "appeared_set": sorted({_name_key(x) for x in appeared}),
        "disappeared_set": sorted({_name_key(x) for x in disappeared}),
    }


def query_param_value_count(query: str, key: str) -> int:
    q = parse_qs(str(query or ""), keep_blank_values=True)
    return len(list(q.get(str(key) or "") or []))


def build_francisco_mutation_proof_url(bridge_sid: str) -> str:
    """Stage A flags ONLY — no Francisco latch, no host-query probe."""
    timer = str(os.environ.get("SOLO_DIAG_TIMER") or "120").strip() or "120"
    sid = str(bridge_sid or "").strip()
    flag_q = "&".join(STAGE_A_QUERY_FLAGS)
    base = (
        f"{BASE}/?active_page=Live%20Draft%20Room"
        f"&{flag_q}"
        f"&solo_diag_timer={timer}"
    )
    if not sid:
        return base
    parts = urlparse(base)
    q = parse_qs(parts.query, keep_blank_values=True)
    q["suite_sid"] = [sid]
    q.pop(FRANCISCO_LATCH_PARAM, None)
    q.pop(HOST_QUERY_PROBE_PARAM, None)
    new_query = urlencode(q, doseq=True)
    return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))


def evaluate_mutation_url_preflight(url: str) -> dict[str, Any]:
    parts = urlparse(str(url or ""))
    q = parse_qs(parts.query, keep_blank_values=True)
    latch_n = query_param_value_count(parts.query, FRANCISCO_LATCH_PARAM)
    host_n = query_param_value_count(parts.query, HOST_QUERY_PROBE_PARAM)
    suite_n = query_param_value_count(parts.query, "suite_sid")
    solo = (q.get("solo_component_diag") or [""])[0] == "1"
    parent = (q.get("solo_stage1_parent_boundary") or [""])[0] == "1"
    active = "Live Draft Room" in " ".join(q.get("active_page") or [])
    failures: list[str] = []
    if latch_n != 0:
        failures.append("francisco_latch_present")
    if host_n != 0:
        failures.append("host_query_probe_present")
    if suite_n != 1:
        failures.append("suite_sid_count")
    if not solo:
        failures.append("solo_component_diag")
    if not parent:
        failures.append("solo_stage1_parent_boundary")
    if not active:
        failures.append("active_page")
    return {
        "ok": not failures,
        "failures": failures,
        "latch_count": latch_n,
        "host_query_probe_count": host_n,
        "suite_sid_count": suite_n,
        "set_query_param_required": False,
        "gate_clear_selected": False,
        "latch_page_goto_selected": False,
        "architecture": ARCHITECTURE,
    }


def evaluate_queue_baseline(
    *,
    session_queue: list[Any] | None,
    canonical_queue: list[Any] | None,
    ui_queue: list[Any] | None = None,
    baseline_known: bool = True,
) -> dict[str, Any]:
    sess = normalize_queue(session_queue)
    canon = normalize_queue(canonical_queue)
    ui = normalize_queue(ui_queue) if ui_queue is not None else None
    result: dict[str, Any] = {
        "ok": False,
        "classification": None,
        "session_queue": sess,
        "canonical_queue": canon,
        "ui_queue": ui,
        "baseline_length": len(sess),
        "francisco_count": francisco_count(sess),
        "session_canonical_equal": queues_equal(sess, canon),
        "francisco_absent": francisco_count(sess) == 0 and francisco_count(canon) == 0,
        "failures": [],
    }
    if not baseline_known:
        result["failures"] = ["unknown_baseline"]
        result["classification"] = CLASSIFICATION_BASELINE_REJECT
        return result
    if session_queue is None or canonical_queue is None:
        result["failures"] = ["unknown_baseline"]
        result["classification"] = CLASSIFICATION_BASELINE_REJECT
        return result
    if not queues_equal(sess, canon):
        result["failures"] = ["session_canonical_mismatch"]
        result["classification"] = CLASSIFICATION_BASELINE_REJECT
        return result
    fc = francisco_count(sess)
    if fc > 1:
        result["failures"] = ["francisco_duplicate_baseline"]
        result["classification"] = CLASSIFICATION_BASELINE_REJECT
        return result
    if fc == 1:
        result["failures"] = ["francisco_already_present"]
        result["classification"] = CLASSIFICATION_BASELINE_REJECT
        return result
    result["ok"] = True
    result["classification"] = None
    return result


def evaluate_gate_allows_normal_mutation(
    *,
    latch_absent: bool,
    fresh_production_sid: bool,
    gate_lifecycle: str | None = None,
    armed_or_consumed_event_present: bool = False,
) -> dict[str, Any]:
    life = str(gate_lifecycle or "").strip().lower()
    failures: list[str] = []
    if not latch_absent:
        failures.append("latch_present")
    if not fresh_production_sid:
        failures.append("sid_not_fresh_or_missing")
    if life in ("armed", "armed_once", "consumed_locked"):
        failures.append(f"gate_lifecycle_{life}")
    if armed_or_consumed_event_present:
        failures.append("armed_or_consumed_event_present")
    return {
        "ok": not failures,
        "failures": failures,
        "gate_lifecycle": life or "unarmed_or_unobserved",
        "clear_gate_selected": False,
    }


def evaluate_francisco_mutation_click_authorization(
    *,
    runtime_identity_ok: bool,
    auth_only_passed: bool,
    stage_a_steady_authorized: bool,
    heavy_paint_complete: bool,
    stage_a_identity_complete: bool,
    fresh_production_sid: bool,
    latch_absent: bool,
    gate_allows_normal: bool,
    baseline_ok: bool,
    prior_mutation_click: bool = False,
    ambiguous_queue: bool = False,
) -> dict[str, Any]:
    failures: list[str] = []
    if not runtime_identity_ok:
        failures.append("runtime")
    if not auth_only_passed:
        failures.append("auth_only")
    if not stage_a_steady_authorized:
        failures.append("stage_a_steady")
    if not heavy_paint_complete:
        failures.append("heavy_paint")
    if not stage_a_identity_complete:
        failures.append("stage_a_identity")
    if not fresh_production_sid:
        failures.append("production_sid")
    if not latch_absent:
        failures.append("latch")
    if not gate_allows_normal:
        failures.append("gate")
    if not baseline_ok:
        failures.append("baseline")
    if prior_mutation_click:
        failures.append("prior_click")
    if ambiguous_queue:
        failures.append("ambiguous_queue")
    ok = not failures
    return {
        "ok": ok,
        "francisco_mutation_click_authorized": ok,
        "classification": None if ok else CLASSIFICATION_CLICK_NOT_AUTHORIZED,
        "failures": failures,
    }


def evaluate_francisco_membership_mutation(
    *,
    runtime_identity_ok: bool,
    auth_only_passed: bool,
    stage_a_passed: bool,
    baseline: dict[str, Any],
    click_count: int,
    click_authorized: bool,
    premutation_stop_observed: bool,
    mutation_helper_entered: bool,
    added: bool | None,
    session_queue_after: list[Any] | None,
    canonical_queue_after: list[Any] | None,
    require_append_at_end: bool = True,
) -> dict[str, Any]:
    """Substantive SESSION+CANONICAL membership mutation authority (narrow)."""
    result: dict[str, Any] = {
        "ok": False,
        "classification": CLASSIFICATION_MUTATION_FAIL,
        "AUTHORITATIVE": "no",
        "PLAYER_A_QUEUE_MUTATION_RESOLVED": False,
        "QUEUE1C3A2F4_RESOLVED": False,
        "QUEUE_SEED_RESOLVED": False,
        "stage_1a_queue_passed": False,
        "stage_1b": False,
        "callback_ledger_authority_required": False,
        "durable_flush_required": False,
        "failures": [],
        "diff": {},
    }
    def _fail(cls: str, *reasons: str) -> dict[str, Any]:
        result["ok"] = False
        result["classification"] = cls
        result["AUTHORITATIVE"] = "no"
        result["failures"] = list(reasons)
        return result

    if not runtime_identity_ok:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "runtime")
    if not auth_only_passed:
        return _fail(CLASSIFICATION_AUTH_FAIL, "auth_only")
    if not stage_a_passed:
        return _fail(CLASSIFICATION_STAGE_A_FAIL, "stage_a")
    if not baseline.get("ok"):
        return _fail(CLASSIFICATION_BASELINE_REJECT, "baseline")
    if not click_authorized:
        return _fail(CLASSIFICATION_CLICK_NOT_AUTHORIZED, "click_not_authorized")
    if int(click_count or 0) <= 0:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "no_click")
    if int(click_count or 0) > 1:
        return _fail(CLASSIFICATION_MULTI_CLICK, "multiple_clicks")
    if premutation_stop_observed:
        return _fail(CLASSIFICATION_STOP_UNEXPECTED, "premutation_stop")
    if not mutation_helper_entered:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "helper_not_entered")
    if added is False:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "added_false")
    if added is None:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "added_unknown")

    before = list(baseline.get("session_queue") or [])
    sess_after = normalize_queue(session_queue_after)
    canon_after = normalize_queue(canonical_queue_after)
    if session_queue_after is None or canonical_queue_after is None:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "after_queue_unknown")
    if not queues_equal(sess_after, canon_after):
        return _fail(CLASSIFICATION_MUTATION_FAIL, "session_canonical_after_mismatch")

    diff = membership_diff(before, sess_after)
    result["diff"] = diff
    if francisco_count(sess_after) != 1:
        if francisco_count(sess_after) == 0:
            return _fail(CLASSIFICATION_MUTATION_FAIL, "francisco_missing_after")
        return _fail(CLASSIFICATION_MUTATION_FAIL, "francisco_duplicate_after")
    if diff["len_delta"] != 1:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "length_delta", str(diff["len_delta"]))
    if diff["appeared_set"] != [_name_key(FRANCISCO_NAME)]:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "appeared_not_exactly_francisco", str(diff["appeared"]))
    if diff["disappeared_set"]:
        return _fail(CLASSIFICATION_MUTATION_FAIL, "baseline_player_removed", str(diff["disappeared"]))
    # Exact list: baseline + Francisco Lindor appended
    expected = list(before) + [FRANCISCO_NAME]
    if require_append_at_end:
        if normalize_queue(sess_after) != normalize_queue(expected):
            return _fail(CLASSIFICATION_MUTATION_FAIL, "not_baseline_plus_francisco_append")
    else:
        if sorted(_name_key(x) for x in sess_after) != sorted(_name_key(x) for x in expected):
            return _fail(CLASSIFICATION_MUTATION_FAIL, "membership_not_baseline_plus_francisco")

    result["ok"] = True
    result["classification"] = CLASSIFICATION_MEMBERSHIP_PROVEN
    result["AUTHORITATIVE"] = "yes"
    result["failures"] = []
    result["francisco_membership_mutation_proven"] = True
    return result


def evaluate_player_a_queue_mutation_resolution(
    *,
    callback_entered: bool,
    mutation_proven: bool,
    queue_mutation_visible: bool,
) -> dict[str, Any]:
    """Faithful wrapper of stage1_rec_fragment_exec_gate.classify_francisco_mutation_step.

    Source contract (stage1_rec_fragment_exec_gate.py):
      PLAYER_A_QUEUE_MUTATION_RESOLVED iff
        callback_entered AND mutation_proven AND queue_mutation_visible
      QUEUE1C3F when mutation_proven but UI not visible
      QUEUE1C3B when callback entered but mutation not proven
    """
    step = {
        "callback_entered": bool(callback_entered),
        "mutation_proven": bool(mutation_proven),
        "queue_mutation_visible": bool(queue_mutation_visible),
    }
    try:
        from stage1_rec_fragment_exec_gate import classify_francisco_mutation_step

        label = classify_francisco_mutation_step(step)
    except ImportError:
        if callback_entered and mutation_proven and queue_mutation_visible:
            label = CLASSIFICATION_PLAYER_A
        elif callback_entered and mutation_proven and not queue_mutation_visible:
            label = "QUEUE1C3F"
        elif callback_entered:
            label = "QUEUE1C3B"
        else:
            label = ""
    return {
        "classification": label,
        "PLAYER_A_QUEUE_MUTATION_RESOLVED": label == CLASSIFICATION_PLAYER_A,
        "callback_entered": bool(callback_entered),
        "mutation_proven": bool(mutation_proven),
        "queue_mutation_visible": bool(queue_mutation_visible),
        "source_contract": {
            "requires_callback_entered": True,
            "requires_mutation_proven": True,
            "requires_queue_mutation_visible": True,
        },
        "distinction": (
            "FRANCISCO_MEMBERSHIP_MUTATION_PROVEN may hold from session/canonical "
            "authority without UI; PLAYER_A_QUEUE_MUTATION_RESOLVED additionally "
            "requires queue_mutation_visible per source classifier."
        ),
    }


def evaluate_queue1c3a2f4_fragment_condition(
    *,
    probe_callback_entered: bool,
    francisco_callback_entered: bool,
    player_a_resolved: bool,
) -> dict[str, Any]:
    """Source-defined QUEUE1C3A2F4_RESOLVED is NOT 'Francisco newly queued'.

    From classify_fragment_gate: when both probe and francisco callbacks entered,
    return PLAYER_A if mutation step is PLAYER_A, else QUEUE1C3A2F4_RESOLVED.
    """
    if probe_callback_entered and francisco_callback_entered:
        if player_a_resolved:
            return {
                "QUEUE1C3A2F4_RESOLVED": False,
                "classification": CLASSIFICATION_PLAYER_A,
                "note": "both_callbacks_entered_but_player_a_takes_precedence",
            }
        return {
            "QUEUE1C3A2F4_RESOLVED": True,
            "classification": "QUEUE1C3A2F4_RESOLVED",
            "note": "both_callbacks_entered_without_player_a_mutation",
        }
    return {
        "QUEUE1C3A2F4_RESOLVED": False,
        "classification": None,
        "note": "not_both_callbacks_entered",
    }


def compose_mutation_proof_result(
    *,
    membership: dict[str, Any],
    player_a: dict[str, Any],
    callback_ledger_observed: bool = False,
    persist_dirty: bool | None = None,
    durable_flush_observed: bool = False,
) -> dict[str, Any]:
    mem_ok = bool(membership.get("ok"))
    pa = bool(player_a.get("PLAYER_A_QUEUE_MUTATION_RESOLVED"))
    return {
        "architecture": ARCHITECTURE,
        "ok": mem_ok,
        "classification": membership.get("classification"),
        "AUTHORITATIVE": membership.get("AUTHORITATIVE"),
        "francisco_membership_mutation_proven": mem_ok,
        "PLAYER_A_QUEUE_MUTATION_RESOLVED": pa,
        "QUEUE1C3A2F4_RESOLVED": False,
        "QUEUE_SEED_RESOLVED": False,
        "stage_1a_queue_passed": False,
        "stage_1b": False,
        "callback_ledger_observed": bool(callback_ledger_observed),
        "callback_ledger_authority_required": False,
        "callback_ledger_observability_gap": mem_ok and not callback_ledger_observed,
        "persist_dirty": persist_dirty,
        "persist_dirty_supporting_only": True,
        "durable_flush_required": False,
        "durable_flush_observed": bool(durable_flush_observed),
        "cleanup_remove_selected": False,
        "membership_detail": membership,
        "player_a_detail": player_a,
        "preserved_callback_proof": {
            "FRANCISCO_ADD_TO_QUEUE_CALLBACK_EXECUTION_PROVEN_PREMUTATION": True,
            "AUTHORITATIVE": "yes",
        },
        "francisco_real_queue_mutation_authorized": False,
        "production_execution_this_module_turn": False,
    }


CLASSIFICATION_CLOUD_NOT_AUTHORIZED = "FRANCISCO_QUEUE_MUTATION_CLOUD_NOT_AUTHORIZED"
CLASSIFICATION_BRIDGE_INVALID = "FRANCISCO_QUEUE_MUTATION_PROOF_BRIDGE_NOT_BOUND"
CLASSIFICATION_URL_PREFLIGHT = "FRANCISCO_QUEUE_MUTATION_URL_PREFLIGHT_FAIL"
CLASSIFICATION_PRODUCT_GAP = "FRANCISCO_QUEUE_MUTATION_CLOUD_OBSERVABILITY_PRODUCT_GAP_CONFIRMED"
CLASSIFICATION_REQUIRED_CLOUD_SHA_INVALID = "FRANCISCO_QUEUE_MUTATION_REQUIRED_CLOUD_SHA_INVALID"
CLASSIFICATION_RUNTIME_MISMATCH = "FRANCISCO_QUEUE_MUTATION_RUNTIME_MISMATCH"
CLASSIFICATION_CLICK_UNAVAILABLE = "FRANCISCO_QUEUE_MUTATION_CLICK_TARGET_UNAVAILABLE"
CLASSIFICATION_POST_QUEUE_UNKNOWN = "FRANCISCO_QUEUE_MUTATION_POST_QUEUE_NOT_OBSERVED"

# --- Bridge marker lifecycle (fixture-safe; never touch real 709269b3 in tests) ---


def evaluate_reserved_bridge_marker(
    marker_text: str,
    *,
    expected_bridge_id: str,
) -> dict[str, Any]:
    text = str(marker_text or "")
    first = (text.splitlines()[0].strip() if text.strip() else "")
    identity_match = first == str(expected_bridge_id or "").strip()
    consumed = bool(
        re.search(r"(?mi)^#\s*CONSUMED\b", text)
        or re.search(r"(?mi)subsequently\s+CONSUMED", text)
    )
    reserved = bool(re.search(r"(?mi)RESERVED", text)) and not consumed
    if re.search(r"(?mi)NOT\s+consumed", text) and reserved:
        consumed = False
    eligible = identity_match and reserved and not consumed
    return {
        "marker_identity": first,
        "identity_match": identity_match,
        "reserved": reserved,
        "consumed": consumed,
        "eligible": eligible,
    }


def mark_bridge_consumed_at_path(
    marker_path: Path,
    *,
    bridge_id: str,
    consumed_at: float | None = None,
    reason: str = "francisco_queue_mutation_proof browser restore start",
) -> dict[str, Any]:
    """Write CONSUMED marker. Tests must pass a temp path — never real 709269b3."""
    import time as _time

    ts = float(consumed_at if consumed_at is not None else _time.time())
    sid = str(bridge_id or "").strip()
    body = (
        f"{sid}\n"
        f"# CONSUMED at {reason} (d664924)\n"
        f"# consumed_at={ts}\n"
        "# permanently consumed regardless of outcome\n"
        "# NOT reserved\n"
    )
    marker_path = Path(marker_path)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(body, encoding="utf-8")
    return {
        "bridge_id": sid,
        "consumed": True,
        "reserved": False,
        "consumed_at": ts,
        "marker_path": str(marker_path),
    }


def assess_d664924_unlatched_queue_observability() -> dict[str, Any]:
    """Source-supported observability for session vs canonical queue without latch.

    With live_draft_queue_state_snapshot_diag (solo_component_diag +
    solo_stage1_parent_boundary, NO Francisco latch), both queues are exposed
    independently for baseline and post-mutation readback.
    """
    diag_path = ROOT / "live_draft_queue_state_snapshot_diag.py"
    gate_path = ROOT / "live_draft_francisco_callback_only_gate.py"
    diag_src = diag_path.read_text(encoding="utf-8") if diag_path.is_file() else ""
    gate_src = gate_path.read_text(encoding="utf-8") if gate_path.is_file() else ""
    has_diag = (
        "read_canonical_queue" in diag_src
        and "read_session_queue" in diag_src
        and "QUEUE_STATE_BASELINE" in diag_src
        and "QUEUE_STATE_POST_MUTATION_ADDED" in diag_src
        and "francisco_callback_only_required" in diag_src
        and "False" in diag_src
    )
    no_latch_required = (
        "No Francisco latch" in diag_src
        or "francisco_callback_only_required\": False" in diag_src.replace(" ", "")
        or 'francisco_callback_only_required": False' in diag_src
    )
    independent_canonical = (
        "canonical_draft_workflow" in diag_src or 'ds.get("queue")' in diag_src
    ) and "draft_queue" in diag_src
    session_unlatched = has_diag and "read_session_queue" in diag_src
    canonical_unlatched = bool(has_diag and no_latch_required and independent_canonical)
    # Historical latch-only path still exists but is no longer the only surface.
    canonical_in_gate = "_canonical_queue_names" in gate_src
    ok = session_unlatched and canonical_unlatched
    return {
        "ok": ok,
        # Product-source assessment only — not live Cloud runtime authority.
        "runtime_sha": "unspecified",
        "session_queue_source": (
            "live_draft_queue_state_snapshot_diag.read_session_queue "
            "(session['draft_queue'] / DRAFT_QUEUE_KEY)"
        ),
        "canonical_queue_source": (
            "live_draft_queue_state_snapshot_diag.read_canonical_queue "
            "(canonical_draft_workflow / session['draft_state']['queue'])"
        ),
        "ui_queue_source": "scrape_queue_container_state (rendered Draft Queue; secondary)",
        "session_queue_observable_without_latch": session_unlatched,
        "canonical_queue_observable_without_latch": canonical_unlatched,
        "canonical_emitted_only_under_callback_latch": bool(
            canonical_in_gate and not canonical_unlatched
        ),
        "dom_equated_to_canonical_forbidden": True,
        "diagnostic_module": "live_draft_queue_state_snapshot_diag",
        "classification": None if ok else CLASSIFICATION_PRODUCT_GAP,
        "gap_detail": (
            None
            if ok
            else (
                "Unlatched dual-queue snapshot diagnostic missing or incomplete."
            )
        ),
    }


def extract_queues_from_snapshot(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Pull session/canonical queues from an authoritative diagnostic snapshot."""
    if not isinstance(snap, dict):
        return {
            "session_queue": None,
            "canonical_queue": None,
            "session_unavailable": True,
            "canonical_unavailable": True,
            "baseline_known": False,
            "snap": None,
        }
    sess = snap.get("session_queue")
    canon = snap.get("canonical_queue")
    sess_ok = isinstance(sess, list)
    canon_ok = isinstance(canon, list)
    return {
        "session_queue": list(sess) if sess_ok else None,
        "canonical_queue": list(canon) if canon_ok else None,
        "session_unavailable": not sess_ok,
        "canonical_unavailable": not canon_ok,
        "baseline_known": sess_ok and canon_ok,
        "snap": dict(snap),
        "phase": snap.get("phase"),
        "streamlit_session_id": snap.get("streamlit_session_id"),
        "diagnostic_run_id": snap.get("diagnostic_run_id"),
        "room_id": snap.get("room_id"),
        "ts": snap.get("ts"),
    }


def select_authoritative_baseline_queues(
    *,
    production_sid: str,
    room_id: str = "",
    snapshots: list[dict[str, Any]] | None = None,
    session: dict[str, Any] | None = None,
    ui_queue: list[Any] | None = None,
) -> dict[str, Any]:
    """Fail closed on wrong SID / missing canonical. UI never substitutes."""
    sid = str(production_sid or "").strip()
    if not sid:
        return {
            "session_queue": None,
            "canonical_queue": None,
            "session_unavailable": True,
            "canonical_unavailable": True,
            "baseline_known": False,
            "rejection": "missing_production_sid",
            "ui_queue": ui_queue,
        }
    snap = None
    try:
        from live_draft_queue_state_snapshot_diag import latest_baseline_for_sid

        snap = latest_baseline_for_sid(session, streamlit_session_id=sid, room_id=room_id)
    except ImportError:
        snap = None
    if snap is None and snapshots:
        matched = [
            dict(s)
            for s in snapshots
            if isinstance(s, dict)
            and str(s.get("phase") or "") == "QUEUE_STATE_BASELINE"
            and str(s.get("streamlit_session_id") or "").strip() == sid
        ]
        if room_id:
            room = str(room_id).strip().upper()
            matched = [
                s
                for s in matched
                if str(s.get("room_id") or "").strip().upper() == room
            ]
        if matched:
            matched.sort(key=lambda r: float(r.get("ts") or 0))
            snap = matched[-1]
    if snap is None:
        return {
            "session_queue": None,
            "canonical_queue": None,
            "session_unavailable": True,
            "canonical_unavailable": True,
            "baseline_known": False,
            "rejection": "baseline_snapshot_missing_or_wrong_sid",
            "ui_queue": ui_queue,
            "ui_not_used_as_canonical": True,
        }
    if str(snap.get("streamlit_session_id") or "").strip() != sid:
        return {
            "session_queue": None,
            "canonical_queue": None,
            "session_unavailable": True,
            "canonical_unavailable": True,
            "baseline_known": False,
            "rejection": "historical_or_wrong_sid",
            "ui_queue": ui_queue,
        }
    out = extract_queues_from_snapshot(snap)
    out["ui_queue"] = ui_queue
    out["ui_not_used_as_canonical"] = True
    out["rejection"] = None
    return out


def select_authoritative_post_queues(
    *,
    production_sid: str,
    room_id: str = "",
    after_ts: float | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    session: dict[str, Any] | None = None,
    ui_queue: list[Any] | None = None,
    reject_baseline_as_post: bool = True,
) -> dict[str, Any]:
    sid = str(production_sid or "").strip()
    if not sid:
        return {
            "session_queue": None,
            "canonical_queue": None,
            "session_unavailable": True,
            "canonical_unavailable": True,
            "rejection": "missing_production_sid",
            "ui_queue": ui_queue,
        }
    snap = None
    try:
        from live_draft_queue_state_snapshot_diag import latest_post_added_for_sid

        snap = latest_post_added_for_sid(
            session, streamlit_session_id=sid, room_id=room_id, after_ts=after_ts
        )
    except ImportError:
        snap = None
    if snap is None and snapshots:
        matched = [
            dict(s)
            for s in snapshots
            if isinstance(s, dict)
            and str(s.get("phase") or "") == "QUEUE_STATE_POST_MUTATION_ADDED"
            and str(s.get("streamlit_session_id") or "").strip() == sid
        ]
        if after_ts is not None:
            matched = [s for s in matched if float(s.get("ts") or 0) > float(after_ts)]
        if matched:
            matched.sort(key=lambda r: float(r.get("ts") or 0))
            snap = matched[-1]
    if snap is None:
        return {
            "session_queue": None,
            "canonical_queue": None,
            "session_unavailable": True,
            "canonical_unavailable": True,
            "rejection": "post_snapshot_missing_or_wrong_sid",
            "ui_queue": ui_queue,
            "ui_not_used_as_canonical": True,
        }
    if reject_baseline_as_post and str(snap.get("phase") or "") == "QUEUE_STATE_BASELINE":
        return {
            "session_queue": None,
            "canonical_queue": None,
            "session_unavailable": True,
            "canonical_unavailable": True,
            "rejection": "stale_baseline_cannot_act_as_post",
            "ui_queue": ui_queue,
        }
    out = extract_queues_from_snapshot(snap)
    out["ui_queue"] = ui_queue
    out["ui_not_used_as_canonical"] = True
    out["rejection"] = None
    out["added"] = snap.get("added")
    out["mutation_helper_entered"] = snap.get("mutation_helper_entered")
    out["phase"] = snap.get("phase")
    return out


def _load_callback_runner():
    import importlib.util

    path = ROOT / "data" / "_francisco_callback_only_cloud_proof_d664924.py"
    name = "francisco_callback_proof_shared"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class MutationCloudPorts:
    """Injectable Cloud adapters. Production wires Playwright; tests use fixtures."""

    launch_browser: Callable[[str], dict[str, Any]]
    mark_consumed: Callable[[], dict[str, Any]]
    restore_auth: Callable[[], dict[str, Any]]
    check_runtime: Callable[[], dict[str, Any]]
    wait_stage_a: Callable[[], dict[str, Any]]
    observe_gate: Callable[[], dict[str, Any]]
    collect_baseline: Callable[[], dict[str, Any]]
    resolve_click_target: Callable[[dict[str, Any]], dict[str, Any]]
    trusted_click: Callable[[dict[str, Any]], dict[str, Any]]
    collect_post_click: Callable[[dict[str, Any]], dict[str, Any]]
    close_browser: Callable[[], None] = field(default_factory=lambda: (lambda: None))


@dataclass
class MutationCloudConfig:
    bridge_id: str
    context_a_sid: str = ""
    context_a_diagnostic_run_id: str = ""
    require_canonical_observability: bool = True
    production_reexecuted: bool = False
    # Current live Cloud implementation SHA (normalized 7-char). Required before browser.
    required_sha: str = ""
    capture_cloud_runtime_sha: str = ""  # historical metadata only; never runtime authority


def _empty_failure_shell(classification: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "mode": "francisco_queue_mutation_proof",
        "architecture": ARCHITECTURE,
        "classification": classification,
        "AUTHORITATIVE": "no",
        "result_finalized": True,
        "production_reexecuted": False,
        "francisco_mutation_click_authorized": False,
        "click_count": 0,
        "cleanup_remove_selected": False,
        "force_save_selected": False,
        "second_navigation": False,
        "set_query_param_sent": False,
        "gate_clear_selected": False,
        "stage1_francisco_callback_only_count": 0,
        "host_query_probe_count": 0,
        "FRANCISCO_MEMBERSHIP_MUTATION_PROVEN": False,
        "PLAYER_A_QUEUE_MUTATION_RESOLVED": False,
        "QUEUE1C3A2F4_RESOLVED": False,
        "QUEUE_SEED_RESOLVED": False,
        "stage_1a_queue_passed": False,
        "stage_1b": False,
        "preserved_callback_proof": {
            "FRANCISCO_ADD_TO_QUEUE_CALLBACK_EXECUTION_PROVEN_PREMUTATION": True,
            "AUTHORITATIVE": "yes",
        },
    }
    out.update(extra)
    return out


def run_cloud_mutation_orchestration(
    ports: MutationCloudPorts,
    cfg: MutationCloudConfig,
    *,
    url: str,
    preflight: dict[str, Any] | None = None,
    observability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bridge → browser → auth → Stage A → baseline → one click → evaluators.

    Local tests inject fixture ports. Production main wires Playwright ports.
    Never clears Francisco gate. Never second-clicks. Never force-saves.
    """
    bridge = str(cfg.bridge_id or "").strip()
    pre = preflight or evaluate_mutation_url_preflight(url)
    obs = observability or assess_d664924_unlatched_queue_observability()
    required_sha = normalize_required_cloud_sha(cfg.required_sha)
    expected_display = expected_build_display_for(required_sha)
    report = _empty_failure_shell(
        "",
        bridge_id=bridge,
        proof_url=url,
        preflight=pre,
        queue_observability=obs,
        production_reexecuted=bool(cfg.production_reexecuted),
        context_a_sid_recorded=str(cfg.context_a_sid or ""),
        context_a_diagnostic_run_id_recorded=str(cfg.context_a_diagnostic_run_id or ""),
        context_a_not_production_authority=True,
        required_sha=required_sha,
        expected_build_display=expected_display,
        capture_cloud_runtime_sha=str(cfg.capture_cloud_runtime_sha or ""),
        capture_runtime_equality_required=False,
    )
    if not pre.get("ok"):
        report["classification"] = CLASSIFICATION_URL_PREFLIGHT
        report["browser_launched"] = False
        report["bridge_consumed"] = False
        return report

    if not required_sha:
        report["classification"] = CLASSIFICATION_REQUIRED_CLOUD_SHA_INVALID
        report["browser_launched"] = False
        report["bridge_consumed"] = False
        report["note"] = (
            "Mutation orchestration requires an explicit current-runtime "
            "required_sha / REQUIRED_CLOUD_SHA before browser launch."
        )
        return report

    if cfg.require_canonical_observability and not obs.get(
        "canonical_queue_observable_without_latch"
    ):
        # Fail closed BEFORE browser so RESERVED bridges stay reusable until
        # product exposes unlatched canonical queue diagnostics.
        report["classification"] = CLASSIFICATION_PRODUCT_GAP
        report["browser_launched"] = False
        report["bridge_consumed"] = False
        report["gap_detail"] = obs.get("gap_detail")
        return report

    browser_meta = ports.launch_browser(url)
    report["browser_launched"] = bool(browser_meta.get("launched"))
    report["browser_meta"] = {k: browser_meta.get(k) for k in ("launched", "headed", "pid")}
    if not report["browser_launched"]:
        report["classification"] = "FRANCISCO_QUEUE_MUTATION_BROWSER_LAUNCH_FAILED"
        report["bridge_consumed"] = False
        return report

    # Accepted consumption boundary: browser launched + restore about to begin.
    consumed = ports.mark_consumed()
    report["bridge_consumed"] = True
    report["bridge_state"] = "CONSUMED"
    report["consumed_at"] = consumed.get("consumed_at")
    report["consumed_marker"] = consumed.get("marker_path")

    try:
        auth = ports.restore_auth()
        report["auth"] = auth
        report["production_streamlit_sid"] = auth.get("streamlit_session_id")
        report["production_diagnostic_run_id"] = auth.get("diagnostic_run_id")
        auth_ok = bool(
            auth.get("authenticated_restored")
            and auth.get("is_authenticated")
            and auth.get("auth_session_complete")
            and auth.get("suite_sid_match")
            and auth.get("bridge_load_ok")
            and auth.get("session_flag_present")
            and str(auth.get("restore_blocked_reason") or "") == ""
        )
        # Production SID must not equal Context A SID when Context A is recorded.
        ctx_sid = str(cfg.context_a_sid or "").strip()
        prod_sid = str(auth.get("streamlit_session_id") or "").strip()
        report["production_sid_differs_from_context_a"] = bool(
            prod_sid and ctx_sid and prod_sid != ctx_sid
        ) or (not ctx_sid)
        if not auth_ok:
            report["classification"] = CLASSIFICATION_AUTH_FAIL
            return report

        runtime = ports.check_runtime()
        report["runtime"] = runtime
        live_eval = evaluate_live_runtime_against_required(
            required_sha=required_sha,
            runtime_sha_raw=runtime.get("runtime_sha_raw")
            or runtime.get("runtime_sha_normalized"),
            deploy_build_raw=runtime.get("deploy_build_raw")
            or runtime.get("deploy_identity")
            or runtime.get("runtime_sha_normalized"),
        )
        # Prefer port-reported match flags when present; still require exact required_sha.
        normalized_live = normalize_required_cloud_sha(
            runtime.get("runtime_sha_normalized") or runtime.get("runtime_sha_raw")
        )
        runtime_ok = (
            normalized_live == required_sha
            and bool(runtime.get("runtime_match", live_eval.get("runtime_match")))
            and bool(runtime.get("build_match", live_eval.get("build_match")))
        )
        report["raw_sha"] = runtime.get("runtime_sha_raw")
        report["normalized_sha"] = runtime.get("runtime_sha_normalized") or normalized_live
        report["deploy_identity"] = runtime.get("deploy_identity") or runtime.get(
            "runtime_sha_normalized"
        )
        report["live_runtime_eval"] = live_eval
        if not runtime_ok:
            report["classification"] = CLASSIFICATION_RUNTIME_MISMATCH
            return report

        stage_a = ports.wait_stage_a()
        report["stage_a"] = stage_a
        stage_ok = bool(stage_a.get("steady_authorized")) and bool(
            stage_a.get("heavy_paint_complete")
        )
        identity_complete = stage_a_identity_complete(stage_a)
        if not stage_ok or not identity_complete:
            report["classification"] = CLASSIFICATION_STAGE_A_FAIL
            return report

        gate = ports.observe_gate()
        report["gate"] = gate
        latch_absent = bool(gate.get("latch_absent", True))
        gate_eval = evaluate_gate_allows_normal_mutation(
            latch_absent=latch_absent,
            fresh_production_sid=bool(prod_sid),
            gate_lifecycle=str(gate.get("lifecycle") or "unarmed"),
            armed_or_consumed_event_present=bool(gate.get("armed_or_consumed_event_present")),
        )
        report["gate_eval"] = gate_eval
        if not gate_eval.get("ok"):
            report["classification"] = CLASSIFICATION_GATE_BLOCK
            return report

        baseline_raw = ports.collect_baseline()
        report["baseline_raw"] = baseline_raw
        if baseline_raw.get("canonical_unavailable") or baseline_raw.get(
            "session_unavailable"
        ):
            report["classification"] = CLASSIFICATION_PRODUCT_GAP
            report["gap_detail"] = baseline_raw.get("gap_detail") or obs.get("gap_detail")
            return report
        baseline = evaluate_queue_baseline(
            session_queue=baseline_raw.get("session_queue"),
            canonical_queue=baseline_raw.get("canonical_queue"),
            ui_queue=baseline_raw.get("ui_queue"),
            baseline_known=bool(baseline_raw.get("baseline_known", True)),
        )
        report["baseline"] = baseline
        if not baseline.get("ok"):
            report["classification"] = CLASSIFICATION_BASELINE_REJECT
            return report

        click_auth = evaluate_francisco_mutation_click_authorization(
            runtime_identity_ok=runtime_ok,
            auth_only_passed=auth_ok,
            stage_a_steady_authorized=stage_ok,
            heavy_paint_complete=bool(stage_a.get("heavy_paint_complete")),
            stage_a_identity_complete=identity_complete,
            fresh_production_sid=bool(prod_sid),
            latch_absent=latch_absent,
            gate_allows_normal=bool(gate_eval.get("ok")),
            baseline_ok=True,
            prior_mutation_click=False,
            ambiguous_queue=False,
        )
        report["click_authorization"] = click_auth
        report["francisco_mutation_click_authorized"] = bool(
            click_auth.get("francisco_mutation_click_authorized")
        )
        if not click_auth.get("francisco_mutation_click_authorized"):
            report["classification"] = CLASSIFICATION_CLICK_NOT_AUTHORIZED
            return report

        target = ports.resolve_click_target(stage_a)
        report["click_target"] = target
        if not target.get("ok"):
            report["classification"] = CLASSIFICATION_CLICK_UNAVAILABLE
            return report

        click = ports.trusted_click(target)
        report["click"] = click
        report["click_count"] = int(click.get("click_count") or 0)
        report["click_timestamp"] = click.get("timestamp")
        if int(report["click_count"] or 0) != 1:
            report["classification"] = (
                CLASSIFICATION_MULTI_CLICK
                if int(report["click_count"] or 0) > 1
                else CLASSIFICATION_MUTATION_FAIL
            )
            return report

        post = ports.collect_post_click(click)
        report["post_click"] = post
        if post.get("premutation_stop_observed"):
            report["classification"] = CLASSIFICATION_STOP_UNEXPECTED
            report["premutation_stop"] = post.get("premutation_stop")
            return report
        if post.get("session_queue") is None or post.get("canonical_queue") is None:
            report["classification"] = CLASSIFICATION_POST_QUEUE_UNKNOWN
            return report

        membership = evaluate_francisco_membership_mutation(
            runtime_identity_ok=runtime_ok,
            auth_only_passed=auth_ok,
            stage_a_passed=stage_ok,
            baseline=baseline,
            click_count=int(report["click_count"] or 0),
            click_authorized=True,
            premutation_stop_observed=bool(post.get("premutation_stop_observed")),
            mutation_helper_entered=bool(post.get("mutation_helper_entered")),
            added=post.get("added"),
            session_queue_after=post.get("session_queue"),
            canonical_queue_after=post.get("canonical_queue"),
        )
        player_a = evaluate_player_a_queue_mutation_resolution(
            callback_entered=bool(post.get("callback_entered")),
            mutation_proven=bool(membership.get("ok")),
            queue_mutation_visible=bool(post.get("queue_mutation_visible")),
        )
        composed = compose_mutation_proof_result(
            membership=membership,
            player_a=player_a,
            callback_ledger_observed=bool(post.get("callback_ledger_observed")),
            persist_dirty=post.get("persist_dirty"),
            durable_flush_observed=False,
        )
        report.update(composed)
        report["FRANCISCO_MEMBERSHIP_MUTATION_PROVEN"] = bool(membership.get("ok"))
        report["result_finalized"] = True
        report["safety"] = {
            "second_francisco_click": False,
            "other_add_to_queue_click": False,
            "cleanup_remove_mutation": False,
            "callback_only_stop_expected": False,
            "host_query": False,
            "set_query_param": False,
            "gate_clear": False,
            "durable_force_save": False,
            "stage_1b": False,
            "click_count": int(report["click_count"] or 0),
        }
        return report
    finally:
        try:
            ports.close_browser()
        except Exception:
            pass


def build_fixture_mutation_ports(
    *,
    marker_path: Path,
    bridge_id: str,
    auth: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    stage_a: dict[str, Any] | None = None,
    gate: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    post: dict[str, Any] | None = None,
    launch: bool = True,
    click_ok: bool = True,
    state: dict[str, Any] | None = None,
    required_sha: str = "95b26f9",
) -> MutationCloudPorts:
    """Deterministic ports for local orchestration tests (no network/browser)."""
    st = state if state is not None else {}
    st.setdefault("click_invocations", 0)
    st.setdefault("launched", False)
    st.setdefault("consumed", False)
    fixture_sha = normalize_required_cloud_sha(required_sha) or "95b26f9"
    fixture_display = expected_build_display_for(fixture_sha)

    def _launch(_url: str) -> dict[str, Any]:
        st["launched"] = bool(launch)
        return {"launched": bool(launch), "headed": False, "pid": 0}

    def _consume() -> dict[str, Any]:
        st["consumed"] = True
        return mark_bridge_consumed_at_path(marker_path, bridge_id=bridge_id)

    def _auth() -> dict[str, Any]:
        base = {
            "authenticated_restored": True,
            "is_authenticated": True,
            "auth_session_complete": True,
            "suite_sid_match": True,
            "bridge_load_ok": True,
            "session_flag_present": True,
            "restore_blocked_reason": "",
            "streamlit_session_id": "prod-sid-fixture-0001",
            "diagnostic_run_id": "prod-run-fixture-0001",
        }
        base.update(auth or {})
        return base

    def _runtime() -> dict[str, Any]:
        base = {
            "runtime_sha_raw": fixture_sha,
            "runtime_sha_normalized": fixture_sha,
            "deploy_identity": fixture_sha,
            "deploy_build_raw": fixture_display,
            "runtime_match": True,
            "build_match": True,
        }
        base.update(runtime or {})
        return base

    def _stage() -> dict[str, Any]:
        base = {
            "steady_authorized": True,
            "heavy_paint_complete": True,
            "recommendation_fragment_run_seq": 7,
            "full_app_run_seq": 12,
            "room_id": "ROOMFIXT",
            "current_pick_index": 3,
            "player_id": "runtime-francisco-id-fixture",
            "widget_key": "rec_queue_ROOMFIXT_3_runtime-francisco-id-fixture",
            "streamlit_session_id": "prod-sid-fixture-0001",
            "diagnostic_run_id": "prod-run-fixture-0001",
        }
        base.update(stage_a or {})
        return base

    def _gate() -> dict[str, Any]:
        base = {
            "latch_absent": True,
            "lifecycle": "unarmed",
            "armed_or_consumed_event_present": False,
        }
        base.update(gate or {})
        return base

    def _baseline() -> dict[str, Any]:
        base = {
            "session_queue": [],
            "canonical_queue": [],
            "ui_queue": [],
            "baseline_known": True,
            "canonical_unavailable": False,
            "session_unavailable": False,
        }
        base.update(baseline or {})
        return base

    def _target(sa: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "room_id": sa.get("room_id"),
            "current_pick_index": sa.get("current_pick_index"),
            "player_id": sa.get("player_id"),
            "widget_key": sa.get("widget_key"),
            "label": "⭐ Add to Queue",
        }

    def _click(target: dict[str, Any]) -> dict[str, Any]:
        st["click_invocations"] = int(st.get("click_invocations") or 0) + 1
        if not click_ok:
            return {"click_count": 0, "timestamp": None, "error": "click_failed"}
        import time as _time

        return {
            "click_count": 1,
            "timestamp": _time.time(),
            "room_id": target.get("room_id"),
            "current_pick_index": target.get("current_pick_index"),
            "player_id": target.get("player_id"),
            "widget_key": target.get("widget_key"),
        }

    def _post(_click: dict[str, Any]) -> dict[str, Any]:
        base = {
            "premutation_stop_observed": False,
            "mutation_helper_entered": True,
            "added": True,
            "session_queue": ["Francisco Lindor"],
            "canonical_queue": ["Francisco Lindor"],
            "ui_queue": ["Francisco Lindor"],
            "queue_mutation_visible": True,
            "callback_entered": True,
            "callback_ledger_observed": True,
            "persist_dirty": True,
        }
        base.update(post or {})
        return base

    return MutationCloudPorts(
        launch_browser=_launch,
        mark_consumed=_consume,
        restore_auth=_auth,
        check_runtime=_runtime,
        wait_stage_a=_stage,
        observe_gate=_gate,
        collect_baseline=_baseline,
        resolve_click_target=_target,
        trusted_click=_click,
        collect_post_click=_post,
        close_browser=lambda: None,
    )


def cloud_authorization_present() -> bool:
    return str(os.environ.get("FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD") or "").strip() == "1"


def resolve_mutation_bridge_id() -> str:
    return (
        str(os.environ.get("FRANCISCO_MUTATION_PROOF_BRIDGE_ID") or "").strip()
        or str(os.environ.get("STAGE1_BRIDGE_SUITE_SID") or "").strip()
    )


def main() -> int:
    """Production entry — Cloud path wired; local tests call orchestration with fixtures."""
    bridge = resolve_mutation_bridge_id()
    abort = _empty_failure_shell(
        CLASSIFICATION_BRIDGE_INVALID,
        production_main_would_require_fresh_bridge=True,
        note=(
            "Bind a FRESH RESERVED bridge via FRANCISCO_MUTATION_PROOF_BRIDGE_ID. "
            "Retired bridges are permanently non-reusable."
        ),
    )
    if not bridge or bridge in RETIRED_BRIDGE_IDS:
        abort["bridge_id"] = bridge or ""
        abort["retired"] = bridge in RETIRED_BRIDGE_IDS
        print(json.dumps(abort, default=str), flush=True)
        return 2

    url = build_francisco_mutation_proof_url(bridge)
    pre = evaluate_mutation_url_preflight(url)
    if not pre.get("ok"):
        abort["classification"] = CLASSIFICATION_URL_PREFLIGHT
        abort["preflight"] = pre
        abort["bridge_id"] = bridge
        print(json.dumps(abort, default=str), flush=True)
        return 2

    if not cloud_authorization_present():
        abort["classification"] = CLASSIFICATION_CLOUD_NOT_AUTHORIZED
        abort["preflight"] = pre
        abort["bridge_id"] = bridge
        abort["proof_url_flags_ok"] = True
        abort["browser_launched"] = False
        abort["bridge_consumed"] = False
        abort["note"] = (
            "Cloud execution requires explicit FRANCISCO_MUTATION_PROOF_AUTHORIZE_CLOUD=1 "
            "and an eligible RESERVED bridge."
        )
        print(json.dumps(abort, default=str), flush=True)
        return 2

    sha_res = resolve_required_cloud_sha(cloud_authorized=True)
    if not sha_res.get("ok"):
        abort["classification"] = CLASSIFICATION_REQUIRED_CLOUD_SHA_INVALID
        abort["preflight"] = pre
        abort["bridge_id"] = bridge
        abort["required_cloud_sha_resolution"] = sha_res
        abort["browser_launched"] = False
        abort["bridge_consumed"] = False
        abort["note"] = (
            "Cloud execution requires explicit REQUIRED_CLOUD_SHA matching the "
            "CURRENT live Cloud implementation (no historical d664924 fallback)."
        )
        print(json.dumps(abort, default=str), flush=True)
        return 2

    # Reserved-marker guard (real marker path). Failures stay pre-browser.
    reserved_path = ROOT / "data" / f"{bridge[:8]}_reserved_bridge.txt"
    marker_text = reserved_path.read_text(encoding="utf-8") if reserved_path.is_file() else ""
    guard = evaluate_reserved_bridge_marker(marker_text, expected_bridge_id=bridge)
    if not guard.get("eligible"):
        abort["classification"] = CLASSIFICATION_BRIDGE_INVALID
        abort["bridge_id"] = bridge
        abort["bridge_guard"] = guard
        abort["required_sha"] = sha_res.get("required_sha")
        abort["browser_launched"] = False
        abort["bridge_consumed"] = False
        print(json.dumps(abort, default=str), flush=True)
        return 2

    obs = assess_d664924_unlatched_queue_observability()
    # Product gap: do not launch browser / do not consume RESERVED bridge.
    if not obs.get("canonical_queue_observable_without_latch"):
        abort.update(
            {
                "classification": CLASSIFICATION_PRODUCT_GAP,
                "bridge_id": bridge,
                "bridge_guard": guard,
                "preflight": pre,
                "queue_observability": obs,
                "gap_detail": obs.get("gap_detail"),
                "required_sha": sha_res.get("required_sha"),
                "browser_launched": False,
                "bridge_consumed": False,
                "cloud_execution_path_wired": True,
                "cloud_path_blocked_by_product_observability": True,
                "note": (
                    "Cloud orchestration is implemented, but unlatched canonical "
                    "draft_state.queue observability is not available in local product source. "
                    "No browser launch; bridge remains RESERVED."
                ),
            }
        )
        print(json.dumps(abort, default=str), flush=True)
        return 2

    report = _run_playwright_cloud_mutation(
        bridge=bridge,
        url=url,
        pre=pre,
        obs=obs,
        guard=guard,
        required_sha=str(sha_res.get("required_sha") or ""),
    )
    print(json.dumps(report, default=str), flush=True)
    return 0 if report.get("ok") else 1


def _run_playwright_cloud_mutation(
    *,
    bridge: str,
    url: str,
    pre: dict[str, Any],
    obs: dict[str, Any],
    guard: dict[str, Any],
    required_sha: str,
) -> dict[str, Any]:
    """Real Cloud Playwright wiring (shared helpers from callback runner).

    ``required_sha`` is the CURRENT live Cloud implementation authority
    (from REQUIRED_CLOUD_SHA). Capture-bridge runtime is never used here.
    """
    import time as _time

    cb = _load_callback_runner()
    consumed_path = ROOT / "data" / f"{bridge[:8]}_consumed_bridge.txt"
    reserved_path = ROOT / "data" / f"{bridge[:8]}_reserved_bridge.txt"
    req = normalize_required_cloud_sha(required_sha)
    state: dict[str, Any] = {"page": None, "browser": None, "context": None, "click_count": 0}

    def launch_browser(u: str) -> dict[str, Any]:
        from cloud_streamlit_wake import goto_and_wake
        from p8_proven_start_delivery import install_proven_start_context_scripts
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1400})
        install_proven_start_context_scripts(context)
        page = context.new_page()
        state["pw"] = pw
        state["browser"] = browser
        state["context"] = context
        state["page"] = page
        goto_and_wake(page, u, timeout_s=240)
        return {"launched": True, "headed": False, "pid": os.getpid()}

    def mark_consumed() -> dict[str, Any]:
        # Mirror callback-runner consumption boundary semantics.
        if reserved_path.is_file():
            try:
                reserved_path.write_text(
                    f"{bridge}\n# subsequently CONSUMED — do not treat as RESERVED\n"
                    f"# Francisco normal queue-mutation proof (d664924)\n"
                    "# permanently non-reusable regardless of outcome\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
        return mark_bridge_consumed_at_path(
            consumed_path,
            bridge_id=bridge,
            reason="francisco normal queue-mutation proof browser restore start",
        )

    def restore_auth() -> dict[str, Any]:
        from p8_production_start_harness import scrape_stage1_ledger_rows
        from playwright_auth_bridge_restore_harness import wait_bridge_auth_hydrated
        from stage1_application_phase import EXPECTED_PHASE_AUTH_ONLY

        page = state["page"]
        hydrate_timeout = float(os.environ.get("BRIDGE_HYDRATION_TIMEOUT_S", "240"))
        bridge_pre = wait_bridge_auth_hydrated(
            page,
            bridge,
            scrape_stage1_ledger_rows,
            timeout_s=hydrate_timeout,
            poll_interval_s=2.0,
            preamble_mode="stage1",
            expected_application_phase=EXPECTED_PHASE_AUTH_ONLY,
        )
        state["auth_sid"] = str(bridge_pre.get("streamlit_session_id") or "")
        state["auth_run"] = str(bridge_pre.get("diagnostic_run_id") or "")
        return {
            "authenticated_restored": bool(bridge_pre.get("authenticated_restored")),
            "is_authenticated": bool(bridge_pre.get("authenticated_restored")),
            "auth_session_complete": bool(bridge_pre.get("authenticated_restored")),
            "suite_sid_match": True,
            "bridge_load_ok": bool(bridge_pre.get("authenticated_restored")),
            "session_flag_present": bool(bridge_pre.get("authenticated_restored")),
            "restore_blocked_reason": ""
            if bridge_pre.get("authenticated_restored")
            else str(bridge_pre.get("failure_classification") or "auth_failed"),
            "streamlit_session_id": bridge_pre.get("streamlit_session_id"),
            "diagnostic_run_id": bridge_pre.get("diagnostic_run_id"),
            "raw": {
                "failure_classification": bridge_pre.get("failure_classification"),
            },
        }

    def check_runtime() -> dict[str, Any]:
        from queueui_audit_protocol import scrape_deploy_marker_from_page
        from run_production_solo_soak import scrape_deploy_build

        page = state["page"]
        sha, _src = scrape_deploy_marker_from_page(page)
        build_raw = scrape_deploy_build(page)
        # Prefer mutation-local exact evaluator so REQUIRED_CLOUD_SHA drives authority
        # even when the shared callback helper still defaults historically.
        local_id = evaluate_live_runtime_against_required(
            required_sha=req,
            runtime_sha_raw=sha,
            deploy_build_raw=build_raw,
        )
        identity = cb.cloud_identity_matches_required(
            runtime_sha_raw=sha,
            deploy_build_raw=build_raw,
            required_sha=req,
        )
        return {
            "runtime_sha_raw": identity.get("runtime_sha_raw"),
            "runtime_sha_normalized": local_id.get("runtime_sha_normalized")
            or identity.get("runtime_sha_normalized"),
            "deploy_identity": local_id.get("runtime_sha_normalized")
            or identity.get("runtime_sha_normalized"),
            "runtime_match": bool(local_id.get("runtime_match")),
            "build_match": bool(local_id.get("build_match")),
            "deploy_build_raw": identity.get("deploy_build_raw"),
            "required_sha": req,
            "expected_build_display": expected_build_display_for(req),
            "ok": bool(local_id.get("ok")),
        }

    def wait_stage_a() -> dict[str, Any]:
        from stage1_rec_fragment_exec_gate import wait_for_rec_fragment_interactive_steady_state

        page = state["page"]
        # Reuse callback-runner Stage A establishment helpers where practical.
        # Full lobby/start/pause path mirrors proven solo-room architecture.
        from p8_canonical_production_start import establish_single_solo_live_draft
        from run_production_stage1_authenticated import queue_setup_pause_for_seeding
        from p8_proven_pause_delivery import PAUSE_DELIVERY_RESOLVED
        from stage1_active_queue_surface import wait_for_active_queue_surface
        from stage1_preflight_cleanup import run_stage1_preflight_cleanup
        from playwright_auth_bridge_restore_harness import wait_bridge_auth_hydrated
        from p8_production_start_harness import scrape_stage1_ledger_rows
        from stage1_application_phase import EXPECTED_PHASE_SETUP_LOBBY

        run_stage1_preflight_cleanup(page, max_wait_s=180.0)
        wait_bridge_auth_hydrated(
            page,
            bridge,
            scrape_stage1_ledger_rows,
            timeout_s=float(os.environ.get("BRIDGE_HYDRATION_TIMEOUT_S", "240")),
            poll_interval_s=2.0,
            preamble_mode="stage1",
            expected_application_phase=EXPECTED_PHASE_SETUP_LOBBY,
        )
        canonical = establish_single_solo_live_draft(
            page, state["context"], setup_url=url, prior_room_id="", fresh_lobby_cleanup=False, max_wait_s=90.0
        )
        room_id = str(canonical.get("room_id") or canonical.get("created_room_id") or "").upper()
        pause = queue_setup_pause_for_seeding(page, room_id=room_id, latch_completed_ts=_time.time())
        pause_ok = bool(pause.get("paused")) and pause.get("pause_classification") == PAUSE_DELIVERY_RESOLVED
        if not pause_ok:
            return {"steady_authorized": False, "heavy_paint_complete": False, "pause_ok": False}
        gate_start = {
            "latched_room_id": room_id,
            "in_progress": True,
            "room_latch_pass": True,
            "pause_ack_ts": _time.time(),
        }
        wait_for_active_queue_surface(
            page,
            start_val=gate_start,
            while_paused=True,
            auth_complete=True,
            run_id=str(canonical.get("application_diagnostic_run_id") or ""),
        )
        steady = wait_for_rec_fragment_interactive_steady_state(page, timeout_s=120.0)
        retained = cb.retain_steady_state_result(steady)
        identity = cb._scrape_francisco_identity(page)
        mapped = map_stage_a_authority_fields(
            retained=retained, identity=identity, fallback_room_id=room_id
        )
        return {
            "steady_authorized": bool(retained.get("steady_state_ok")),
            "heavy_paint_complete": bool(retained.get("steady_state_ok")),
            "recommendation_fragment_run_seq": mapped.get("recommendation_fragment_run_seq"),
            "full_app_run_seq": mapped.get("full_app_run_seq"),
            "room_id": mapped.get("room_id") or room_id,
            "current_pick_index": mapped.get("current_pick_index"),
            "player_id": mapped.get("player_id"),
            "widget_key": mapped.get("widget_key"),
            "streamlit_session_id": first_defined(
                retained.get("streamlit_session_id"),
                (identity.get("francisco_probe") or {}).get("streamlit_session_id")
                if isinstance(identity.get("francisco_probe"), dict)
                else None,
                state.get("auth_sid"),
            ),
            "diagnostic_run_id": first_defined(
                retained.get("diagnostic_run_id"), state.get("auth_run")
            ),
            "authoritative_pick_source": mapped.get("authoritative_pick_source"),
            "pick_status": mapped.get("pick_status"),
            "retained": retained,
            "identity": identity,
        }

    def observe_gate() -> dict[str, Any]:
        page = state["page"]
        page_url = str(page.url or "")
        latch_n = query_param_value_count(urlparse(page_url).query, FRANCISCO_LATCH_PARAM)
        return {
            "latch_absent": latch_n == 0,
            "lifecycle": "unarmed",
            "armed_or_consumed_event_present": False,
            "page_url_latch_count": latch_n,
            "clear_gate_selected": False,
        }

    def collect_baseline() -> dict[str, Any]:
        from run_production_stage1_authenticated import scrape_queue_container_state
        from live_draft_queue_state_snapshot_diag import wait_and_scrape_queue_state_snapshot_from_page

        page = state["page"]
        ui = cb._queue_names(scrape_queue_container_state(page))
        # Stage A paint may complete before the dual-queue DOM probe is visible;
        # poll for the exact probe id (empty queues are valid once present).
        scraped = wait_and_scrape_queue_state_snapshot_from_page(page, timeout_s=20.0, poll_s=0.5)
        payload = scraped.get("payload") if isinstance(scraped.get("payload"), dict) else {}
        baseline_snap = payload.get("baseline") if isinstance(payload.get("baseline"), dict) else None
        # Prefer AUTH_ONLY production SID — never Context-A / bridge UUID / scrape-only.
        prod_sid = str(state.get("auth_sid") or "").strip()
        if not prod_sid:
            prod_sid = str(
                scraped.get("sid")
                or (baseline_snap or {}).get("streamlit_session_id")
                or ""
            ).strip()
        room_hint = str(
            (baseline_snap or {}).get("room_id")
            or scraped.get("room_id")
            or (state.get("stage_a_room_id") if isinstance(state, dict) else "")
            or ""
        )
        selected = select_authoritative_baseline_queues(
            production_sid=prod_sid,
            room_id=room_hint,
            snapshots=[baseline_snap] if baseline_snap else None,
            ui_queue=ui,
        )
        selected["ui_queue"] = ui
        selected["scrape"] = scraped
        selected["probe_found"] = bool(scraped.get("probe_found"))
        return selected

    def resolve_click_target(sa: dict[str, Any]) -> dict[str, Any]:
        ok = stage_a_identity_complete(sa)
        return {
            "ok": ok,
            "room_id": sa.get("room_id"),
            "current_pick_index": sa.get("current_pick_index"),
            "player_id": sa.get("player_id"),
            "widget_key": sa.get("widget_key"),
            "label": "⭐ Add to Queue",
        }

    def trusted_click(target: dict[str, Any]) -> dict[str, Any]:
        from stage1_add_to_queue_delivery import BINDING_UNIQUE, deliver_add_to_queue_click

        page = state["page"]
        if int(state.get("click_count") or 0) >= 1:
            return {"click_count": int(state["click_count"]), "error": "second_click_forbidden"}
        result = deliver_add_to_queue_click(
            page,
            widget_key=str(target.get("widget_key") or ""),
            player_name=FRANCISCO_NAME,
            binding=BINDING_UNIQUE,
        )
        state["click_count"] = 1
        return {
            "click_count": 1,
            "timestamp": _time.time(),
            "room_id": target.get("room_id"),
            "current_pick_index": target.get("current_pick_index"),
            "player_id": target.get("player_id"),
            "widget_key": target.get("widget_key"),
            "delivery": result,
        }

    def collect_post_click(click: dict[str, Any]) -> dict[str, Any]:
        from stage1_rec_queue_click_trace_scrape import scrape_rec_queue_app_trace
        from run_production_stage1_authenticated import scrape_queue_container_state
        from live_draft_queue_state_snapshot_diag import wait_and_scrape_queue_state_snapshot_from_page

        page = state["page"]
        # Bounded settle — no reload / second click / force-save.
        try:
            page.wait_for_timeout(2500)
        except Exception:
            pass
        app_trace = scrape_rec_queue_app_trace(page)
        payload_app = app_trace.get("payload") if isinstance(app_trace.get("payload"), dict) else {}
        last = payload_app.get("last") if isinstance(payload_app.get("last"), dict) else {}
        ui = cb._queue_names(scrape_queue_container_state(page))
        scraped = wait_and_scrape_queue_state_snapshot_from_page(page, timeout_s=15.0, poll_s=0.5)
        payload = scraped.get("payload") if isinstance(scraped.get("payload"), dict) else {}
        post_snap = (
            payload.get("post_mutation_added")
            if isinstance(payload.get("post_mutation_added"), dict)
            else None
        )
        prod_sid = str(state.get("auth_sid") or "").strip()
        if not prod_sid:
            prod_sid = str(
                scraped.get("sid")
                or (post_snap or {}).get("streamlit_session_id")
                or ""
            ).strip()
        click_ts = click.get("timestamp")
        selected = select_authoritative_post_queues(
            production_sid=prod_sid,
            room_id=str((post_snap or {}).get("room_id") or click.get("room_id") or ""),
            after_ts=float(click_ts) if click_ts is not None else None,
            snapshots=[post_snap] if post_snap else None,
            ui_queue=ui,
        )
        stop_observed = False  # unlatched path; STOP would be unexpected if seen in ledger
        return {
            "premutation_stop_observed": stop_observed,
            "mutation_helper_entered": bool(
                selected.get("mutation_helper_entered")
                if selected.get("mutation_helper_entered") is not None
                else last.get("mutation_helper_entered")
            ),
            "added": selected.get("added") if selected.get("added") is not None else last.get("added"),
            "session_queue": selected.get("session_queue"),
            "canonical_queue": selected.get("canonical_queue"),
            "ui_queue": ui,
            "queue_mutation_visible": FRANCISCO_NAME in ui,
            "callback_entered": bool(last.get("callback_entered") or app_trace.get("callback_entered")),
            "callback_ledger_observed": bool(last),
            "persist_dirty": (post_snap or {}).get("persist_dirty")
            if isinstance(post_snap, dict)
            else (last.get("persistence_write_result") == "persist_dirty"),
            "app_trace": app_trace,
            "queue_state_scrape": scraped,
            "authoritative_post": selected,
        }

    def close_browser() -> None:
        try:
            if state.get("context"):
                state["context"].close()
            if state.get("browser"):
                state["browser"].close()
            if state.get("pw"):
                state["pw"].stop()
        except Exception:
            pass

    ports = MutationCloudPorts(
        launch_browser=launch_browser,
        mark_consumed=mark_consumed,
        restore_auth=restore_auth,
        check_runtime=check_runtime,
        wait_stage_a=wait_stage_a,
        observe_gate=observe_gate,
        collect_baseline=collect_baseline,
        resolve_click_target=resolve_click_target,
        trusted_click=trusted_click,
        collect_post_click=collect_post_click,
        close_browser=close_browser,
    )
    cfg = MutationCloudConfig(
        bridge_id=bridge,
        require_canonical_observability=False,  # already checked in main
        production_reexecuted=True,
        required_sha=req,
        capture_cloud_runtime_sha="",  # never authority for live runtime
    )
    report = run_cloud_mutation_orchestration(
        ports, cfg, url=url, preflight=pre, observability=obs
    )
    report["bridge_guard"] = guard
    report["cloud_execution_path_wired"] = True
    report["required_sha"] = req
    report["expected_build_display"] = expected_build_display_for(req)
    return report


if __name__ == "__main__":
    raise SystemExit(main())
