"""Server-owned Baseball billing configuration and rollout policy."""
from __future__ import annotations
import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping
from urllib.parse import urlsplit

class RolloutMode(str, Enum):
    OFF="off"; PREVIEW="preview"; TEST="test"; LIVE="live"

def _v(env, key): return str(env.get(key) or "").strip()

def trusted_url(value: str, *, allow_loopback: bool=False) -> bool:
    try: parsed=urlsplit(str(value or "").strip()); port=parsed.port
    except ValueError: return False
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment: return False
    if parsed.scheme=="https": return True
    return bool(allow_loopback and parsed.scheme=="http" and parsed.hostname.lower() in {"localhost","127.0.0.1","::1"})

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
    def from_environ(cls, environ: Mapping[str,str]|None=None):
        env=os.environ if environ is None else environ
        try: rollout=RolloutMode(_v(env,"BASEBALL_BILLING_ROLLOUT").lower() or "off")
        except ValueError: rollout=RolloutMode.OFF
        return cls(rollout,_v(env,"BASEBALL_STRIPE_MODE").lower() or "test",
            _v(env,"STRIPE_SECRET_KEY"),_v(env,"STRIPE_WEBHOOK_SECRET"),
            _v(env,"STRIPE_BASEBALL_PRO_PRICE_ID"),_v(env,"BASEBALL_PUBLIC_BASE_URL").rstrip("/"),
            _v(env,"BASEBALL_BILLING_SERVICE_URL").rstrip("/"),
            _v(env,"BASEBALL_BILLING_SUPABASE_URL") or _v(env,"SUITE_SUPABASE_URL"),
            _v(env,"BASEBALL_BILLING_SUPABASE_SERVICE_ROLE_KEY"),
            _v(env,"BASEBALL_BILLING_SUPABASE_ANON_KEY") or _v(env,"SUITE_SUPABASE_ANON_KEY"))

    @property
    def test_mode(self): return self.rollout is RolloutMode.TEST and self.stripe_mode=="test"
    @property
    def live_mode(self): return self.rollout is RolloutMode.LIVE and self.stripe_mode=="live"
    @property
    def checkout_enabled(self):
        if not (self.test_mode or self.live_mode): return False
        prefix="sk_live_" if self.live_mode else "sk_test_"
        urls=trusted_url(self.public_base_url,allow_loopback=self.test_mode) and trusted_url(self.supabase_url,allow_loopback=self.test_mode)
        roles_safe=bool(self.supabase_service_role_key and self.supabase_anon_key and self.supabase_service_role_key!=self.supabase_anon_key)
        return self.stripe_secret_key.startswith(prefix) and bool(self.pro_price_id) and urls and roles_safe
    @property
    def webhook_enabled(self):
        return self.checkout_enabled and self.stripe_webhook_secret.startswith("whsec_")
    @property
    def enforcement_enabled(self):
        return self.rollout in {RolloutMode.TEST,RolloutMode.LIVE} and self.webhook_enabled
    @property
    def client_checkout_enabled(self):
        public=trusted_url(self.billing_service_url,allow_loopback=self.test_mode) and trusted_url(self.supabase_url,allow_loopback=self.test_mode) and bool(self.supabase_anon_key)
        return public and (self.test_mode or (self.live_mode and self.webhook_enabled))
    def public_status(self):
        return {"rollout":self.rollout.value,"stripe_mode":self.stripe_mode,"checkout_enabled":self.checkout_enabled,
            "webhook_enabled":self.webhook_enabled,"enforcement_enabled":self.enforcement_enabled,"client_checkout_enabled":self.client_checkout_enabled,
            "configuration_healthy":self.checkout_enabled and self.webhook_enabled,
            "price_configured":bool(self.pro_price_id),"billing_service_configured":bool(self.billing_service_url),
            "supabase_configured":bool(self.supabase_url and self.supabase_service_role_key and self.supabase_anon_key)}
