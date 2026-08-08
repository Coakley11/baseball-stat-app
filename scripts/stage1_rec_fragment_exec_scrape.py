"""Scrape recommendation-fragment execution probes and durable callback ledger."""

from __future__ import annotations

import json
from typing import Any


def scrape_fragment_callback_ledger(page) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """() => {
            const docs = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {}
            }
            for (const doc of docs) {
              const el = doc.querySelector('#solo-stage1-rec-fragment-callback-ledger');
              if (!el) continue;
              return {
                ledger_len: el.getAttribute('data-ledger-len') || '',
                last_callback_entered: el.getAttribute('data-last-callback-entered') || '',
                last_source: el.getAttribute('data-last-source') || '',
                last_event_id: el.getAttribute('data-last-event-id') || '',
                probe_click_count: el.getAttribute('data-probe-click-count') || '',
                impl_rev: el.getAttribute('data-impl-rev') || '',
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
    if out.get("json"):
        try:
            out["payload"] = json.loads(str(out["json"]).replace("'", '"'))
        except Exception:
            pass
    return out


def scrape_fragment_exec_probes(page, *, widget_kind: str = "") -> list[dict[str, Any]]:
    try:
        raw = page.evaluate(
            """(kindFilter) => {
            const docs = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {}
            }
            const want = String(kindFilter || '').trim();
            const rows = [];
            for (const doc of docs) {
              const nodes = doc.querySelectorAll('[data-probe-element="solo-stage1-rec-fragment-exec-diag"], .rec-fragment-exec-probe-card');
              for (const el of nodes) {
                const row = {
                  widget_kind: el.getAttribute('data-widget-kind') || '',
                  room_id: el.getAttribute('data-room-id') || '',
                  pick_index: el.getAttribute('data-pick-index') || '',
                  player_name: el.getAttribute('data-player-name') || '',
                  widget_key: el.getAttribute('data-widget-key') || '',
                  callback_id: el.getAttribute('data-callback-id') || '',
                  full_app_run_seq: el.getAttribute('data-full-app-run-seq') || '',
                  recommendation_fragment_run_seq: el.getAttribute('data-recommendation-fragment-run-seq') || '',
                  fragment_context: el.getAttribute('data-fragment-context') || '',
                  paint_via: el.getAttribute('data-paint-via') || '',
                  impl_rev: el.getAttribute('data-impl-rev') || '',
                };
                if (want && row.widget_kind !== want) continue;
                rows.push(row);
              }
            }
            return rows;
          }""",
            widget_kind,
        )
    except Exception as exc:
        return [{"error": str(exc)[:200]}]
    return list(raw) if isinstance(raw, list) else []


def classify_fragment_exec_comparison(
    *,
    pause_functional: bool,
    probe_ledger_last: dict[str, Any] | None,
    francisco_ledger_last: dict[str, Any] | None,
    probe_dom_click: bool,
    francisco_dom_click: bool,
) -> str:
    """F1–F4 scaffolding for focused fragment gate (not emitted without full evidence)."""
    probe_entered = bool((probe_ledger_last or {}).get("callback_entered"))
    fr_entered = bool((francisco_ledger_last or {}).get("callback_entered"))
    if pause_functional and probe_dom_click and probe_entered and francisco_dom_click and not fr_entered:
        return "QUEUE1C3A2F1"
    if pause_functional and probe_dom_click and not probe_entered and francisco_dom_click and not fr_entered:
        return "QUEUE1C3A2F4"
    if fr_entered or probe_entered:
        return "QUEUE1C3A2F2_CANDIDATE"
    return ""
