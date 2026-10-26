"""Configuration boundaries for the Baseball billing client and service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any
from urllib.parse import urlsplit


# This is a public Stripe identifier, not a credential. Keeping the expected test
# value here makes it impossible to accidentally charge against an unreviewed price.
BASEBALL_PRO_TEST_PRICE_ID = "price_1UOJuhKBFPikFnl8SDE6hKwc"


class RolloutMode(str, Enum):
    OFF = "off"
    PREVIEW = "preview"
    TEST = "test"
    LIVE = "live"


def _value(source: Mapping[str, Any], key: str) -> str:
    return str(source.get(key) or "").strip()


def _mapping_value(source: Any, *keys: str) -> str:
    if source is None:
        return ""
    for key in keys:
        try:
            value = source.get(key)
        except Exception:
            value = None
        if value is None:
            try:
                value = source[key]
            except Exception:
                value = None
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""


def trusted_url(value: str, *, allow_loopback: bool = False) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
        parsed.port
    except ValueError:
        return False
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return False
    if parsed.scheme == "https":
        return True
    return bool(
        allow_loopback
        and parsed.scheme == "http"
        and parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    )


@dataclass(frozen=True)
class BillingConfig:
    rollout: RolloutMode
    stripe_mode: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    pro_price_id: str
    public_base_url: str
    billing_service_url: str
    supabase_url: str
    supabase_service_role_key: str
    supabase_anon_key: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "BillingConfig":
        env = os.environ if environ is None else environ
        try:
            rollout = RolloutMode(_value(env, "BASEBALL_BILLING_ROLLOUT").lower() or "off")
        except ValueError:
            rollout = RolloutMode.OFF
        stripe_mode = _value(env, "BASEBALL_STRIPE_MODE").lower() or "test"
        if stripe_mode == "live":
            price_id = _value(env, "STRIPE_BASEBALL_PRO_LIVE_PRICE_ID")
        else:
            price_id = _value(env, "STRIPE_BASEBALL_PRO_TEST_PRICE_ID")
        return cls(
            rollout=rollout,
            stripe_mode=stripe_mode,
            stripe_secret_key=_value(env, "STRIPE_SECRET_KEY"),
            stripe_webhook_secret=_value(env, "STRIPE_WEBHOOK_SECRET"),
            pro_price_id=price_id,
            public_base_url=_value(env, "BASEBALL_PUBLIC_BASE_URL").rstrip("/"),
            billing_service_url=_value(env, "BASEBALL_BILLING_SERVICE_URL").rstrip("/"),
            supabase_url=(
                _value(env, "BASEBALL_BILLING_SUPABASE_URL")
                or _value(env, "SUITE_SUPABASE_URL")
            ).rstrip("/"),
            supabase_service_role_key=(
                _value(env, "BASEBALL_BILLING_SUPABASE_SECRET_KEY")
                or _value(env, "BASEBALL_BILLING_SUPABASE_SERVICE_ROLE_KEY")
            ),
            supabase_anon_key=(
                _value(env, "BASEBALL_BILLING_SUPABASE_ANON_KEY")
                or _value(env, "SUITE_SUPABASE_ANON_KEY")
            ),
        )

    @property
    def test_mode(self) -> bool:
        return self.rollout is RolloutMode.TEST and self.stripe_mode == "test"

    @property
    def live_mode(self) -> bool:
        return self.rollout is RolloutMode.LIVE and self.stripe_mode == "live"

    @property
    def _server_base_ready(self) -> bool:
        mode_ready = self.test_mode or self.live_mode
        prefix = "sk_live_" if self.live_mode else "sk_test_"
        database_ready = (
            trusted_url(self.supabase_url, allow_loopback=self.test_mode)
            and bool(self.supabase_service_role_key and self.supabase_anon_key)
            and self.supabase_service_role_key != self.supabase_anon_key
        )
        return mode_ready and self.stripe_secret_key.startswith(prefix) and database_ready

    @property
    def price_valid(self) -> bool:
        if self.test_mode:
            return self.pro_price_id == BASEBALL_PRO_TEST_PRICE_ID
        if self.live_mode:
            return bool(self.pro_price_id) and self.pro_price_id != BASEBALL_PRO_TEST_PRICE_ID
        return False

    @property
    def webhook_enabled(self) -> bool:
        return self._server_base_ready and self.stripe_webhook_secret.startswith("whsec_")

    @property
    def checkout_enabled(self) -> bool:
        return (
            self.webhook_enabled
            and self.price_valid
            and trusted_url(self.public_base_url, allow_loopback=self.test_mode)
        )

    @property
    def enforcement_enabled(self) -> bool:
        return self.checkout_enabled

    @property
    def client_checkout_enabled(self) -> bool:
        public_ready = (
            trusted_url(self.billing_service_url, allow_loopback=self.test_mode)
            and trusted_url(self.supabase_url, allow_loopback=self.test_mode)
            and bool(self.supabase_anon_key)
        )
        return public_ready and (self.test_mode or self.live_mode)

    def public_status(self) -> dict[str, Any]:
        return {
            "rollout": self.rollout.value,
            "stripe_mode": self.stripe_mode,
            "checkout_enabled": self.checkout_enabled,
            "webhook_enabled": self.webhook_enabled,
            "enforcement_enabled": self.enforcement_enabled,
            "client_checkout_enabled": self.client_checkout_enabled,
            "configuration_healthy": self.checkout_enabled and self.webhook_enabled,
            "price_configured": self.price_valid,
            "billing_service_configured": bool(self.billing_service_url),
            "supabase_configured": bool(
                self.supabase_url
                and self.supabase_service_role_key
                and self.supabase_anon_key
            ),
        }


def load_client_billing_config(
    environ: Mapping[str, str] | None = None,
) -> BillingConfig:
    """Load public-only Streamlit settings without ever reading a service secret."""
    source = os.environ if environ is None else environ
    public_keys = {
        "BASEBALL_BILLING_ROLLOUT",
        "BASEBALL_STRIPE_MODE",
        "BASEBALL_PUBLIC_BASE_URL",
        "BASEBALL_BILLING_SERVICE_URL",
        "BASEBALL_BILLING_SUPABASE_URL",
        "BASEBALL_BILLING_SUPABASE_ANON_KEY",
        "SUITE_SUPABASE_URL",
        "SUITE_SUPABASE_ANON_KEY",
    }
    public_environment = {key: source.get(key, "") for key in public_keys}
    config = BillingConfig.from_environ(public_environment)
    if environ is not None:
        return config
    try:
        import streamlit as st  # noqa: WPS433

        root = st.secrets
        try:
            billing = root.get("baseball_billing")
        except Exception:
            billing = None
        try:
            suite = root.get("suite_activity")
        except Exception:
            suite = None
        rollout_value = _mapping_value(billing, "rollout", "billing_rollout")
        stripe_mode = _mapping_value(billing, "stripe_mode")
        try:
            rollout = RolloutMode(rollout_value.lower()) if rollout_value else config.rollout
        except ValueError:
            rollout = RolloutMode.OFF
        config = replace(
            config,
            rollout=rollout,
            stripe_mode=(stripe_mode.lower() or config.stripe_mode),
            billing_service_url=(
                _mapping_value(billing, "service_url", "billing_service_url")
                or config.billing_service_url
            ).rstrip("/"),
            public_base_url=(
                _mapping_value(billing, "public_base_url") or config.public_base_url
            ).rstrip("/"),
            supabase_url=(
                _mapping_value(suite, "supabase_url", "url") or config.supabase_url
            ).rstrip("/"),
            supabase_anon_key=(
                _mapping_value(
                    suite,
                    "supabase_anon_key",
                    "supabase_public_key",
                    "anon_key",
                )
                or config.supabase_anon_key
            ),
            # Intentionally never populated from st.secrets in the client loader.
            stripe_secret_key="",
            stripe_webhook_secret="",
            supabase_service_role_key="",
        )
    except Exception:
        pass
    return config
