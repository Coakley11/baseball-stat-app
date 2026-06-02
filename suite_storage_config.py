"""
Supabase credentials for shared suite activity (all deployments).

Streamlit Cloud → Settings → Secrets (paste TOML below).
Same block on Command Center and every suite app.

Environment fallback (local / CI):
  SUITE_SUPABASE_URL
  SUITE_SUPABASE_KEY
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

EXPECTED_SECRETS_TOML = """\
[suite_activity]
supabase_url = "https://YOUR_PROJECT_REF.supabase.co"
supabase_key = "YOUR_SERVICE_ROLE_KEY"
"""


@dataclass(frozen=True)
class SuiteCloudConfig:
    url: str
    key: str


@dataclass(frozen=True)
class SecretsProbe:
    """Safe diagnostics — never exposes secret values."""

    env_supabase_url_set: bool
    env_supabase_key_set: bool
    streamlit_secrets_available: bool
    suite_activity_section_found: bool
    supabase_url_found: bool
    supabase_key_found: bool
    top_level_url_found: bool
    top_level_key_found: bool
    secrets_error: str
    resolved_source: str  # env | suite_activity | top_level | none


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _mapping_get(block: Any, *names: str) -> str:
    """Read from dict or Streamlit Secrets section (not always isinstance(dict))."""
    if block is None:
        return ""
    for name in names:
        val: Any = None
        if isinstance(block, Mapping):
            val = block.get(name)
        elif hasattr(block, "get"):
            try:
                val = block.get(name)
            except Exception:
                val = None
        if val is None and hasattr(block, name):
            try:
                val = getattr(block, name)
            except Exception:
                val = None
        cleaned = _coerce_str(val)
        if cleaned:
            return cleaned
    return ""


def _empty_probe(*, secrets_error: str = "") -> SecretsProbe:
    return SecretsProbe(
        env_supabase_url_set=bool(os.environ.get("SUITE_SUPABASE_URL", "").strip()),
        env_supabase_key_set=bool(os.environ.get("SUITE_SUPABASE_KEY", "").strip()),
        streamlit_secrets_available=False,
        suite_activity_section_found=False,
        supabase_url_found=False,
        supabase_key_found=False,
        top_level_url_found=False,
        top_level_key_found=False,
        secrets_error=secrets_error,
        resolved_source="none",
    )


def _from_streamlit_secrets() -> tuple[str, str, SecretsProbe]:
    """Return (url, key, probe). Never raises."""
    try:
        import streamlit as st  # noqa: WPS433

        probe = replace(
            _empty_probe(),
            streamlit_secrets_available=True,
        )
        root = st.secrets
        block = None
        try:
            block = root.get("suite_activity")
        except Exception:
            try:
                block = root["suite_activity"]
            except Exception as exc:
                return "", "", replace(probe, secrets_error=f"suite_activity missing: {exc}")

        if block is not None:
            probe = replace(probe, suite_activity_section_found=True)
            url = _mapping_get(block, "supabase_url", "url", "SUPABASE_URL")
            key = _mapping_get(
                block, "supabase_key", "service_role_key", "key", "SUPABASE_KEY"
            )
            probe = replace(
                probe,
                supabase_url_found=bool(url),
                supabase_key_found=bool(key),
            )
            if url and key:
                return url, key, replace(probe, resolved_source="suite_activity")

        top_url = _mapping_get(root, "supabase_url", "SUITE_SUPABASE_URL", "url")
        top_key = _mapping_get(
            root, "supabase_key", "service_role_key", "SUITE_SUPABASE_KEY", "key"
        )
        probe = replace(
            probe,
            top_level_url_found=bool(top_url),
            top_level_key_found=bool(top_key),
        )
        if top_url and top_key:
            return top_url, top_key, replace(probe, resolved_source="top_level")

        if block is not None and not probe.supabase_url_found:
            err = (
                "[suite_activity] exists but supabase_url / supabase_key not found. "
                "Use exact key names (see admin panel TOML example)."
            )
        elif block is None:
            err = (
                "No [suite_activity] section in Streamlit secrets. "
                "Paste the TOML block from .streamlit/secrets.toml.example."
            )
        else:
            err = "supabase_url and supabase_key must both be set under [suite_activity]."
        return "", "", replace(probe, secrets_error=err)
    except Exception as exc:
        return "", "", _empty_probe(secrets_error=f"st.secrets unavailable: {exc}")


def probe_secrets() -> SecretsProbe:
    """Inspect how credentials would resolve (clears config cache)."""
    reset_cloud_config_cache()
    url = os.environ.get("SUITE_SUPABASE_URL", "").strip()
    key = os.environ.get("SUITE_SUPABASE_KEY", "").strip()
    if url and key:
        return replace(_empty_probe(), resolved_source="env")
    _, _, probe = _from_streamlit_secrets()
    return probe


@lru_cache(maxsize=1)
def get_cloud_config() -> SuiteCloudConfig | None:
    url = os.environ.get("SUITE_SUPABASE_URL", "").strip()
    key = os.environ.get("SUITE_SUPABASE_KEY", "").strip()
    if not url or not key:
        sec_url, sec_key, _probe = _from_streamlit_secrets()
        url = url or sec_url
        key = key or sec_key
    if not url or not key:
        return None
    return SuiteCloudConfig(url=url.rstrip("/"), key=key)


def cloud_storage_enabled() -> bool:
    return get_cloud_config() is not None


def reset_cloud_config_cache() -> None:
    get_cloud_config.cache_clear()
