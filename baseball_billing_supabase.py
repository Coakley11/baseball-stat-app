"""Supabase adapters: server-only billing writes and user-JWT RLS reads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import requests

from baseball_billing import (
    BillingError,
    CustomerRecord,
    EventClaim,
    EventLease,
    SubscriptionRecord,
)
from baseball_monetization import EntitlementSnapshot, Plan, SubscriptionStatus


class Rest:
    def __init__(self, url: str, key: str, bearer: str | None = None):
        self.url = url.rstrip("/")
        self.key = key
        self.bearer = bearer or key

    def request(self, method, path, *, params=None, body=None, prefer="return=representation"):
        response = requests.request(
            method,
            f"{self.url}/rest/v1/{path}",
            params=params,
            json=body,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.bearer}",
                "Prefer": prefer,
            },
            timeout=12,
        )
        if not response.ok:
            raise BillingError(f"Billing database request failed ({response.status_code})")
        return response.json() if response.content else None


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value if isinstance(value, Mapping) else None


def _scalar(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def _period_end(value: int) -> str | None:
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


class SupabaseBillingStore:
    def __init__(self, config):
        if not config.supabase_url or not config.supabase_service_role_key:
            raise BillingError("Server billing storage is not configured")
        self.db = Rest(config.supabase_url, config.supabase_service_role_key)

    def _subscription_row(self, *, user_id="", customer_id=""):
        params = {
            "select": "user_id,stripe_customer_id",
            "limit": "1",
        }
        if user_id:
            params["user_id"] = f"eq.{user_id}"
        if customer_id:
            params["stripe_customer_id"] = f"eq.{customer_id}"
        return _first(self.db.request("GET", "subscriptions", params=params))

    @staticmethod
    def _customer(row) -> CustomerRecord | None:
        if not row or not row.get("stripe_customer_id"):
            return None
        return CustomerRecord(str(row["user_id"]), str(row["stripe_customer_id"]))

    def customer_for_user(self, user_id):
        return self._customer(self._subscription_row(user_id=user_id))

    def customer_by_stripe_id(self, customer_id):
        return self._customer(self._subscription_row(customer_id=customer_id))

    def _rpc(self, name, body):
        return _scalar(self.db.request("POST", f"rpc/{name}", body=body))

    def attach_customer(self, row):
        attached = self._rpc(
            "baseball_attach_stripe_customer",
            {
                "p_user_id": row.app_user_id,
                "p_customer_id": row.stripe_customer_id,
            },
        )
        if not attached:
            raise BillingError("Customer ownership conflict")

    def claim_event(self, event_id, event_type, created, fingerprint, livemode):
        value = self._rpc(
            "baseball_claim_webhook_event",
            {
                "p_event_id": event_id,
                "p_event_type": event_type,
                "p_event_created": created,
                "p_fingerprint": fingerprint,
                "p_livemode": livemode,
            },
        )
        if not isinstance(value, Mapping):
            raise BillingError("Webhook claim failed")
        return EventLease(
            EventClaim(str(value.get("claim") or "")),
            str(value.get("lease_token") or ""),
        )

    def apply_subscription_if_newer(self, row, snapshot, lease_token):
        return bool(
            self._rpc(
                "baseball_apply_subscription_event",
                {
                    "p_user_id": row.app_user_id,
                    "p_customer_id": row.customer_id,
                    "p_subscription_id": row.subscription_id,
                    "p_plan": snapshot.plan.value,
                    "p_status": snapshot.status.value,
                    "p_period_end": _period_end(row.period_end),
                    "p_event_id": row.event_id,
                    "p_event_created": row.event_created,
                    "p_lease_token": lease_token,
                },
            )
        )

    def mark_event_processed(self, event_id, token):
        if not self._rpc(
            "baseball_finish_webhook_event",
            {
                "p_event_id": event_id,
                "p_lease_token": token,
                "p_state": "processed",
                "p_error": None,
            },
        ):
            raise BillingError("Webhook lease ownership lost")

    def mark_event_failed(self, event_id, token, error):
        if not self._rpc(
            "baseball_finish_webhook_event",
            {
                "p_event_id": event_id,
                "p_lease_token": token,
                "p_state": "failed",
                "p_error": str(error)[:1000],
            },
        ):
            raise BillingError("Webhook lease ownership lost")


class SupabaseEntitlementProvider:
    def __init__(self, config, token):
        if not config.supabase_url or not config.supabase_anon_key or not token:
            raise BillingError("Entitlement read is not configured")
        self.db = Rest(config.supabase_url, config.supabase_anon_key, token)

    def entitlement_for_user(self, user_id):
        row = _first(
            self.db.request(
                "GET",
                "subscriptions",
                params={
                    "user_id": f"eq.{user_id}",
                    "select": (
                        "user_id,plan,status,stripe_customer_id,"
                        "stripe_subscription_id,current_period_end"
                    ),
                    "limit": "1",
                },
            )
        )
        if not row:
            return None
        if str(row.get("user_id") or "") != user_id:
            raise BillingError("Subscription ownership mismatch")
        try:
            plan = Plan(str(row.get("plan") or "free"))
        except ValueError:
            return EntitlementSnapshot(
                ready=False,
                source="subscriptions",
                status=SubscriptionStatus.UNKNOWN,
                user_id=user_id,
            )
        status_value = str(row.get("status") or "inactive")
        status_map = {
            "inactive": SubscriptionStatus.INACTIVE,
            "active": SubscriptionStatus.ACTIVE,
            "trialing": SubscriptionStatus.TRIALING,
            "past_due": SubscriptionStatus.PAST_DUE,
            "canceled": SubscriptionStatus.CANCELED,
        }
        status = status_map.get(status_value, SubscriptionStatus.UNKNOWN)
        if status is SubscriptionStatus.UNKNOWN:
            return EntitlementSnapshot(
                plan=plan,
                ready=False,
                source="subscriptions",
                status=status,
                user_id=user_id,
            )
        return EntitlementSnapshot(
            plan=plan,
            ready=True,
            source="subscriptions",
            status=status,
            user_id=user_id,
            current_period_end=str(row.get("current_period_end") or ""),
            has_stripe_customer=bool(row.get("stripe_customer_id")),
        )
