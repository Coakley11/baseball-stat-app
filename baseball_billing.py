"""Trusted Stripe subscription domain; contains no Streamlit state."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol

from baseball_billing_config import BillingConfig
from baseball_monetization import EntitlementSnapshot, Plan, SubscriptionStatus


class BillingError(RuntimeError):
    pass


class AuthenticationRequired(BillingError):
    pass


class BillingUnavailable(BillingError):
    pass


class InvalidWebhookSignature(BillingError):
    pass


class EventClaim(str, Enum):
    NEW = "new"
    RETRY = "retry"
    IN_PROGRESS = "in_progress"
    DUPLICATE = "duplicate"
    COLLISION = "collision"


LEASE_SECONDS = 300
SUPPORTED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
    }
)


@dataclass(frozen=True)
class VerifiedUser:
    user_id: str
    email: str = ""


@dataclass(frozen=True)
class CustomerRecord:
    app_user_id: str
    stripe_customer_id: str


@dataclass(frozen=True)
class SubscriptionRecord:
    app_user_id: str
    customer_id: str
    subscription_id: str
    price_id: str
    provider_status: str
    period_end: int
    event_id: str
    event_created: int


@dataclass(frozen=True)
class EventLease:
    claim: EventClaim
    token: str = ""


class Store(Protocol):
    def customer_for_user(self, user_id: str) -> CustomerRecord | None: ...

    def customer_by_stripe_id(self, customer_id: str) -> CustomerRecord | None: ...

    def attach_customer(self, row: CustomerRecord) -> None: ...

    def claim_event(
        self, event_id: str, event_type: str, created: int, fingerprint: str, livemode: bool
    ) -> EventLease: ...

    def apply_subscription_if_newer(
        self,
        row: SubscriptionRecord,
        snapshot: EntitlementSnapshot,
        lease_token: str,
    ) -> bool: ...

    def mark_event_processed(self, event_id: str, lease_token: str) -> None: ...

    def mark_event_failed(self, event_id: str, lease_token: str, error: object) -> None: ...


class StripeGateway(Protocol):
    def create_customer(self, *, app_user_id: str, email: str) -> str: ...

    def create_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        app_user_id: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]: ...

    def create_portal(self, *, customer_id: str, return_url: str) -> Mapping[str, Any]: ...

    def retrieve_subscription(self, subscription_id: str) -> Mapping[str, Any]: ...


class InMemoryStore:
    """Deterministic store used by trust-boundary tests."""

    def __init__(self) -> None:
        self.customers: dict[str, CustomerRecord] = {}
        self.by_stripe: dict[str, CustomerRecord] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self.subscriptions: dict[str, SubscriptionRecord] = {}
        self.entitlements: dict[str, tuple[EntitlementSnapshot, int, str, str]] = {}

    def customer_for_user(self, user_id: str) -> CustomerRecord | None:
        return self.customers.get(user_id)

    def customer_by_stripe_id(self, customer_id: str) -> CustomerRecord | None:
        return self.by_stripe.get(customer_id)

    def attach_customer(self, row: CustomerRecord) -> None:
        current_user = self.customers.get(row.app_user_id)
        current_customer = self.by_stripe.get(row.stripe_customer_id)
        if (current_user and current_user != row) or (
            current_customer and current_customer.app_user_id != row.app_user_id
        ):
            raise BillingError("Customer ownership conflict")
        self.customers[row.app_user_id] = row
        self.by_stripe[row.stripe_customer_id] = row

    # Backward-compatible test helper name.
    upsert_customer = attach_customer

    def claim_event(self, event_id, event_type, created, fingerprint, livemode):
        old = self.events.get(event_id)
        now = time.time()
        identity = (event_type, created, fingerprint, livemode)
        if old:
            if (old["type"], old["created"], old["fingerprint"], old["livemode"]) != identity:
                old["collision_count"] = old.get("collision_count", 0) + 1
                return EventLease(EventClaim.COLLISION)
            if old["state"] == "processed":
                return EventLease(EventClaim.DUPLICATE)
            if old["state"] == "processing" and now - old["updated"] < LEASE_SECONDS:
                return EventLease(EventClaim.IN_PROGRESS)
            token = secrets.token_urlsafe(24)
            old.update(
                state="processing",
                updated=now,
                attempts=min(100, old["attempts"] + 1),
                lease_token=token,
            )
            return EventLease(EventClaim.RETRY, token)
        token = secrets.token_urlsafe(24)
        self.events[event_id] = {
            "type": event_type,
            "created": created,
            "fingerprint": fingerprint,
            "livemode": livemode,
            "state": "processing",
            "updated": now,
            "attempts": 1,
            "collision_count": 0,
            "lease_token": token,
        }
        return EventLease(EventClaim.NEW, token)

    def apply_subscription_if_newer(self, row, snapshot, lease_token):
        self._owned(row.event_id, lease_token)
        old = self.subscriptions.get(row.subscription_id)
        if old and (old.event_created, old.event_id) >= (row.event_created, row.event_id):
            return False
        self.subscriptions[row.subscription_id] = row
        self.entitlements[row.app_user_id] = (
            snapshot,
            row.event_created,
            row.event_id,
            row.subscription_id,
        )
        return True

    def _owned(self, event_id, token):
        row = self.events[event_id]
        if (
            row["state"] != "processing"
            or not token
            or not secrets.compare_digest(str(row.get("lease_token") or ""), str(token))
        ):
            raise BillingError("Webhook lease ownership lost")
        return row

    def mark_event_processed(self, event_id, token):
        self._owned(event_id, token).update(
            state="processed", lease_token="", updated=time.time()
        )

    def mark_event_failed(self, event_id, token, error):
        self._owned(event_id, token).update(
            state="failed",
            lease_token="",
            error=str(error)[:1000],
            updated=time.time(),
        )


class CheckoutService:
    def __init__(self, config: BillingConfig, store: Store, stripe: StripeGateway):
        self.config = config
        self.store = store
        self.stripe = stripe

    def create(self, user: VerifiedUser, *, intent: str = "pro") -> Mapping[str, Any]:
        if not user.user_id:
            raise AuthenticationRequired("Sign in with a verified Baseball account to upgrade")
        if not self.config.checkout_enabled:
            raise BillingUnavailable("Checkout is disabled")
        if intent != "pro":
            raise BillingError("Unknown product intent")
        customer = self.store.customer_for_user(user.user_id)
        if not customer:
            customer_id = str(
                self.stripe.create_customer(app_user_id=user.user_id, email=user.email) or ""
            )
            if not customer_id:
                raise BillingError("Stripe customer creation failed")
            customer = CustomerRecord(user.user_id, customer_id)
            self.store.attach_customer(customer)
        day = int(time.time() // 86400)
        idempotency_key = "baseball-checkout-" + hashlib.sha256(
            f"{user.user_id}:pro:{day}".encode()
        ).hexdigest()
        return self.stripe.create_checkout(
            customer_id=customer.stripe_customer_id,
            price_id=self.config.pro_price_id,
            app_user_id=user.user_id,
            success_url=self.config.public_base_url + "?billing=success",
            cancel_url=self.config.public_base_url + "?billing=cancelled",
            idempotency_key=idempotency_key,
        )

    def portal(self, user: VerifiedUser) -> Mapping[str, Any]:
        if not user.user_id:
            raise AuthenticationRequired("Sign in is required")
        customer = self.store.customer_for_user(user.user_id)
        if not customer:
            raise BillingError("No billing customer exists")
        return self.stripe.create_portal(
            customer_id=customer.stripe_customer_id,
            return_url=self.config.public_base_url,
        )


def verify_signature(raw: bytes, header: str, secret: str, *, now=None, tolerance=300) -> None:
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        key, separator, value = item.partition("=")
        if separator:
            parts.setdefault(key, []).append(value)
    try:
        stamp = int(parts.get("t", [""])[0])
    except ValueError as exc:
        raise InvalidWebhookSignature("Invalid webhook signature") from exc
    current = int(time.time()) if now is None else int(now)
    if not secret or abs(current - stamp) > tolerance:
        raise InvalidWebhookSignature("Invalid webhook signature")
    expected = hmac.new(
        secret.encode(), str(stamp).encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, value) for value in parts.get("v1", [])):
        raise InvalidWebhookSignature("Invalid webhook signature")


def parse_verified_event(raw, header, secret, **kwargs):
    verify_signature(raw, header, secret, **kwargs)
    try:
        event = json.loads(raw)
    except Exception as exc:
        raise BillingError("Malformed webhook JSON") from exc
    if not isinstance(event, dict):
        raise BillingError("Malformed webhook envelope")
    return event


def _subscription_terms(
    subscription: Mapping[str, Any], known_price: str
) -> tuple[str, int]:
    items = (subscription.get("items") or {}).get("data") or []
    fallback: tuple[str, int] = ("", 0)
    for item in items:
        price_id = str(((item or {}).get("price") or {}).get("id") or "")
        period_end = int(
            (item or {}).get("current_period_end")
            or subscription.get("current_period_end")
            or 0
        )
        if price_id and not fallback[0]:
            fallback = (price_id, period_end)
        if price_id == known_price:
            return price_id, period_end
    return fallback


def project(row: SubscriptionRecord, known_price: str) -> EntitlementSnapshot:
    status = row.provider_status.lower()
    known_subscription = row.price_id == known_price
    plan = Plan.PRO if known_subscription else Plan.FREE
    if known_subscription and status == "trialing":
        mapped = SubscriptionStatus.TRIALING
    elif known_subscription and status == "active":
        mapped = SubscriptionStatus.ACTIVE
    elif known_subscription and status == "past_due":
        mapped = SubscriptionStatus.PAST_DUE
    elif known_subscription and status in {"canceled", "unpaid", "incomplete_expired"}:
        mapped = SubscriptionStatus.CANCELED
    elif known_subscription:
        mapped = SubscriptionStatus.INACTIVE
    else:
        mapped = SubscriptionStatus.AUTHENTICATED_FREE
    return EntitlementSnapshot(
        plan=plan,
        ready=True,
        source="subscriptions",
        status=mapped,
        user_id=row.app_user_id,
        current_period_end=str(row.period_end or ""),
        has_stripe_customer=True,
    )


class WebhookProcessor:
    def __init__(self, config: BillingConfig, store: Store, stripe: StripeGateway):
        self.config = config
        self.store = store
        self.stripe = stripe

    def _subscription_object(self, event_type: str, obj: Mapping[str, Any]):
        if event_type == "customer.subscription.deleted":
            return obj
        if event_type.startswith("customer.subscription."):
            subscription_id = str(obj.get("id") or "")
        else:
            value = obj.get("subscription")
            if not value:
                value = (
                    ((obj.get("parent") or {}).get("subscription_details") or {}).get(
                        "subscription"
                    )
                )
            subscription_id = str(value.get("id") if isinstance(value, Mapping) else value or "")
        if not subscription_id:
            return None
        return self.stripe.retrieve_subscription(subscription_id)

    def process(self, event: Mapping[str, Any]) -> str:
        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        try:
            created = int(event.get("created") or 0)
        except (TypeError, ValueError) as exc:
            raise BillingError("Malformed webhook envelope") from exc
        livemode = event.get("livemode")
        if not event_id or not event_type or created <= 0 or not isinstance(livemode, bool):
            raise BillingError("Malformed webhook envelope")
        if livemode is not self.config.live_mode:
            raise BillingError("Webhook mode mismatch")
        fingerprint = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        lease = self.store.claim_event(
            event_id, event_type, created, fingerprint, livemode
        )
        if lease.claim is EventClaim.COLLISION:
            raise BillingError("Webhook event id collision")
        if lease.claim in {EventClaim.DUPLICATE, EventClaim.IN_PROGRESS}:
            return lease.claim.value
        try:
            if event_type not in SUPPORTED_EVENTS:
                self.store.mark_event_processed(event_id, lease.token)
                return "ignored"
            obj = ((event.get("data") or {}).get("object") or {})
            if not isinstance(obj, Mapping):
                raise BillingError("Malformed webhook object")
            subscription = self._subscription_object(event_type, obj)
            if not subscription:
                self.store.mark_event_processed(event_id, lease.token)
                return "ignored"
            customer_id = str(subscription.get("customer") or obj.get("customer") or "")
            owner = self.store.customer_by_stripe_id(customer_id)
            if not owner:
                raise BillingError("Stripe customer has no trusted owner")
            metadata = subscription.get("metadata") or {}
            metadata_user = str(metadata.get("app_user_id") or "")
            session_user = (
                str(obj.get("client_reference_id") or (obj.get("metadata") or {}).get("app_user_id") or "")
                if event_type == "checkout.session.completed"
                else ""
            )
            if (metadata_user and metadata_user != owner.app_user_id) or (
                session_user and session_user != owner.app_user_id
            ):
                raise BillingError("Ownership metadata conflict")
            price_id, period_end = _subscription_terms(
                subscription, self.config.pro_price_id
            )
            row = SubscriptionRecord(
                app_user_id=owner.app_user_id,
                customer_id=customer_id,
                subscription_id=str(subscription.get("id") or ""),
                price_id=price_id,
                provider_status=str(subscription.get("status") or ""),
                period_end=period_end,
                event_id=event_id,
                event_created=created,
            )
            if not row.subscription_id:
                raise BillingError("Stripe subscription id missing")
            snapshot = project(row, self.config.pro_price_id)
            self.store.apply_subscription_if_newer(row, snapshot, lease.token)
            self.store.mark_event_processed(event_id, lease.token)
            return "processed"
        except Exception as exc:
            try:
                self.store.mark_event_failed(event_id, lease.token, exc)
            except BillingError:
                pass
            raise
