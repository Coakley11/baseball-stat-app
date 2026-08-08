"""Scrape app-side rec-card queue click trace DOM probe (solo_component_diag)."""

from __future__ import annotations

import json
from typing import Any


def scrape_rec_queue_render_trace(page, *, player_name: str = "") -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """(playerName) => {
            const docs = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {}
            }
            const want = String(playerName || '').trim().toLowerCase();
            for (const doc of docs) {
              const el = doc.querySelector('#rec-card-queue-render-trace');
              if (!el) continue;
              const row = {
                room_id: el.getAttribute('data-room-id') || '',
                player_name: el.getAttribute('data-player-name') || '',
                player_id: el.getAttribute('data-player-id') || '',
                pick_index: el.getAttribute('data-pick-index') || '',
                widget_key: el.getAttribute('data-widget-key') || '',
                callback_id: el.getAttribute('data-callback-id') || '',
                registry_len: el.getAttribute('data-registry-len') || '',
                app_sha: el.getAttribute('data-app-sha') || '',
                json: el.getAttribute('data-json') || '',
              };
              if (want && row.player_name && row.player_name.toLowerCase() !== want) {
                const payload = row.json || '';
                if (!payload.toLowerCase().includes(want)) continue;
              }
              return row;
            }
            return {};
          }""",
            player_name,
        )
    except Exception as exc:
        return {"error": str(exc)[:200]}
    if not isinstance(raw, dict):
        return {}
    out = dict(raw)
    if out.get("json"):
        try:
            out["payload"] = json.loads(str(out["json"]).replace("'", '"'))
        except Exception:
            pass
    return out


def merge_render_trace_into_step(step: dict[str, Any], trace: dict[str, Any]) -> None:
    if not trace or not trace.get("widget_key") and not trace.get("json"):
        return
    step["app_render_trace"] = trace
    step["render_trace_present"] = bool(trace.get("widget_key") or trace.get("json"))
    step["expected_widget_key"] = str(trace.get("widget_key") or "")
    step["render_callback_id"] = str(trace.get("callback_id") or "")


def scrape_rec_queue_app_trace(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
            const docs = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {}
            }
            for (const doc of docs) {
              const el = doc.querySelector('#rec-card-queue-click-trace');
              if (!el) continue;
              return {
                event_id: el.getAttribute('data-event-id') || '',
                callback_entered: el.getAttribute('data-callback-entered') === '1',
                added: el.getAttribute('data-added') === '1',
                classification: el.getAttribute('data-classification') || '',
                json: el.getAttribute('data-json') || '',
              };
            }
            return {};
          }"""
        )
    except Exception as exc:
        return {"error": str(exc)[:200]}
    if not isinstance(raw, dict):
        return {}
    out = dict(raw)
    payload = out.get("json")
    if isinstance(payload, str) and payload.strip():
        try:
            out["payload"] = json.loads(payload.replace("'", '"'))
        except Exception:
            out["payload_raw"] = payload[:2000]
    return out


def merge_app_trace_into_step(step: dict[str, Any], trace: dict[str, Any]) -> None:
    if not trace:
        return
    step["app_queue_trace"] = trace
    app_class = str(trace.get("classification") or "").strip()
    if app_class:
        step["app_classification"] = app_class
    payload = trace.get("payload") if isinstance(trace.get("payload"), dict) else {}
    last = payload.get("last") if isinstance(payload.get("last"), dict) else {}
    if last:
        step["app_callback_entered"] = bool(last.get("callback_entered"))
        step["app_queue_after_mutation"] = list(last.get("queue_immediately_after_mutation") or [])
        post = last.get("post_prepare") if isinstance(last.get("post_prepare"), dict) else {}
        if post:
            step["app_queue_after_prepare"] = list(post.get("queue_after_rerun_hydration") or [])
