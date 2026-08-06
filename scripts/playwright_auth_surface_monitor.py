"""Track all Playwright browser surfaces during headed OAuth capture (harness only)."""

from __future__ import annotations

import time
import uuid
from typing import Any
from urllib.parse import urlparse

from playwright_auth_capture_diag import (
    CaptureTraceCollector,
    is_cloud_app_url,
    is_oauth_callback_url,
    is_provider_url,
)
from playwright_auth_preflight_strict import suite_sid_from_url


def _page_label(page: Any) -> str:
    try:
        return str(page.url or "")[:200]
    except Exception:
        return ""


class BrowserSurfaceMonitor:
    """Observe popups, replacements, iframes, and select the Cloud app page for ledger scrape."""

    def __init__(
        self,
        *,
        context: Any,
        target_sid: str,
        collector: CaptureTraceCollector,
    ) -> None:
        self._context = context
        self._target_sid = str(target_sid or "").strip()
        self._collector = collector
        self._pages: dict[str, Any] = {}
        self._page_records: list[dict[str, Any]] = []
        self._iframe_transitions: list[dict[str, Any]] = []
        self._selected_app_page_id = ""
        self.sign_in_click_attempted = False
        self.sign_in_initiated = False
        self.provider_surface_seen = False
        self.oauth_callback_seen = False
        self.returned_to_cloud_after_provider = False
        self.signed_in_display_any_surface = False
        self._provider_before_cloud = False
        self._provider_login_active = False
        self._harness_control_events: list[dict[str, Any]] = []
        self._last_monitored_cloud_page_id = ""

    def record_harness_event(
        self,
        cause: str,
        *,
        page_id: str = "",
        detail: str = "",
        url_host: str = "",
    ) -> None:
        self._harness_control_events.append(
            {
                "ts": time.time(),
                "cause": cause[:80],
                "page_id": page_id[:12],
                "detail": detail[:200],
                "url_host": url_host[:80],
            }
        )

    def provider_login_in_progress(self) -> bool:
        """True while any live page or iframe is on a provider OAuth host."""
        for pg in self._context.pages:
            if pg.is_closed():
                continue
            try:
                if is_provider_url(pg.url or ""):
                    return True
                for frame in pg.frames:
                    if is_provider_url(frame.url or ""):
                        return True
            except Exception:
                continue
        return False

    def cloud_app_page(self) -> Any | None:
        """Baseball Cloud tab with target suite_sid (never a provider URL)."""
        for pg in self._context.pages:
            if pg.is_closed():
                continue
            try:
                u = pg.url or ""
                if is_cloud_app_url(u) and suite_sid_from_url(u) == self._target_sid:
                    return pg
            except Exception:
                continue
        return None

    def provider_pages(self) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        for pid, pg in self._pages.items():
            if pg.is_closed():
                continue
            try:
                if is_provider_url(pg.url or ""):
                    out.append((pid, pg))
            except Exception:
                pass
        for pg in self._context.pages:
            if pg.is_closed():
                continue
            try:
                if is_provider_url(pg.url or ""):
                    pid = next((k for k, v in self._pages.items() if v is pg), "")
                    out.append((pid or "unknown", pg))
            except Exception:
                pass
        return out

    def wire(self, initial_page: Any) -> None:
        self._context.on("page", self._on_context_page)
        self._register_page(initial_page, role="initial")

    def mark_sign_in_click_attempted(self) -> None:
        self.sign_in_click_attempted = True
        self.sign_in_initiated = True

    def _on_context_page(self, page: Any) -> None:
        self.record_harness_event("popup_or_new_page_opened")
        self._register_page(page, role="popup")

    def _register_page(self, page: Any, *, role: str) -> None:
        pid = str(uuid.uuid4())[:12]
        self._pages[pid] = page
        rec = {
            "page_id": pid,
            "role": role,
            "created_at": time.time(),
            "closed_at": None,
            "urls": [],
        }
        self._page_records.append(rec)

        def on_close() -> None:
            rec["closed_at"] = time.time()
            host = urlparse(rec["urls"][-1]).netloc[:80] if rec.get("urls") else ""
            was_provider = any(is_provider_url(u) for u in rec.get("urls") or [])
            self.record_harness_event(
                "provider_page_closed" if was_provider else "page_closed",
                page_id=pid,
                url_host=host,
            )

        try:
            page.on("close", on_close)
        except Exception:
            pass

        def attach_frame(frame: Any) -> None:
            try:

                def on_nav(_: Any) -> None:
                    self._note_frame_nav(pid, frame)

                frame.on("framenavigated", on_nav)
            except Exception:
                pass

        try:
            page.on("frameattached", attach_frame)
            for frame in page.frames:
                attach_frame(frame)
        except Exception:
            pass

        self._collector.attach(page)
        self._note_page_url(pid, _page_label(page), label=f"page_open:{role}")

    def _note_page_url(self, page_id: str, url: str, *, label: str = "") -> None:
        u = str(url or "").strip()
        if not u or u == "about:blank":
            return
        for rec in self._page_records:
            if rec["page_id"] == page_id:
                if rec["urls"] and rec["urls"][-1] == u:
                    break
                rec["urls"].append(u[:512])
                break
        self._collector.note_url(u, label=label or page_id)
        self._consume_url(u, page_id=page_id, surface="page")

    def _note_frame_nav(self, page_id: str, frame: Any) -> None:
        try:
            url = str(frame.url or "")
        except Exception:
            return
        if not url or url == "about:blank":
            return
        self._iframe_transitions.append(
            {
                "ts": time.time(),
                "page_id": page_id,
                "frame_url_host": urlparse(url).netloc[:80],
                "is_provider": is_provider_url(url),
                "is_cloud_app": is_cloud_app_url(url),
                "is_oauth_callback": is_oauth_callback_url(url),
            }
        )
        self._consume_url(url, page_id=page_id, surface="iframe")

    def _consume_url(self, url: str, *, page_id: str, surface: str) -> None:
        if is_provider_url(url):
            self.provider_surface_seen = True
            self.sign_in_initiated = True
            self._provider_before_cloud = True
        if is_oauth_callback_url(url):
            self.oauth_callback_seen = True
        if self._provider_before_cloud and is_cloud_app_url(url) and suite_sid_from_url(url) == self._target_sid:
            self.returned_to_cloud_after_provider = True
        if is_cloud_app_url(url) and suite_sid_from_url(url) == self._target_sid:
            self._selected_app_page_id = page_id

    def poll(self, *, passive_only: bool = False) -> None:
        """Refresh URL/sign-in state from every live page and iframe."""
        prev_provider = self._provider_login_active
        self._provider_login_active = self.provider_login_in_progress()
        if self._provider_login_active and not prev_provider:
            self.record_harness_event("provider_login_became_active")
        if prev_provider and not self._provider_login_active:
            self.record_harness_event("provider_login_ended_natural")

        self.signed_in_display_any_surface = False
        for pid, pg in list(self._pages.items()):
            if pg.is_closed():
                continue
            if passive_only and is_provider_url(pg.url or ""):
                try:
                    self._note_page_url(pid, pg.url or "", label="poll_passive")
                except Exception:
                    pass
                continue
            try:
                self._note_page_url(pid, pg.url or "", label="poll")
            except Exception:
                pass
            try:
                signed = bool(
                    pg.evaluate(
                        """() => {
                      const roots = [document];
                      for (const f of document.querySelectorAll('iframe')) {
                        try { if (f.contentDocument) roots.push(f.contentDocument); } catch (e) {}
                      }
                      return roots.some(r => ((r.body && r.body.innerText) || '').includes('Signed in as'));
                    }"""
                    )
                )
                if signed:
                    self.signed_in_display_any_surface = True
            except Exception:
                pass
            try:
                for frame in pg.frames:
                    fu = frame.url or ""
                    if fu and fu != "about:blank":
                        self._consume_url(fu, page_id=pid, surface="iframe_poll")
            except Exception:
                pass
        if not self._selected_app_page_id:
            for pid, pg in self._pages.items():
                if pg.is_closed():
                    continue
                try:
                    if is_cloud_app_url(pg.url or "") and suite_sid_from_url(pg.url or "") == self._target_sid:
                        self._selected_app_page_id = pid
                        break
                except Exception:
                    continue

    def app_page(self, fallback: Any) -> Any | None:
        """Cloud app page for ledger scrape; does not prefer provider tabs."""
        cloud = self.cloud_app_page()
        if cloud is not None:
            pid = next((k for k, v in self._pages.items() if v is cloud), "")
            if pid and pid != self._last_monitored_cloud_page_id:
                self._last_monitored_cloud_page_id = pid
                self.record_harness_event("context_page_selection_change", page_id=pid, detail="cloud_app_page")
            return cloud
        if self.provider_login_in_progress():
            return None
        if fallback is not None and not fallback.is_closed():
            if not is_provider_url(fallback.url or ""):
                return fallback
        return None

    def sync_identity(self, identity: dict[str, Any]) -> None:
        identity["sign_in_click_attempted"] = self.sign_in_click_attempted
        identity["sign_in_initiated"] = self.sign_in_initiated
        identity["provider_login_seen"] = self.provider_surface_seen
        identity["oauth_callback_seen"] = self.oauth_callback_seen
        identity["returned_to_app_after_provider"] = self.returned_to_cloud_after_provider
        identity["signed_in_display"] = self.signed_in_display_any_surface

    def diagnostic_blob(self) -> dict[str, Any]:
        pages_out = []
        for rec in self._page_records:
            pages_out.append(
                {
                    "page_id": rec["page_id"],
                    "role": rec["role"],
                    "created_at": rec["created_at"],
                    "closed_at": rec["closed_at"],
                    "url_count": len(rec["urls"]),
                    "last_url_host": urlparse(rec["urls"][-1]).netloc[:80] if rec["urls"] else "",
                }
            )
        return {
            "selected_app_page_id": self._selected_app_page_id,
            "pages": pages_out,
            "iframe_transitions": self._iframe_transitions[-60:],
            "provider_surface_seen": self.provider_surface_seen,
            "oauth_callback_seen": self.oauth_callback_seen,
            "signed_in_display_any_surface": self.signed_in_display_any_surface,
            "provider_login_active": self._provider_login_active,
            "harness_control_events": self._harness_control_events[-80:],
        }
