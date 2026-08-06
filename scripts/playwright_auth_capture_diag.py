"""Headed auth capture diagnostics: identity, trace, login-boundary classification (harness only)."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RESULT_PATH = ROOT / "data" / "capture_playwright_daniel_auth_once.result.json"
TRACE_ROOT = ROOT / "data" / "capture_playwright_daniel_auth_trace"

AUTH_LOGIN1 = "AUTH_LOGIN1"  # provider login never completed
AUTH_LOGIN2 = "AUTH_LOGIN2"  # callback did not return to app
AUTH_LOGIN3 = "AUTH_LOGIN3"  # provider session but tokens absent from browser storage
AUTH_LOGIN4 = "AUTH_LOGIN4"  # browser tokens but bridge save never invoked
AUTH_LOGIN5 = "AUTH_LOGIN5"  # bridge save invoked but rejected before persistence
AUTH_LOGIN6 = "AUTH_LOGIN6"  # bridge persisted but Streamlit lookup/hydration never ran
AUTH_LOGIN7 = "AUTH_LOGIN7"  # suite_sid changed during login/callback
AUTH_LOGIN8 = "AUTH_LOGIN8"

CLOUD_HOST = "baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app"

LOGIN_CHECKPOINTS = (
    "load_browser_auth_tokens",
    "load_browser_auth_tokens_lookup",
    "save_browser_auth_tokens",
    "save_browser_auth_tokens_readback",
    "restore_auth_session_exit",
    "apply_authenticated_user_exit",
)

_TOKEN_LIKE = re.compile(r"eyJ[a-zA-Z0-9_-]{10,}")


def harness_git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                text=True,
                timeout=10,
            ).strip()
        )
    except Exception:
        return ""


def is_provider_url(url: str) -> bool:
    u = (url or "").lower()
    return any(
        x in u
        for x in (
            "accounts.google",
            "login.microsoftonline",
            "auth0.com",
            "supabase.co/auth",
        )
    )


def is_cloud_app_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return CLOUD_HOST in host or host.endswith(".streamlit.app")


def is_oauth_callback_url(url: str) -> bool:
    u = url or ""
    low = u.lower()
    if not is_cloud_app_url(u):
        return False
    return any(
        x in low
        for x in (
            "code=",
            "access_token=",
            "#access_token",
            "error=",
            "type=recovery",
        )
    )


def new_run_identity(*, suite_sid: str, target_url: str) -> dict[str, Any]:
    return {
        "harness_sha": harness_git_sha(),
        "suite_sid": str(suite_sid or "").strip(),
        "suite_sid_prefix": str(suite_sid or "")[:8],
        "target_url": str(target_url or "")[:512],
        "capture_started_at": _utc_iso(),
        "capture_ended_at": "",
        "final_browser_url": "",
        "cloud_runtime_sha": "",
        "diagnostic_run_id": "",
        "streamlit_session_id": "",
        "provider_login_seen": False,
        "oauth_callback_seen": False,
        "signed_in_display": False,
        "files_updated": False,
        "ok": False,
        "failure": "",
        "auth_login_classification": "",
        "first_missing_login_transition": "",
        "bridge_save_attempted": False,
        "bridge_readback_attempted": False,
    }


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def probe_storage_booleans(page: Any) -> dict[str, Any]:
    """Non-secret localStorage/sessionStorage presence flags."""
    try:
        return page.evaluate(
            """() => {
      const out = { local_key_count: 0, session_key_count: 0, supabase_storage_key_present: false,
        auth_token_key_present: false, access_token_value_present: false, refresh_token_value_present: false,
        key_prefix_samples: [] };
      const sample = [];
      const scan = (store) => {
        if (!store) return;
        try {
          for (let i = 0; i < store.length; i++) {
            const k = store.key(i) || '';
            if (!k) continue;
            const kl = k.toLowerCase();
            if (kl.includes('supabase') || kl.startsWith('sb-')) out.supabase_storage_key_present = true;
            if (kl.includes('auth') && kl.includes('token')) out.auth_token_key_present = true;
            const v = String(store.getItem(k) || '');
            if (v.length > 20 && v.includes('.')) {
              if (kl.includes('access')) out.access_token_value_present = true;
              if (kl.includes('refresh')) out.refresh_token_value_present = true;
            }
            if (sample.length < 12) sample.push(k.slice(0, 24));
          }
        } catch (e) {}
      };
      scan(window.localStorage);
      scan(window.sessionStorage);
      try { out.local_key_count = localStorage.length; } catch (e) {}
      try { out.session_key_count = sessionStorage.length; } catch (e) {}
      out.key_prefix_samples = sample;
      return out;
    }"""
        )
    except Exception as exc:
        return {"probe_error": type(exc).__name__}


def sanitize_text(text: str, *, limit: int = 4000) -> str:
    t = str(text or "")[:limit]
    t = _TOKEN_LIKE.sub("[redacted-token]", t)
    return t


def sanitize_console_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in entries[-40:]:
        msg = sanitize_text(str(e.get("text") or ""), limit=240)
        out.append({"type": str(e.get("type") or "")[:20], "text": msg})
    return out


def sanitize_failed_requests(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in entries[-30:]:
        url = str(e.get("url") or "")
        try:
            host = urlparse(url).netloc
        except Exception:
            host = url[:80]
        out.append(
            {
                "host": host[:80],
                "failure": str(e.get("failure") or "")[:80],
                "method": str(e.get("method") or "")[:12],
            }
        )
    return out


def extract_identity_from_ledger(rows: list[dict[str, Any]]) -> dict[str, str]:
    run_id = ""
    st_sid = ""
    for r in reversed(rows):
        if not isinstance(r, dict):
            continue
        if not run_id:
            run_id = str(r.get("diagnostic_run_id") or r.get("run_id") or "").strip()
        if not st_sid:
            st_sid = str(r.get("streamlit_session_id") or "").strip()
        if run_id and st_sid:
            break
    return {"diagnostic_run_id": run_id[:64], "streamlit_session_id": st_sid[:36]}


def ledger_login_timeline(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordered hydration/login checkpoints from Cloud ledger (no secrets)."""
    timeline: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ev = str(r.get("event") or "")
        cp = str(r.get("checkpoint") or "")
        if ev != "production_stage1_auth_prestart_hydration" and ev != "browser_auth_bridge_mutation":
            if ev == "production_stage1_auth_state_before_start_control":
                timeline.append(
                    {
                        "kind": "before_start_control",
                        "event_id": str(r.get("event_id") or "")[:80],
                        "streamlit_session_id": str(r.get("streamlit_session_id") or "")[:36],
                        "is_authenticated": r.get("is_authenticated"),
                        "auth_session_complete": r.get("auth_session_complete"),
                        "auth_hydration_source": str(r.get("auth_hydration_source") or "")[:40],
                    }
                )
            continue
        if cp not in LOGIN_CHECKPOINTS and ev != "browser_auth_bridge_mutation":
            continue
        entry: dict[str, Any] = {
            "checkpoint": cp or str(r.get("operation") or "")[:40],
            "event_id": str(r.get("event_id") or "")[:80],
            "streamlit_session_id": str(r.get("streamlit_session_id") or "")[:36],
            "suite_sid_prefix": str(r.get("suite_sid_prefix") or "")[:8],
            "rejection_reason": str(r.get("rejection_reason") or r.get("failure_reason") or "")[:80],
            "browser_tokens_loaded": r.get("browser_tokens_loaded"),
            "persistence_attempted": r.get("persistence_attempted"),
            "persistence_succeeded": r.get("persistence_succeeded"),
            "readback_record_complete": r.get("readback_record_complete"),
            "apply_authenticated_user_ok": r.get("apply_authenticated_user_ok"),
            "authenticated_after": r.get("authenticated_after"),
        }
        if r.get("row_id_prefix"):
            entry["row_id_prefix"] = str(r.get("row_id_prefix") or "")[:8]
        if r.get("matching_row_id"):
            entry["matching_row_id_prefix"] = str(r.get("matching_row_id") or "")[:8]
        env = r.get("environment")
        if isinstance(env, dict) and env.get("url_fingerprint"):
            entry["environment_fingerprint"] = str(env.get("url_fingerprint") or "")[:16]
        timeline.append(entry)
    return timeline


def auth_prestart_hydration_seen(rows: list[dict[str, Any]]) -> bool:
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("event") or "") != "production_stage1_auth_prestart_hydration":
            continue
        cp = str(r.get("checkpoint") or "")
        if cp in LOGIN_CHECKPOINTS or cp.startswith("apply_authenticated_user"):
            return True
    return False


def login_transition_state(
    *,
    target_sid: str,
    url_sid: str,
    provider_seen: bool,
    oauth_callback_seen: bool,
    returned_to_app: bool,
    storage: dict[str, Any],
    signed_in_display: bool,
    ledger_rows: list[dict[str, Any]],
    strict_failure: str,
    sign_in_initiated: bool = False,
) -> dict[str, Any]:
    """Ten-step callback boundary booleans (harness + ledger derived)."""
    save_row = _last_cp(ledger_rows, "save_browser_auth_tokens")
    readback_row = _last_cp(ledger_rows, "save_browser_auth_tokens_readback")
    load_row = _last_cp(ledger_rows, "load_browser_auth_tokens")
    load_lookup = _last_cp(ledger_rows, "load_browser_auth_tokens_lookup")
    apply_row = _last_cp(ledger_rows, "apply_authenticated_user_exit")
    before = _last_event(ledger_rows, "production_stage1_auth_state_before_start_control")

    tokens_in_storage = bool(
        storage.get("access_token_value_present")
        or storage.get("refresh_token_value_present")
        or storage.get("supabase_storage_key_present")
    )
    save_invoked = save_row is not None
    save_ok = bool(save_row.get("persistence_succeeded")) if save_row else False
    readback_ok = bool(readback_row.get("readback_record_complete")) if readback_row else False
    load_invoked = load_row is not None or load_lookup is not None
    apply_ok = bool(apply_row.get("authenticated_after")) if apply_row else False
    auth_complete = bool(before and before.get("auth_session_complete") is True)
    hydration_ledger = auth_prestart_hydration_seen(ledger_rows)

    steps = {
        "1_sign_in_initiated": bool(sign_in_initiated or provider_seen),
        "2_provider_surface_observed": bool(provider_seen),
        "3_tokens_present_in_browser_storage": tokens_in_storage,
        "4_authenticated_user_visible_or_provider_state": bool(
            signed_in_display and (provider_seen or tokens_in_storage)
        ),
        "5_suite_sid_matches_target": bool(target_sid and url_sid and target_sid == url_sid),
        "6_auth_hydration_ledger_started": hydration_ledger,
        "7_bridge_save_committed_or_readback_ok": save_ok or readback_ok,
        "8_load_browser_auth_tokens_invoked": load_invoked,
        "9_apply_authenticated_user_invoked": apply_row is not None,
        "10_streamlit_auth_complete": auth_complete,
    }
    # Legacy step keys for older tests / artifacts
    steps_legacy = {
        "1_provider_sign_in_initiated": steps["1_sign_in_initiated"],
        "2_oauth_callback_url_reached": bool(oauth_callback_seen or (returned_to_app and provider_seen)),
        "3_tokens_present_in_browser_storage": steps["3_tokens_present_in_browser_storage"],
        "4_authenticated_user_visible_or_provider_state": steps["4_authenticated_user_visible_or_provider_state"],
        "5_suite_sid_matches_target": steps["5_suite_sid_matches_target"],
        "6_token_bridge_save_invoked": save_invoked,
        "7_bridge_save_committed_or_readback_ok": steps["7_bridge_save_committed_or_readback_ok"],
        "8_load_browser_auth_tokens_invoked": steps["8_load_browser_auth_tokens_invoked"],
        "9_apply_authenticated_user_invoked": steps["9_apply_authenticated_user_invoked"],
        "10_streamlit_auth_complete": steps["10_streamlit_auth_complete"],
    }
    order = list(steps.keys())
    first_missing = ""
    for key in order:
        if not steps[key]:
            first_missing = key
            break
    return {
        "steps": steps,
        "steps_legacy": steps_legacy,
        "first_missing_transition": first_missing,
        "bridge_save_attempted": bool(save_row and save_row.get("persistence_attempted")),
        "bridge_readback_attempted": readback_row is not None,
        "strict_failure": strict_failure,
        "misleading_signed_in_only": bool(
            signed_in_display and not provider_seen and not hydration_ledger and not save_invoked
        ),
    }


def infer_timeout_failure_phase(
    login_state: dict[str, Any],
    *,
    strict_failure: str = "",
) -> str:
    """Map first missing ordered step to a deterministic harness failure code."""
    if strict_failure in ("start_control_disabled", "auth_session_finalization_incomplete"):
        return "session_finalization_after_apply"
    if strict_failure == "streamlit_auth_incomplete":
        steps = login_state.get("steps") or {}
        if login_state.get("misleading_signed_in_only"):
            return "timeout_signed_in_ui_without_provider_or_ledger"
        if steps.get("9_apply_authenticated_user_invoked"):
            return "session_finalization_after_apply"
        if steps.get("7_bridge_save_committed_or_readback_ok") and not steps.get("9_apply_authenticated_user_invoked"):
            return "timeout_apply_auth_never_invoked"
        if steps.get("6_auth_hydration_ledger_started") and not steps.get("7_bridge_save_committed_or_readback_ok"):
            return "timeout_bridge_save_never_invoked"
        if steps.get("5_suite_sid_matches_target") and not steps.get("6_auth_hydration_ledger_started"):
            return "timeout_ledger_hydration_unavailable"
    steps = login_state.get("steps") or {}
    missing = str(login_state.get("first_missing_transition") or "")
    if missing == "1_sign_in_initiated":
        return "timeout_login_never_initiated"
    if missing == "2_provider_surface_observed":
        return "timeout_provider_surface_never_observed"
    if missing in ("3_tokens_present_in_browser_storage", "4_authenticated_user_visible_or_provider_state"):
        return "timeout_callback_never_completed"
    if missing == "6_auth_hydration_ledger_started":
        return "timeout_ledger_hydration_unavailable"
    if missing == "7_bridge_save_committed_or_readback_ok":
        return "timeout_bridge_save_never_invoked"
    if missing == "9_apply_authenticated_user_invoked":
        return "timeout_apply_auth_never_invoked"
    if missing == "10_streamlit_auth_complete":
        return "session_finalization_after_apply"
    return strict_failure or "timeout_strict_capture"


def classify_auth_login(
    state: dict[str, Any],
    *,
    sid_drift: bool = False,
    timeout_before_sign_in: bool = False,
) -> str:
    if sid_drift:
        return AUTH_LOGIN7
    steps = state.get("steps") or state.get("steps_legacy") or {}
    missing = str(state.get("first_missing_transition") or "")
    if state.get("misleading_signed_in_only"):
        return AUTH_LOGIN1
    if timeout_before_sign_in and not steps.get("1_sign_in_initiated") and not steps.get(
        "1_provider_sign_in_initiated"
    ):
        return AUTH_LOGIN1
    if not steps.get("1_sign_in_initiated") and not steps.get("1_provider_sign_in_initiated"):
        if not steps.get("2_provider_surface_observed") and not steps.get("2_oauth_callback_url_reached"):
            return AUTH_LOGIN1
    if (steps.get("1_sign_in_initiated") or steps.get("1_provider_sign_in_initiated")) and not steps.get(
        "2_provider_surface_observed"
    ) and not steps.get("2_oauth_callback_url_reached"):
        return AUTH_LOGIN2
    if steps.get("2_oauth_callback_url_reached") or steps.get("2_provider_surface_observed"):
        if not steps.get("3_tokens_present_in_browser_storage"):
            if not steps.get("4_authenticated_user_visible_or_provider_state"):
                return AUTH_LOGIN3
    if steps.get("3_tokens_present_in_browser_storage") and not steps.get("6_token_bridge_save_invoked"):
        if not steps.get("6_auth_hydration_ledger_started"):
            return AUTH_LOGIN4
        return AUTH_LOGIN4
    if steps.get("6_token_bridge_save_invoked") and not steps.get("7_bridge_save_committed_or_readback_ok"):
        return AUTH_LOGIN5
    if steps.get("7_bridge_save_committed_or_readback_ok") and not steps.get("8_load_browser_auth_tokens_invoked"):
        return AUTH_LOGIN6
    if missing == "10_streamlit_auth_complete" or str(state.get("strict_failure") or "") == "streamlit_auth_incomplete":
        if steps.get("4_authenticated_user_visible_or_provider_state") and not steps.get("6_token_bridge_save_invoked"):
            if not steps.get("6_auth_hydration_ledger_started"):
                return AUTH_LOGIN1 if state.get("misleading_signed_in_only") else AUTH_LOGIN4
            return AUTH_LOGIN4
        if steps.get("6_token_bridge_save_invoked") and not steps.get("7_bridge_save_committed_or_readback_ok"):
            return AUTH_LOGIN5
        if steps.get("7_bridge_save_committed_or_readback_ok") and not steps.get("9_apply_authenticated_user_invoked"):
            return AUTH_LOGIN6
        if steps.get("8_load_browser_auth_tokens_invoked") and not steps.get("9_apply_authenticated_user_invoked"):
            return AUTH_LOGIN6
        return AUTH_LOGIN6
    return AUTH_LOGIN8


def _last_cp(rows: list[dict[str, Any]], checkpoint: str) -> dict[str, Any] | None:
    matches = [
        r
        for r in rows
        if isinstance(r, dict)
        and str(r.get("event") or "") == "production_stage1_auth_prestart_hydration"
        and str(r.get("checkpoint") or "") == checkpoint
    ]
    return matches[-1] if matches else None


def _last_event(rows: list[dict[str, Any]], event: str) -> dict[str, Any] | None:
    matches = [r for r in rows if isinstance(r, dict) and str(r.get("event") or "") == event]
    return matches[-1] if matches else None


class CaptureTraceCollector:
    """Console/network/url timeline for headed capture."""

    def __init__(self) -> None:
        self.url_transitions: list[dict[str, Any]] = []
        self.console: list[dict[str, Any]] = []
        self.failed_requests: list[dict[str, Any]] = []
        self._last_url = ""

    def attach(self, page: Any) -> None:
        def on_console(msg: Any) -> None:
            self.console.append({"type": msg.type, "text": msg.text})

        def on_request_failed(req: Any) -> None:
            self.failed_requests.append(
                {
                    "url": req.url,
                    "method": req.method,
                    "failure": req.failure or "",
                }
            )

        page.on("console", on_console)
        page.on("requestfailed", on_request_failed)

    def note_url(self, url: str, *, label: str = "") -> None:
        u = str(url or "")
        if u == self._last_url:
            return
        self._last_url = u
        self.url_transitions.append(
            {
                "ts": time.time(),
                "label": label[:40],
                "url_host": urlparse(u).netloc[:80] if u else "",
                "is_provider": is_provider_url(u),
                "is_cloud_app": is_cloud_app_url(u),
                "is_oauth_callback": is_oauth_callback_url(u),
                "suite_sid_prefix": u.split("suite_sid=")[-1][:8] if "suite_sid=" in u else "",
            }
        )


def save_trace_bundle(
    *,
    trace_dir: Path,
    page: Any,
    identity: dict[str, Any],
    storage_probe: dict[str, Any],
    collector: CaptureTraceCollector,
    ledger_rows: list[dict[str, Any]],
    screenshot_labels: list[tuple[str, Callable[[], None] | None]],
    browser_surfaces: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for label, _ in screenshot_labels:
        safe = re.sub(r"[^a-z0-9_]+", "_", label.lower())[:40]
        path = trace_dir / f"{safe}.png"
        try:
            page.screenshot(path=str(path), full_page=False)
            paths[label] = str(path)
        except Exception:
            paths[label] = ""
    try:
        body_path = trace_dir / "final_page_text.txt"
        from playwright.sync_api import Page

        if isinstance(page, Page):
            text = page.evaluate("() => (document.body && document.body.innerText) || ''")
        else:
            text = ""
        body_path.write_text(sanitize_text(str(text), limit=8000), encoding="utf-8")
        paths["final_page_text"] = str(body_path)
    except Exception:
        pass

    ledger_summary = {
        "row_count": len(ledger_rows),
        "event_ids": [
            str(r.get("event_id") or "")[:80]
            for r in ledger_rows[-60:]
            if isinstance(r, dict) and r.get("event_id")
        ],
        "login_timeline": ledger_login_timeline(ledger_rows),
    }
    bundle = {
        "identity": identity,
        "storage_probe": storage_probe,
        "url_transitions": collector.url_transitions[-80:],
        "console": sanitize_console_entries(collector.console),
        "failed_requests": sanitize_failed_requests(collector.failed_requests),
        "screenshots": paths,
        "ledger_summary": ledger_summary,
    }
    if browser_surfaces:
        bundle["browser_surfaces"] = browser_surfaces
    bundle_path = trace_dir / "trace_bundle.json"
    blob = json.dumps(bundle, indent=2, default=str)
    if not trace_has_no_secrets(blob):
        bundle["sanitized"] = True
        blob = json.dumps(bundle, indent=2, default=str)
    bundle_path.write_text(blob, encoding="utf-8")
    return {"trace_dir": str(trace_dir), "trace_bundle": str(bundle_path), "screenshots": paths}


def trace_has_no_secrets(blob: str) -> bool:
    low = blob.lower()
    if _TOKEN_LIKE.search(blob):
        return False
    if '"access_token"' in low and re.search(r'"access_token"\s*:\s*"[^"]{8,}', blob):
        return False
    if "refresh_token" in low and re.search(r'"refresh_token"\s*:\s*"[^"]{8,}', blob):
        return False
    return True


def write_result_artifact(payload: dict[str, Any]) -> Path:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(payload, indent=2, default=str)
    if not trace_has_no_secrets(blob):
        payload = {"error": "refused_to_write_secrets", "suite_sid_prefix": payload.get("suite_sid_prefix")}
        blob = json.dumps(payload, indent=2)
    RESULT_PATH.write_text(blob, encoding="utf-8")
    return RESULT_PATH


def build_failure_payload(
    *,
    identity: dict[str, Any],
    failure: str,
    strict_capture: dict[str, Any] | None,
    login_state: dict[str, Any],
    auth_login_class: str,
    trace_meta: dict[str, Any],
    files_updated: bool,
) -> dict[str, Any]:
    identity = dict(identity)
    identity["capture_ended_at"] = _utc_iso()
    identity["ok"] = False
    identity["failure"] = failure
    identity["files_updated"] = files_updated
    identity["auth_login_classification"] = auth_login_class
    identity["first_missing_login_transition"] = str(login_state.get("first_missing_transition") or "")
    identity["bridge_save_attempted"] = bool(login_state.get("bridge_save_attempted"))
    identity["bridge_readback_attempted"] = bool(login_state.get("bridge_readback_attempted"))
    payload: dict[str, Any] = {
        **identity,
        "strict_capture": strict_capture or {},
        "login_boundary": login_state,
        "trace": trace_meta,
    }
    if login_state.get("failure_phase"):
        payload["failure_phase"] = login_state["failure_phase"]
    return payload


def verify_capture_url(url: str, *, expected_sid: str) -> dict[str, Any]:
    parsed = urlparse(url)
    return {
        "hostname_ok": CLOUD_HOST in (parsed.netloc or ""),
        "is_streamlit_app": (parsed.netloc or "").endswith(".streamlit.app"),
        "suite_sid_in_url": expected_sid in (url or ""),
        "suite_sid_prefix_in_url": expected_sid[:8] in (url or "") if expected_sid else False,
        "path_query_sample": (parsed.path + "?" + (parsed.query or ""))[:120],
    }
