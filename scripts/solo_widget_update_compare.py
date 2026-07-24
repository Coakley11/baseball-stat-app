"""Capture widget-update metadata for minimal vs Case A vs Case B comparisons."""

from __future__ import annotations

import json
import re
import time
from typing import Any


def install_compare_hooks(page, store: dict[str, Any]) -> None:
    store.setdefault("ws_frames", [])
    store.setdefault("post_messages", [])
    page.evaluate(
        """() => {
          window.__soloWidgetCompare = window.__soloWidgetCompare || {
            postMessages: [],
            streamlitHints: {},
          };
          if (!window.__soloWidgetCompareHooks) {
            window.addEventListener('message', (ev) => {
              const d = ev && ev.data;
              if (!d) return;
              if (d.type === 'streamlit:setComponentValue') {
                window.__soloWidgetCompare.postMessages.push({
                  ts: Date.now(),
                  type: d.type,
                  value: String((d.value && d.value.value) || d.value || '').slice(0, 400),
                });
              }
            }, true);
            window.__soloWidgetCompareHooks = true;
          }
          try {
            const root = window.parent !== window ? window.parent : window;
            const hints = {};
            for (const key of Object.keys(root)) {
              if (!/streamlit/i.test(key)) continue;
              hints[key] = typeof root[key];
            }
            window.__soloWidgetCompare.streamlitHints = hints;
          } catch (e) {}
        }"""
    )

    def _on_ws(ws):
        def _record(payload: Any) -> None:
            text = payload if isinstance(payload, str) else str(payload)
            lowered = text.lower()
            if not any(
                x in lowered or x in text
                for x in (
                    "setcomponentvalue",
                    "widget",
                    "minimal_wake",
                    "solo_countdown",
                    "repro|",
                    "component",
                )
            ):
                return
            store["ws_frames"].append(
                {
                    "ts": time.time(),
                    "snippet": text[:1200],
                    "len": len(text),
                }
            )

        ws.on("framesent", _record)
        ws.on("framereceived", _record)

    page.on("websocket", _on_ws)


def scrape_client_chain(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          function roots() {
            const out = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) out.push(f.contentDocument); } catch (e) {}
            }
            return out.filter(Boolean);
          }
          const out = {
            repro_client: null,
            solo_expire_client: null,
            case_a: null,
            delivery: null,
            page_url: location.href,
            title: document.title,
          };
          for (const root of roots()) {
            const repro = root.querySelector('#repro-client');
            if (repro) {
              out.repro_client = {
                last: repro.getAttribute('data-last') || '',
                chain: repro.getAttribute('data-chain') || '',
              };
            }
            const solo = root.querySelector('#solo-expire-client');
            if (solo) {
              out.solo_expire_client = {
                last: solo.getAttribute('data-last') || '',
                chain: solo.getAttribute('data-chain') || '',
                token: solo.getAttribute('data-token') || '',
              };
            }
            const caseA = root.querySelector('#solo-case-a-diag');
            if (caseA) {
              out.case_a = {
                passed: caseA.getAttribute('data-passed') || '',
                callbacks: caseA.getAttribute('data-callbacks') || '',
                key: caseA.getAttribute('data-key') || '',
                token: caseA.getAttribute('data-token') || '',
                stages: caseA.getAttribute('data-stages') || '',
                json: caseA.getAttribute('data-json') || '',
              };
            }
            const delivery = root.querySelector('#solo-delivery-diag');
            if (delivery) {
              out.delivery = {
                case: delivery.getAttribute('data-case') || '',
                key: delivery.getAttribute('data-key') || '',
                stages: delivery.getAttribute('data-stages') || '',
                rerun: delivery.getAttribute('data-rerun') || '',
              };
            }
          }
          return out;
        }"""
    )


def parse_python_delivery(stages_chain: str, json_blob: str) -> dict[str, Any]:
    stages = [p for p in str(stages_chain or "").split("|") if p]
    payload: dict[str, Any] = {}
    if json_blob:
        try:
            payload = json.loads(json_blob.replace("'", '"'))
        except json.JSONDecodeError:
            payload = {"raw": json_blob[:500]}
    callbacks = payload.get("callbacks") if isinstance(payload.get("callbacks"), list) else []
    return {
        "python_stages": stages,
        "callback_count": len(callbacks),
        "callbacks": callbacks[-8:],
        "cycles_done": payload.get("cycles_done"),
        "diag": payload.get("diag") if isinstance(payload.get("diag"), dict) else {},
    }


def extract_ws_tokens(ws_frames: list[dict[str, Any]]) -> list[str]:
    tokens: list[str] = []
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        for match in re.finditer(r"repro\|\d+\|[0-9.]+", snippet):
            tokens.append(match.group(0))
        for match in re.finditer(r"[A-F0-9]{8}\|\d+\|[0-9.]+", snippet):
            tokens.append(match.group(0))
    return tokens


def summarize_environment(
    *,
    label: str,
    component_name: str,
    scrape: dict[str, Any],
    ws_frames: list[dict[str, Any]],
    post_messages: list[dict[str, Any]],
    page_url: str,
) -> dict[str, Any]:
    repro = scrape.get("repro_client") or {}
    solo = scrape.get("solo_expire_client") or {}
    case_a = scrape.get("case_a") or {}
    delivery = scrape.get("delivery") or {}
    client_chain = str(repro.get("chain") or solo.get("chain") or "")
    python_blob = str(case_a.get("json") or "")
    python_stages_chain = str(case_a.get("stages") or delivery.get("stages") or "")
    python = parse_python_delivery(python_stages_chain, python_blob)
    widget_key = (
        str(case_a.get("key") or "")
        or str(delivery.get("key") or "")
        or str((python.get("diag") or {}).get("widget_key") or "")
    )
    ws_tokens = extract_ws_tokens(ws_frames)
    pm_values = [str(m.get("value") or "") for m in post_messages if m.get("type") == "streamlit:setComponentValue"]
    return {
        "label": label,
        "page_url": page_url,
        "component_name": component_name,
        "widget_key": widget_key,
        "streamlit_widget_id": _guess_widget_id(ws_frames, widget_key),
        "page_script_hash": _guess_script_hash(ws_frames),
        "fragment_id": "",
        "script_run_identifier": str(delivery.get("rerun") or case_a.get("rerun") or ""),
        "client_chain": client_chain,
        "client_last": str(repro.get("last") or solo.get("last") or ""),
        "tokens_in_websocket_frames": ws_tokens[-6:],
        "tokens_in_postmessage": pm_values[-6:],
        "websocket_frame_count": len(ws_frames),
        "postmessage_count": len(post_messages),
        "widget_registered_at_send": None,
        "reruns_between_mount_and_send": int(delivery.get("rerun") or case_a.get("rerun") or 0) or None,
        "python_session_state_result": python,
        "browser_deadline_crossed": "browser_deadline_crossed" in client_chain,
        "setComponentValue_called": "component_value_sent" in client_chain
        or "setComponentValue_called" in client_chain,
    }


def _guess_widget_id(ws_frames: list[dict[str, Any]], widget_key: str) -> str:
    if not widget_key:
        return ""
    for frame in reversed(ws_frames):
        snippet = str(frame.get("snippet") or "")
        if widget_key in snippet:
            m = re.search(r'"id"\s*:\s*"([^"]+)"', snippet)
            if m:
                return m.group(1)
    return ""


def _guess_script_hash(ws_frames: list[dict[str, Any]]) -> str:
    for frame in ws_frames:
        snippet = str(frame.get("snippet") or "")
        m = re.search(r"scriptRunId[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", snippet)
        if m:
            return m.group(1)
        m = re.search(r"runId[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)", snippet)
        if m:
            return m.group(1)
    return ""


def diff_environments(envs: list[dict[str, Any]]) -> str:
    if len(envs) < 2:
        return ""
    baseline = envs[0]
    for env in envs[1:]:
        if baseline.get("python_session_state_result", {}).get("callback_count", 0) >= 4 and (
            env.get("python_session_state_result", {}).get("callback_count", 0) == 0
        ):
            return (
                f"{env['label']}: browser sent widget updates "
                f"(ws={env.get('websocket_frame_count')}, postMessage={env.get('postmessage_count')}) "
                f"but Python recorded zero deliveries — likely stale widget registration vs "
                f"{baseline['label']} (widget_key={env.get('widget_key')}, "
                f"script_run={env.get('script_run_identifier')})."
            )
        if baseline.get("setComponentValue_called") and not env.get("setComponentValue_called"):
            return f"{env['label']}: client never reached component_value_sent (baseline did)."
    return ""
