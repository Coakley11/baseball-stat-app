"""Helpers for waking Streamlit Community Cloud apps before deploy probes."""

from __future__ import annotations

import re
import time
from typing import Any


def all_frames_text(page) -> str:
    return page.evaluate(
        """() => {
          function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
          return roots().map((root) => (root.body ? root.body.innerText : '')).join('\\n');
        }"""
    )


def is_app_asleep(text: str) -> bool:
    low = str(text or "").lower()
    return "gone to sleep" in low or "get this app back up" in low or low.strip().startswith("zzzz")


def is_app_waking(text: str) -> bool:
    low = str(text or "").lower()
    return "waking up" in low or "taking longer than normal" in low


def wake_streamlit_app(page, *, wait_ms: int = 3000) -> bool:
    """Click Streamlit Cloud sleep-screen wake button if present."""
    try:
        clicked = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                for (const b of root.querySelectorAll('button, a, [role=\"button\"]')) {
                  const t = String(b.innerText || b.textContent || '').replace(/\\s+/g, ' ').trim();
                  if (!t) continue;
                  const low = t.toLowerCase();
                  if (low.includes('get this app back up') || low.includes('wake it back up') || low === 'yes') {
                    b.click();
                    return true;
                  }
                }
              }
              return false;
            }"""
        )
        if clicked:
            page.wait_for_timeout(wait_ms)
        return bool(clicked)
    except Exception:
        return False


def _p6_writer_probe_present(page) -> bool:
    try:
        return bool(
            page.evaluate(
                """() => {
                  function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
                  for (const root of roots()) {
                    if (root && root.querySelector('#solo-p6-writer-probe')) return true;
                  }
                  return false;
                }"""
            )
        )
    except Exception:
        return False


def ensure_app_awake(page, *, timeout_s: int = 240) -> dict[str, Any]:
    """Wake sleeping app and wait until Streamlit content is loading or ready."""
    deadline = time.time() + timeout_s
    wake_clicks = 0
    last_text = ""
    while time.time() < deadline:
        try:
            text = all_frames_text(page)
            last_text = text
            if is_app_asleep(text):
                if wake_streamlit_app(page):
                    wake_clicks += 1
                else:
                    page.wait_for_timeout(2000)
                continue
            if is_app_waking(text):
                page.wait_for_timeout(3000)
                continue
            if _p6_writer_probe_present(page):
                return {"awake": True, "wake_clicks": wake_clicks, "text_len": len(text.strip()), "p6_probe": True}
            if len(text.strip()) > 200 or "live draft" in text.lower() or "start new live draft" in text.lower():
                return {"awake": True, "wake_clicks": wake_clicks, "text_len": len(text.strip())}
            page.wait_for_timeout(2500)
        except Exception as exc:
            page.wait_for_timeout(2500)
            last_text = f"{type(exc).__name__}:{exc}"
    return {
        "awake": False,
        "wake_clicks": wake_clicks,
        "text_len": len(str(last_text).strip()),
        "text_snippet": str(last_text)[:400],
    }


def goto_and_wake(page, url: str, *, timeout_s: int = 240) -> dict[str, Any]:
    page.goto(url, wait_until="domcontentloaded", timeout=min(240000, max(60000, timeout_s * 1000)))
    return ensure_app_awake(page, timeout_s=timeout_s)


def gentle_wake_if_asleep(page) -> dict[str, Any]:
    """Wake sleep screen only — never page.goto (safe during manual login)."""
    try:
        text = all_frames_text(page)
        if is_app_asleep(text) or is_app_waking(text):
            clicked = wake_streamlit_app(page)
            return {"action": "wake_click" if clicked else "wake_wait", "asleep": True}
    except Exception as exc:
        return {"action": "error", "detail": type(exc).__name__}
    return {"action": "none", "asleep": False}


def scrape_deploy_sha_from_page(page) -> str:
    try:
        raw = page.evaluate(
            """() => {
              function roots(){ const r=[document]; for (const f of document.querySelectorAll('iframe')) { try { r.push(f.contentDocument);} catch(e){} } return r.filter(Boolean); }
              for (const root of roots()) {
                const el = root.querySelector('#solo-deploy-build');
                if (el) return el.getAttribute('data-sha') || '';
                const html = root.documentElement ? root.documentElement.innerHTML : '';
                const m = html.match(/solo-deploy-build sha=([0-9a-f]{7})/i);
                if (m) return m[1];
              }
              return '';
            }"""
        )
        sha = str(raw or "").strip().lower()[:7]
        if sha:
            return sha
    except Exception:
        pass
    try:
        html = page.content()
        for pattern in (
            r'solo-deploy-build sha=([0-9a-f]{7})',
            r'id="solo-deploy-build"[^>]*data-sha="([0-9a-f]{7})"',
            r'baseball-dev-([0-9a-f]{7})',
        ):
            m = re.search(pattern, html, re.I)
            if m:
                return m.group(1).lower()
    except Exception:
        pass
    try:
        text = all_frames_text(page)
        m = re.search(r"baseball-dev-([0-9a-f]{7})", text, re.I)
        if m:
            return m.group(1).lower()
    except Exception:
        pass
    return ""
