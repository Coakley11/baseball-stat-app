"""Harness helper: resolve Streamlit connected server URI from browser traffic."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

STREAM_SUFFIX = "/_stcore/stream"
HEALTH_SUFFIX = "/_stcore/health"
HOST_CONFIG_SUFFIX = "/_stcore/host-config"

SOURCE_WEBSOCKET_STREAM = "websocket_stcore_stream"
SOURCE_HEALTH = "http_stcore_health"
SOURCE_HOST_CONFIG = "http_stcore_host_config"


def _scheme_http_from_ws(scheme: str) -> str:
    s = str(scheme or "").lower()
    if s == "wss":
        return "https"
    if s == "ws":
        return "http"
    if s in ("http", "https"):
        return s
    return "https" if s.endswith("s") else "http"


def connected_server_uri_from_stcore_url(url: str) -> str | None:
    """Derive connected server base from a _stcore stream/health/host-config URL."""
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return None
    path = parsed.path or ""
    for suffix in (STREAM_SUFFIX, HEALTH_SUFFIX, HOST_CONFIG_SUFFIX):
        if path.endswith(suffix) or f"{suffix}" in path:
            # Prefer exact suffix at end; otherwise split on first occurrence.
            idx = path.find(suffix)
            if idx < 0:
                continue
            prefix = path[:idx].rstrip("/")
            scheme = _scheme_http_from_ws(parsed.scheme)
            return urlunparse((scheme, parsed.netloc, prefix, "", "", ""))
    return None


def join_connected_server_static_url(connected_server_uri: str, static_url_path: str) -> str:
    """Join connected server base with server-relative static path (no doubled slashes)."""
    base = str(connected_server_uri or "").strip().rstrip("/")
    path = str(static_url_path or "").strip()
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def resolve_connected_server_uri(
    *,
    websocket_urls: list[str] | None = None,
    health_endpoints: list[dict[str, Any]] | None = None,
    host_config_endpoints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve using hierarchy: WebSocket stream > health > host-config."""
    out: dict[str, Any] = {
        "uri": "",
        "source": "",
        "ok": False,
        "websocket_urls": list(websocket_urls or []),
        "health_endpoints": list(health_endpoints or []),
        "host_config_endpoints": list(host_config_endpoints or []),
    }
    for ws in websocket_urls or []:
        if STREAM_SUFFIX not in str(ws):
            continue
        uri = connected_server_uri_from_stcore_url(ws)
        if uri:
            out["uri"] = uri
            out["source"] = SOURCE_WEBSOCKET_STREAM
            out["ok"] = True
            out["observed_url"] = ws
            return out
    for ep in health_endpoints or []:
        if not isinstance(ep, dict):
            continue
        status = int(ep.get("status") or 0)
        if status not in (200, 204):
            continue
        url = str(ep.get("url") or "")
        if HEALTH_SUFFIX not in url:
            continue
        uri = connected_server_uri_from_stcore_url(url)
        if uri:
            out["uri"] = uri
            out["source"] = SOURCE_HEALTH
            out["ok"] = True
            out["observed_url"] = url
            return out
    for ep in host_config_endpoints or []:
        if not isinstance(ep, dict):
            continue
        status = int(ep.get("status") or 0)
        if status not in (200, 204):
            continue
        url = str(ep.get("url") or "")
        if HOST_CONFIG_SUFFIX not in url:
            continue
        uri = connected_server_uri_from_stcore_url(url)
        if uri:
            out["uri"] = uri
            out["source"] = SOURCE_HOST_CONFIG
            out["ok"] = True
            out["observed_url"] = url
            return out
    return out


def safe_endpoint_summary(method: str, url: str, status: int | None, content_type: str = "") -> dict[str, Any]:
    return {
        "method": str(method or "")[:16],
        "url": str(url or "")[:300],
        "status": int(status or 0),
        "content_type": str(content_type or "")[:120],
    }


class ConnectedServerUriCapture:
    """Attach to a Playwright page before first navigation; resolve after connect."""

    def __init__(self) -> None:
        self.websocket_urls: list[str] = []
        self.health_endpoints: list[dict[str, Any]] = []
        self.host_config_endpoints: list[dict[str, Any]] = []
        self._attached = False

    def attach(self, page: Any) -> None:
        if self._attached:
            return

        def on_websocket(ws: Any) -> None:
            url = str(getattr(ws, "url", "") or "")
            if STREAM_SUFFIX in url and url not in self.websocket_urls:
                self.websocket_urls.append(url)

        def on_response(response: Any) -> None:
            try:
                req = response.request
                url = str(getattr(req, "url", "") or "")
                method = str(getattr(req, "method", "") or "GET")
                status = int(getattr(response, "status", 0) or 0)
                ctype = ""
                try:
                    headers = getattr(response, "headers", {}) or {}
                    ctype = str(headers.get("content-type") or headers.get("Content-Type") or "")
                except Exception:
                    ctype = ""
                if HEALTH_SUFFIX in url:
                    self.health_endpoints.append(safe_endpoint_summary(method, url, status, ctype))
                elif HOST_CONFIG_SUFFIX in url:
                    self.host_config_endpoints.append(safe_endpoint_summary(method, url, status, ctype))
            except Exception:
                return

        page.on("websocket", on_websocket)
        page.on("response", on_response)
        self._attached = True

    def resolve(self) -> dict[str, Any]:
        resolved = resolve_connected_server_uri(
            websocket_urls=self.websocket_urls,
            health_endpoints=self.health_endpoints,
            host_config_endpoints=self.host_config_endpoints,
        )
        resolved["endpoint_summaries"] = {
            "websockets": [{"url": u} for u in self.websocket_urls],
            "health": list(self.health_endpoints),
            "host_config": list(self.host_config_endpoints),
        }
        return resolved
