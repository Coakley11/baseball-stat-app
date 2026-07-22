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
        return "http://localhost:8501"
    return DEFAULT_CLOUD_BASE.rstrip("/")


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
          }
          return out;
        }"""
    )


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
            report["console_messages"].append(
                {
                    "type": msg.type,
                    "text": msg.text,
                    "ts": time.time(),
                }
            )

        page.on("console", _on_console)
        try:
            page.goto(target, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(5000)
            title = page.title()
            report["page_title"] = title
            if "Minimal Component Wake Repro" not in title and "#repro-result" not in page.content():
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
                    report["passed"] = True
                    break
                if cb >= REQUIRED_CYCLES:
                    report["passed"] = True
                    break
                page.wait_for_timeout(1000)
            report["final_probe"] = scrape_probe(page)
            report["best_callback_count"] = best_callbacks
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
    report["passed"] = bool(
        int(report.get("best_callback_count") or 0) >= REQUIRED_CYCLES
        and "wrong_app_not_minimal_repro" not in report["errors"]
        and not [e for e in report["errors"] if not e.startswith("deploy_sha_mismatch")]
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
