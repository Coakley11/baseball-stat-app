"""
Supabase credentials for shared suite activity (all deployments).

Set in Streamlit Cloud secrets.toml under [suite_activity] or via environment:

  SUITE_SUPABASE_URL=https://xxxx.supabase.co
  SUITE_SUPABASE_KEY=<service_role or anon key>
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class SuiteCloudConfig:
    url: str
    key: str


def _from_streamlit_secrets() -> tuple[str, str]:
    try:
        import streamlit as st  # noqa: WPS433

        block = st.secrets.get("suite_activity")
        if isinstance(block, dict):
            url = str(block.get("supabase_url") or block.get("url") or "").strip()
            key = str(
                block.get("supabase_key")
                or block.get("service_role_key")
                or block.get("key")
                or ""
            ).strip()
            return url, key
    except Exception:
        pass
    return "", ""


@lru_cache(maxsize=1)
def get_cloud_config() -> SuiteCloudConfig | None:
    url = os.environ.get("SUITE_SUPABASE_URL", "").strip()
    key = os.environ.get("SUITE_SUPABASE_KEY", "").strip()
    if not url or not key:
        sec_url, sec_key = _from_streamlit_secrets()
        url = url or sec_url
        key = key or sec_key
    if not url or not key:
        return None
    return SuiteCloudConfig(url=url.rstrip("/"), key=key)


def cloud_storage_enabled() -> bool:
    return get_cloud_config() is not None


def reset_cloud_config_cache() -> None:
    get_cloud_config.cache_clear()
