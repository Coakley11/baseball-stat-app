"""Scrape browser-side Streamlit custom-component / iframe widget identities."""

from __future__ import annotations

from typing import Any

PROD_KEY = "solo_countdown_wake_solo_persistent"
CONTROL_KEY_PREFIX = "minimal_wake_repro"


def scrape_browser_widget_identities(page) -> dict[str, Any]:
    return page.evaluate(
        """(prodKey) => {
          function roots() {
            const out = [document];
            for (const f of document.querySelectorAll('iframe')) {
              try { if (f.contentDocument) out.push(f.contentDocument); } catch (e) {}
            }
            return out;
          }
          const idRe = /\\$\\$ID-[a-f0-9]{32}-[^\\s"'<>\\\\]+/gi;
          const out = {
            dom_widget_ids: [],
            production_iframes: [],
            control_iframes: [],
            register_component_messages: [],
          };
          const seen = new Set();
          for (const root of roots()) {
            const html = root.documentElement ? root.documentElement.outerHTML : '';
            let m;
            while ((m = idRe.exec(html)) !== null) {
              const id = m[0];
              if (!seen.has(id)) {
                seen.add(id);
                out.dom_widget_ids.push(id);
              }
            }
            for (const el of root.querySelectorAll('[data-iframe-instance], #solo-expire-client')) {
              const inst = el.getAttribute('data-iframe-instance') || el.getAttribute('data-iframe-instance-id') || '';
              const tok = el.getAttribute('data-token') || '';
              const row = {
                iframe_instance: inst,
                token_preview: String(tok || '').slice(0, 120),
                widget_key: el.getAttribute('data-widget-key') || '',
              };
              const host = el.closest('iframe') || el.ownerDocument.defaultView.frameElement;
              if (host && host.tagName === 'IFRAME') {
                row.host_iframe_src_preview = String(host.src || host.getAttribute('src') || '').slice(0, 160);
              }
              if (String(row.widget_key || '').includes(prodKey) || String(tok).includes('|')) {
                out.production_iframes.push(row);
              } else if (String(row.widget_key || '').includes('minimal_wake')) {
                out.control_iframes.push(row);
              }
            }
          }
          try {
            const h = window.__solo_stage1_harness_top_observer_v1;
            if (h && Array.isArray(h.messages)) {
              for (const msg of h.messages) {
                if (msg.is_register_component || String(msg.message_type || '').includes('register')) {
                  out.register_component_messages.push(msg);
                }
              }
            }
          } catch (e) {}
          out.production_dom_ids = out.dom_widget_ids.filter((id) => id.includes(prodKey));
          out.control_dom_ids = out.dom_widget_ids.filter((id) => id.includes('minimal_wake'));
          return out;
        }""",
        PROD_KEY,
    )


def pick_browser_id_for_key(scrape: dict[str, Any], user_key: str) -> str:
    ids = [
        i
        for i in (scrape.get("dom_widget_ids") or [])
        if isinstance(i, str) and user_key in i
    ]
    if user_key == PROD_KEY and scrape.get("production_dom_ids"):
        ids = list(scrape.get("production_dom_ids") or []) + ids
    return ids[-1] if ids else ""
