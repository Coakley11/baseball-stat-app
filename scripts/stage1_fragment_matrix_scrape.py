"""Scrape Stage1 fragment matrix DOM ownership probes (Playwright)."""

from __future__ import annotations

from typing import Any


def scrape_matrix_probes(page, *, control: str = "") -> list[dict[str, Any]]:
    want = str(control or "").strip().upper()
    try:
        raw = page.evaluate(
            """(wantControl) => {
            const docs = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) docs.push(f.contentDocument); } catch (e) {}
            }
            const rows = [];
            for (const doc of docs) {
              const nodes = doc.querySelectorAll('[data-probe-element="solo-stage1-fragment-identity-matrix-probe"]');
              for (const el of nodes) {
                const row = {
                  control: el.getAttribute('data-control') || '',
                  widget_key: el.getAttribute('data-widget-key') || '',
                  construction: el.getAttribute('data-construction') || '',
                  run_every: el.getAttribute('data-run-every') || '',
                  thread_fragment_id: el.getAttribute('data-thread-fragment-id') || '',
                  metadata_fragment_id: el.getAttribute('data-metadata-fragment-id') || '',
                  widget_owner_fragment_current: el.getAttribute('data-widget-owner-fragment-current') || '',
                  ownership_subcode: el.getAttribute('data-ownership-subcode') || '',
                  render_fragment_in_storage: el.getAttribute('data-render-fragment-in-storage') || '',
                  metadata_fragment_in_storage: el.getAttribute('data-metadata-fragment-in-storage') || '',
                  invocation: el.getAttribute('data-invocation') || '',
                  stored_fragment_id_count: el.getAttribute('data-stored-fragment-id-count') || '',
                };
                if (wantControl && row.control !== wantControl) continue;
                rows.push(row);
              }
            }
            return rows;
          }""",
            want,
        )
    except Exception as exc:
        return [{"error": str(exc)[:200]}]
    return list(raw) if isinstance(raw, list) else []


def latest_probe_for_control(probes: list[dict[str, Any]], control: str) -> dict[str, Any]:
    want = str(control or "").strip().upper()
    matches = [p for p in probes if isinstance(p, dict) and str(p.get("control") or "").upper() == want]
    if not matches:
        return {}
    try:
        return max(matches, key=lambda r: int(r.get("invocation") or 0))
    except (TypeError, ValueError):
        return matches[-1]
