"""Regression tests for Stage 1 ledger browser extraction."""

from __future__ import annotations

import base64
import html
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage1_ledger_browser_extract import (  # noqa: E402
    PIPELINE_CANARY_EVENT,
    _candidate_score,
    classify_scrape_boundary,
    decode_ledger_payload,
    filter_rows_for_run,
)


def _payload(rows: list[dict]) -> str:
    raw = json.dumps({"run_id": "abc123", "rows": rows}, default=str)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def test_decode_large_payload_with_padding() -> None:
    rows = [{"event": PIPELINE_CANARY_EVENT, "run_id": "abc123", "script_run_seq": 9, "event_id": "a:1:x"}]
    rows.extend(
        {"event": "production_stage1_script_begin", "run_id": "abc123", "script_run_seq": i, "event_id": f"a:{i}:y"}
        for i in range(250)
    )
    b64 = _payload(rows)
    dec = decode_ledger_payload(b64)
    assert dec["ok"] is True
    assert len(dec["rows"]) >= 250
    assert any(r.get("event") == PIPELINE_CANARY_EVENT for r in dec["rows"])


def test_payload_json_larger_than_48000_chars_decodes() -> None:
    rows = [{"event": PIPELINE_CANARY_EVENT, "run_id": "big", "payload": "x" * 400}]
    rows.extend({"event": "e", "run_id": "big", "blob": "y" * 300} for _ in range(200))
    raw = json.dumps({"run_id": "big", "rows": rows}, default=str)
    assert len(raw) > 48000
    dec = decode_ledger_payload(base64.b64encode(raw.encode()).decode())
    assert dec["ok"] is True
    assert len(dec["rows"]) == len(rows)


def test_candidate_score_complete_beats_stale_harness() -> None:
    harness = {
        "source": "window.__soloStage1HarnessLedgerStore.best_b64",
        "parse_ok": True,
        "row_count": 4,
        "pipeline_canary_present": True,
        "integrity_ok": True,
        "authority_rank": 99,
    }
    chunks = {
        "source": "window.__soloStage1LedgerB64Chunks",
        "parse_ok": True,
        "row_count": 265,
        "pipeline_canary_present": True,
        "integrity_ok": True,
        "authority_rank": 1,
    }
    assert _candidate_score(chunks) > _candidate_score(harness)


def test_verify_integrity_sha_mismatch() -> None:
    from stage1_ledger_browser_extract import verify_decoded_payload_integrity

    rows = [{"event": PIPELINE_CANARY_EVENT}]
    raw = json.dumps({"run_id": "r1", "rows": rows})
    dec = decode_ledger_payload(base64.b64encode(raw.encode()).decode())
    cand = {"payload_sha256_expected": "0" * 64, "data_rows_attr": 1}
    v = verify_decoded_payload_integrity(dec, cand)
    assert v["integrity_ok"] is False
    assert "sha256_mismatch" in v["integrity_issues"]


def test_filter_surface_drops_wrong_surface() -> None:
    rows = [
        {"event": PIPELINE_CANARY_EVENT, "run_id": "r1", "diagnostic_surface": "other"},
        {"event": PIPELINE_CANARY_EVENT, "run_id": "r1", "diagnostic_surface": "case_a_control"},
    ]
    out = filter_rows_for_run(rows, run_id="r1", diagnostic_surface="case_a_control")
    assert out["filtered_p6_capture_pass"] is True
    assert len(out["filtered_rows"]) == 1


def test_normalize_whitespace_and_urlsafe_b64() -> None:
    inner = json.dumps({"run_id": "r1", "rows": [{"event": PIPELINE_CANARY_EVENT, "run_id": "r1"}]})
    std = base64.b64encode(inner.encode()).decode()
    urlsafe = std.replace("+", "-").replace("/", "_")
    spaced = "\n".join(urlsafe[i : i + 20] for i in range(0, len(urlsafe), 20))
    dec = decode_ledger_payload(spaced)
    assert dec["ok"] is True
    assert dec["rows"][0]["event"] == PIPELINE_CANARY_EVENT


def test_candidate_score_prefers_canary_and_window() -> None:
    dom = {
        "source": "dom#solo-stage1-production-ledger[1]",
        "parse_ok": True,
        "row_count": 200,
        "pipeline_canary_present": False,
        "integrity_ok": True,
        "authority_rank": 4,
    }
    win = {
        "source": "window.__soloStage1LedgerB64",
        "parse_ok": True,
        "row_count": 241,
        "pipeline_canary_present": True,
        "integrity_ok": True,
        "authority_rank": 2,
    }
    assert _candidate_score(win) > _candidate_score(dom)


def test_filter_retains_canary_same_run() -> None:
    rows = [
        {"event": PIPELINE_CANARY_EVENT, "run_id": "abc123"},
        {"event": "other", "run_id": "abc123"},
        {"event": "other", "run_id": "old999"},
    ]
    out = filter_rows_for_run(rows, run_id="abc123")
    assert out["filtered_p6_capture_pass"] is True
    assert len(out["filtered_rows"]) == 2


def test_classify_scrape1_no_candidates() -> None:
    assert "SCRAPE1" in classify_scrape_boundary(candidates=[], selected=None, raw_canary=False)


def test_decode_html_escaped_b64() -> None:
    inner = json.dumps({"run_id": "r1", "rows": [{"event": PIPELINE_CANARY_EVENT}]})
    b64 = base64.b64encode(inner.encode()).decode()
    escaped = html.escape(b64)
    dec = decode_ledger_payload(escaped)
    assert dec["ok"] is True


def test_decode_missing_padding() -> None:
    inner = json.dumps({"run_id": "r1", "rows": [{"event": PIPELINE_CANARY_EVENT}]})
    b64 = base64.b64encode(inner.encode()).decode().rstrip("=")
    dec = decode_ledger_payload(b64)
    assert dec["ok"] is True


def test_candidate_score_prefers_late_dom_probe_over_early_duplicate() -> None:
    early = {
        "source": "dom#solo-stage1-production-ledger[1]",
        "parse_ok": True,
        "row_count": 80,
        "max_script_run_seq": 5,
        "data_script_run_seq": 5,
        "data_probe_checkpoint": "early_script",
        "data_probe_ts": 100.0,
        "pipeline_canary_present": True,
        "integrity_ok": True,
        "authority_rank": 4,
    }
    late = {
        "source": "dom#solo-stage1-production-ledger[2]",
        "parse_ok": True,
        "row_count": 95,
        "max_script_run_seq": 5,
        "data_script_run_seq": 5,
        "data_probe_checkpoint": "late_start_handler_success",
        "data_probe_ts": 100.5,
        "pipeline_canary_present": True,
        "integrity_ok": True,
        "authority_rank": 4,
    }
    assert _candidate_score(late) > _candidate_score(early)


def test_stale_early_dom_would_lose_without_checkpoint_rank() -> None:
    """Documents prior failure mode: more rows on window beat early dom; late checkpoint fixes dom-vs-dom."""
    stale_early = {
        "source": "dom#solo-stage1-production-ledger[1]",
        "parse_ok": True,
        "row_count": 240,
        "max_script_run_seq": 4,
        "data_script_run_seq": 4,
        "data_probe_checkpoint": "early_script",
        "pipeline_canary_present": True,
        "integrity_ok": True,
        "authority_rank": 4,
    }
    fresh_late = {
        "source": "dom#solo-stage1-production-ledger[2]",
        "parse_ok": True,
        "row_count": 260,
        "max_script_run_seq": 5,
        "data_script_run_seq": 5,
        "data_probe_checkpoint": "late_start_handler_success",
        "pipeline_canary_present": True,
        "integrity_ok": True,
        "authority_rank": 4,
    }
    assert _candidate_score(fresh_late) > _candidate_score(stale_early)


def test_classify_scrape2_canary_on_unselected_candidate() -> None:
    cands = [
        {"source": "dom#solo-stage1-production-ledger[1]", "parse_ok": True, "row_count": 50, "pipeline_canary_present": True},
        {"source": "dom#solo-stage1-production-ledger[2]", "parse_ok": True, "row_count": 240, "pipeline_canary_present": False},
    ]
    assert "SCRAPE2" in classify_scrape_boundary(candidates=cands, selected=cands[1], raw_canary=False)


def test_reassemble_b64_chunks() -> None:
    from stage1_ledger_browser_extract import reassemble_b64_from_chunk_attrs

    rows = [{"event": PIPELINE_CANARY_EVENT, "run_id": "r1"}]
    b64 = _payload(rows)
    c0, c1 = b64[:30], b64[30:]
    attrs = {
        "data-chunk-count": "2",
        "data-payload-b64-len": str(len(b64)),
        "data-b64-chunk-0": c0,
        "data-b64-chunk-1": c1,
    }
    joined, kind = reassemble_b64_from_chunk_attrs(attrs)
    assert kind == "chunk_full"
    dec = decode_ledger_payload(joined)
    assert dec["ok"] is True


def test_filter_drops_canary_wrong_run() -> None:
    rows = [{"event": PIPELINE_CANARY_EVENT, "run_id": "abc123"}]
    out = filter_rows_for_run(rows, run_id="other_run")
    assert out["filtered_p6_capture_pass"] is False
