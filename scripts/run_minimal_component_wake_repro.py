"""Run minimal component wake repro against local or Streamlit Cloud."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "data" / "minimal_component_wake_repro.json"
DEFAULT_CLOUD_BASE = os.environ.get(
    "MINIMAL_WAKE_REPRO_CLOUD_URL",
    "https://baseball-stat-app-d4jlymjc4iptaadc3kquwx.streamlit.app",
)
REQUIRED_CYCLES = 4
TIMEOUT_S = 120


def expected_sha() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1].strip().lower()[:7]
    marker = ROOT / "minimal_wake_repro_deploy.txt"
    if marker.is_file():
        return marker.read_text(encoding="utf-8").splitlines()[0].split("#", 1)[0].strip()[:7]
    return ""


def target_url() -> str:
    env = os.environ.get("MINIMAL_WAKE_REPRO_URL", "").strip()
    if env:
        return env
    if os.environ.get("MINIMAL_WAKE_REPRO_LOCAL", "").strip() in ("1", "true", "yes"):
        return "http://localhost:8765"
    return DEFAULT_CLOUD_BASE.rstrip("/")


def _component_iframe_url(iframe_urls: list[str]) -> str:
    for url in iframe_urls:
        low = str(url or "").lower()
        if "minimal_wake_repro" in low or "/component/" in low:
            return url
    for url in iframe_urls:
        if url and "statuspage" not in url and url not in ("", "about:blank"):
            return url
    return ""


def scrape_probe(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots() {
            const out = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { out.push(f.contentDocument); } catch (e) {}
            }
            return out.filter(Boolean);
          }
          const out = {
            deploy_sha: '',
            passed: false,
            callback_count: 0,
            component_name: '',
            widget_key: '',
            payload: '',
            client_last: '',
            client_chain: '',
            client_console: '',
            client_iframe_url: '',
            iframe_urls: [],
          };
          const deploy = document.querySelector('#repro-deploy-build');
          if (deploy) out.deploy_sha = deploy.getAttribute('data-sha') || '';
          const result = document.querySelector('#repro-result');
          if (result) {
            out.passed = (result.getAttribute('data-passed') || '') === 'true';
            out.callback_count = parseInt(result.getAttribute('data-callbacks') || '0', 10);
            out.component_name = result.getAttribute('data-component-name') || '';
            out.widget_key = result.getAttribute('data-widget-key') || '';
            out.payload = result.getAttribute('data-payload') || '';
          }
          for (const frame of document.querySelectorAll('iframe')) {
            try { out.iframe_urls.push(frame.src || ''); } catch (e) {}
          }
          for (const root of roots()) {
            const el = root.querySelector('#repro-client');
            if (!el) continue;
            out.client_last = el.getAttribute('data-last') || '';
            out.client_chain = el.getAttribute('data-chain') || '';
            out.client_console = el.getAttribute('data-console') || '';
            out.client_iframe_url = el.getAttribute('data-iframe-url') || '';
          }
          return out;
        }"""
    )


def _validate_probe(report: dict[str, Any]) -> None:
    final = dict(report.get("final_probe") or {})
    payload = dict(report.get("python_payload") or {})
    validation = dict(payload.get("validation") or {})
    callbacks = list(payload.get("callbacks") or [])
    tokens = [str(row.get("token") or "") for row in callbacks if row.get("token")]
    unique_tokens = list(dict.fromkeys(tokens))
    report["token_analysis"] = {
        "callback_count": len(callbacks),
        "unique_token_count": len(unique_tokens),
        "duplicate_tokens": max(0, len(tokens) - len(unique_tokens)),
        "tokens": unique_tokens,
    }
    report["component_iframe_url"] = _component_iframe_url(list(final.get("iframe_urls") or [])) or str(
        final.get("client_iframe_url") or ""
    )
    report["component_registration_name"] = str(
        final.get("component_name")
        or (payload.get("diag") or {}).get("component_registration")
        or (payload.get("diag") or {}).get("component_name")
        or ""
    )
    report["widget_key"] = str(final.get("widget_key") or (payload.get("diag") or {}).get("widget_key") or "")
    diag = dict(payload.get("diag") or {})
    report["raw_return_value"] = diag.get("raw_return")
    report["session_state_value"] = diag.get("session_state_value")
    report["callback_count"] = int(report.get("best_callback_count") or final.get("callback_count") or 0)
    report["cloud_logs"] = {
        "available": False,
        "reason": "Streamlit Cloud runtime logs require manage-console access; not exposed to probe.",
        "note": "Inspect Streamlit Cloud → Manage app → Logs while repro runs for Python-side traces.",
    }
    if validation:
        report["validation"] = validation
    passed = bool(
        report["callback_count"] >= REQUIRED_CYCLES
        and report["token_analysis"]["unique_token_count"] >= REQUIRED_CYCLES
        and report["token_analysis"]["duplicate_tokens"] == 0
        and "wrong_app_not_minimal_repro" not in report.get("errors", [])
        and "component_value_sent" in str(final.get("client_chain") or "")
    )
    if validation.get("passed") is True:
        passed = True
    report["passed"] = passed


def main() -> int:
    from playwright.sync_api import sync_playwright

    target = target_url()
    sha = expected_sha()
    report: dict[str, Any] = {
        "started_at": time.time(),
        "target_url": target,
        "expected_sha": sha,
        "console_messages": [],
        "samples": [],
        "errors": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 960, "height": 900})

        def _on_console(msg) -> None:
            text = msg.text
            if "[minimal_wake_repro]" in text or "streamlit" in text.lower():
                report["console_messages"].append(
                    {
                        "type": msg.type,
                        "text": text,
                        "ts": time.time(),
                    }
                )

        page.on("console", _on_console)
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(5000)
            title = page.title()
            report["page_title"] = title
            body_snippet = page.inner_text("body")[:500]
            report["body_snippet"] = body_snippet
            if "Minimal component wake repro" not in body_snippet and "Minimal component wake repro" not in title:
                if "Baseball" in body_snippet or "Live Draft" in body_snippet:
                    report["errors"].append("wrong_app_not_minimal_repro")
            deadline = time.time() + TIMEOUT_S
            best_callbacks = 0
            while time.time() < deadline:
                probe = scrape_probe(page)
                probe["ts"] = time.time()
                cb = int(probe.get("callback_count") or 0)
                best_callbacks = max(best_callbacks, cb)
                if not report["samples"] or report["samples"][-1].get("callback_count") != cb:
                    report["samples"].append(probe)
                if probe.get("passed") and cb >= REQUIRED_CYCLES:
                    break
                if cb >= REQUIRED_CYCLES:
                    break
                page.wait_for_timeout(1000)
            report["final_probe"] = scrape_probe(page)
            report["best_callback_count"] = best_callbacks
            probe_html = page.content()
            has_repro = bool(
                report["final_probe"].get("deploy_sha")
                or report["final_probe"].get("component_name")
                or "#repro-result" in probe_html
            )
            if not has_repro and "wrong_app_not_minimal_repro" not in report["errors"]:
                report["errors"].append("repro_markers_missing")
            seen_sha = str(report.get("final_probe", {}).get("deploy_sha") or "").strip().lower()
            if sha and seen_sha and seen_sha != sha[: len(seen_sha)] and seen_sha != sha:
                report["errors"].append(
                    f"deploy_sha_mismatch:expected={sha}:seen={seen_sha}"
                )
            if best_callbacks < REQUIRED_CYCLES:
                report["errors"].append(f"callbacks_low:{best_callbacks}")
            chain = str(report.get("final_probe", {}).get("client_chain") or "")
            if best_callbacks < REQUIRED_CYCLES and "component_value_sent" not in chain:
                report["errors"].append("client_never_sent_component_value")
            if best_callbacks == 0:
                report["errors"].append("python_never_received_component_value")
            try:
                payload_raw = str(report.get("final_probe", {}).get("payload") or "")
                if payload_raw:
                    report["python_payload"] = json.loads(payload_raw.replace("'", '"'))
            except Exception as exc:
                report["errors"].append(f"payload_parse:{type(exc).__name__}")
        except Exception as exc:
            report["errors"].append(f"{type(exc).__name__}:{exc}")
        finally:
            browser.close()

    report["duration_s"] = round(time.time() - float(report["started_at"]), 1)
    _validate_probe(report)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
