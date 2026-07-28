"""Runner probe decode and page-state precedence tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from live_draft_solo_rv_control_probe import (
    RV_LEDGER_B64_PREFIX,
    decode_control_probe_text_with_meta,
    encode_control_probe_payload,
)
from solo_rv_ladder_runner_state import classify_page_shell, page_state_to_invalid_reason


def test_decode_wrapped_base64_across_lines():
    payload = {"run_id": "r1", "rows": [{"event": "script_begin", "run_id": "r1"}]}
    line = encode_control_probe_payload(payload)
    b64_part = line[len(RV_LEDGER_B64_PREFIX) :]
    wrapped = RV_LEDGER_B64_PREFIX + b64_part[:40] + "\n" + b64_part[40:80] + "\n" + b64_part[80:]
    text = f"Fork\nSome unrelated Error word in UI\n{wrapped}\n"
    decoded, meta = decode_control_probe_text_with_meta(text)
    assert meta.get("decode_ok") is True
    assert decoded.get("run_id") == "r1"
    assert len(decoded.get("rows") or []) == 1


def test_ledger_overrides_unrelated_error_word():
    payload = {"run_id": "r1", "rows": [{"event": "script_begin", "run_id": "r1"}]}
    text = "Error in unrelated label\n" + encode_control_probe_payload(payload)
    decoded, meta = decode_control_probe_text_with_meta(text)
    probe = {**decoded, "_probe_parse": meta}
    state = classify_page_shell(
        page_text=text,
        dom={"has_streamlit_app": True, "has_st_exception": False},
        rows=[],
        probe=probe,
    )
    assert state == "READY_LEDGER"


def test_traceback_without_ledger_is_app_error():
    state = classify_page_shell(
        page_text="Something failed",
        dom={"has_st_exception": True, "has_streamlit_app": True},
        rows=[],
        probe={"_probe_parse": {"decode_ok": False, "prefix_found": False}},
    )
    assert state == "APP_ERROR"


def test_malformed_base64_reports_probe_decode_failed():
    text = RV_LEDGER_B64_PREFIX + "eyJnotvalidbase64padding"
    _, meta = decode_control_probe_text_with_meta(text)
    assert meta.get("decode_ok") is False
    assert "PROBE_DECODE_FAILED" in str(meta.get("decode_error") or "")


def test_encode_does_not_truncate_large_ledger():
    """Regression: [:48000] JSON cap produced ~64k b64 and invalid JSON on Cloud RV3 runs."""
    rows = []
    for i in range(120):
        rows.append(
            {
                "event": "rv3_room_checkpoint",
                "event_sequence": i + 1,
                "run_id": "r-large",
                "extra": {"checkpoint": "before_prepare_live_draft_state", "padding": "x" * 400},
            }
        )
    payload = {"run_id": "r-large", "step": "RV3", "script_run_seq": 4, "rows": rows}
    line = encode_control_probe_payload(payload)
    decoded, meta = decode_control_probe_text_with_meta(line)
    assert meta.get("decode_ok") is True
    assert len(decoded.get("rows") or []) == 120
    assert len(line) > 70000


def test_extract_longest_ledger_when_multiple_prefix_copies():
    small = encode_control_probe_payload({"run_id": "small", "rows": [{"event": "a"}]})
    large = encode_control_probe_payload(
        {"run_id": "large", "rows": [{"event": "b", "extra": {"pad": "z" * 8000}}]}
    )
    text = f"noise\n{small}\nmore\n{large}\n"
    decoded, meta = decode_control_probe_text_with_meta(text)
    assert meta.get("decode_ok") is True
    assert decoded.get("run_id") == "large"


def test_neither_ledger_nor_exception_is_page_not_ready():
    state = classify_page_shell(
        page_text="Loading...",
        dom={"has_streamlit_app": False},
        rows=[],
        probe={"_probe_parse": {"decode_ok": False, "prefix_found": False}},
    )
    assert state == "PAGE_NOT_READY"


def test_traceback_in_page_text_is_app_error_without_ledger():
    state = classify_page_shell(
        page_text='Traceback:\nFile "/mount/src/baseball-stat-app/streamlit_app.py", line 1\nNameError: x',
        dom={"has_st_exception": False, "has_streamlit_app": True},
        rows=[],
        probe={"_probe_parse": {"decode_ok": False, "prefix_found": True}},
    )
    assert state == "APP_ERROR"


def test_probe_parse_invalid_reason():
    reason = page_state_to_invalid_reason(
        "PAGE_NOT_READY",
        probe_parse={"prefix_found": True, "decode_ok": False, "decode_error": "PROBE_DECODE_FAILED:x"},
    )
    assert reason == "INVALID_RV_CONTROL_PAGE_NOT_READY_OR_PROBE_PARSE_FAILED"
