"""Trusted Stripe subscription domain; contains no Streamlit state."""
from __future__ import annotations
import hashlib,hmac,json,time
from dataclasses import dataclass
from enum import Enum
from typing import Any,Mapping,Protocol
from baseball_billing_config import BillingConfig
from baseball_monetization import EntitlementSnapshot,Plan,SubscriptionStatus

class BillingError(RuntimeError): pass
class AuthenticationRequired(BillingError): pass
class BillingUnavailable(BillingError): pass
class InvalidWebhookSignature(BillingError): pass
class EventClaim(str,Enum): NEW="new"; RETRY="retry"; IN_PROGRESS="in_progress"; DUPLICATE="duplicate"
LEASE_SECONDS=300
SUPPORTED_EVENTS=frozenset({"checkout.session.completed","customer.subscription.created","customer.subscription.updated","customer.subscription.deleted","invoice.paid","invoice.payment_failed"})

@dataclass(frozen=True)
class VerifiedUser: user_id:str; email:str=""
@dataclass(frozen=True)
class CustomerRecord: app_user_id:str; stripe_customer_id:str
@dataclass(frozen=True)
class SubscriptionRecord:
    app_user_id:str; customer_id:str; subscription_id:str; price_id:str; provider_status:str
    period_end:int; cancel_at_period_end:bool; event_id:str; event_created:int

class Store(Protocol):
    def customer_for_user(self,user_id:str): ...
    def customer_by_stripe_id(self,customer_id:str): ...
    def upsert_customer(self,row): ...
    def claim_event(self,event_id,event_type,created,fingerprint,livemode): ...
    def apply_subscription_if_newer(self,row): ...
    def save_entitlement(self,user_id,snapshot,event_id,event_created,subscription_id): ...
    def mark_event_processed(self,event_id): ...
    def mark_event_failed(self,event_id,error): ...

class StripeGateway(Protocol):
    def create_customer(self,*,app_user_id,email): ...
    def create_checkout(self,*,customer_id,price_id,app_user_id,success_url,cancel_url): ...
    def create_portal(self,*,customer_id,return_url): ...
    def retrieve_subscription(self,subscription_id): ...

class InMemoryStore:
    def __init__(self): self.customers={}; self.by_stripe={}; self.events={}; self.subscriptions={}; self.entitlements={}
    def customer_for_user(self,u): return self.customers.get(u)
    def customer_by_stripe_id(self,c): return self.by_stripe.get(c)
    def upsert_customer(self,row):
        a=self.customers.get(row.app_user_id); b=self.by_stripe.get(row.stripe_customer_id)
        if (a and a!=row) or (b and b.app_user_id!=row.app_user_id): raise BillingError("Customer ownership conflict")
        self.customers[row.app_user_id]=row; self.by_stripe[row.stripe_customer_id]=row
    def claim_event(self,e,t,c,f,l):
        old=self.events.get(e); now=time.time()
        if old:
            if (old["type"],old["created"],old["fingerprint"],old["livemode"])!=(t,c,f,l): raise BillingError("Webhook event id collision")
            if old["state"]=="processed": return EventClaim.DUPLICATE
            if old["state"]=="processing" and now-old["updated"]<LEASE_SECONDS: return EventClaim.IN_PROGRESS
            old.update(state="processing",updated=now,attempts=old["attempts"]+1); return EventClaim.RETRY
        self.events[e]={"type":t,"created":c,"fingerprint":f,"livemode":l,"state":"processing","updated":now,"attempts":1}; return EventClaim.NEW
    def apply_subscription_if_newer(self,row):
        old=self.subscriptions.get(row.subscription_id)
        if old and (old.event_created,old.event_id)>=(row.event_created,row.event_id): return False
        self.subscriptions[row.subscription_id]=row; return True
    def save_entitlement(self,u,s,e,c,sub):
        old=self.entitlements.get(u)
        if old and (old[1],old[2])>(c,e): return
        self.entitlements[u]=(s,c,e,sub)
    def mark_event_processed(self,e): self.events[e].update(state="processed",updated=time.time())
    def mark_event_failed(self,e,error): self.events[e].update(state="failed",error=str(error)[:1000],updated=time.time())

class CheckoutService:
    def __init__(self,config,store,stripe): self.config=config; self.store=store; self.stripe=stripe
    def create(self,user:VerifiedUser,*,intent="pro"):
        if not user.user_id: raise AuthenticationRequired("Sign in with a verified Baseball account to upgrade")
        if not self.config.checkout_enabled: raise BillingUnavailable("Checkout is disabled")
        if intent!="pro": raise BillingError("Unknown product intent")
        customer=self.store.customer_for_user(user.user_id)
        if not customer:
            cid=str(self.stripe.create_customer(app_user_id=user.user_id,email=user.email) or "")
            customer=CustomerRecord(user.user_id,cid); self.store.upsert_customer(customer)
        return self.stripe.create_checkout(customer_id=customer.stripe_customer_id,price_id=self.config.pro_price_id,
            app_user_id=user.user_id,success_url=self.config.public_base_url+"?billing=success",cancel_url=self.config.public_base_url+"?billing=cancelled")
    def portal(self,user:VerifiedUser):
        if not user.user_id: raise AuthenticationRequired("Sign in is required")
        customer=self.store.customer_for_user(user.user_id)
        if not customer: raise BillingError("No billing customer exists")
        return self.stripe.create_portal(customer_id=customer.stripe_customer_id,return_url=self.config.public_base_url)

def verify_signature(raw:bytes,header:str,secret:str,*,now=None,tolerance=300):
    parts={}
    for item in header.split(","):
        k,sep,v=item.partition("=")
        if sep: parts.setdefault(k,[]).append(v)
    try: stamp=int(parts.get("t",[""])[0])
    except ValueError: raise InvalidWebhookSignature("Invalid signature timestamp")
    if not secret or abs((int(time.time()) if now is None else now)-stamp)>tolerance: raise InvalidWebhookSignature("Invalid webhook signature")
    expected=hmac.new(secret.encode(),str(stamp).encode()+b"."+raw,hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected,v) for v in parts.get("v1",[])): raise InvalidWebhookSignature("Invalid webhook signature")

def parse_verified_event(raw,header,secret,**kwargs):
    verify_signature(raw,header,secret,**kwargs)
    try: event=json.loads(raw)
    except Exception as exc: raise BillingError("Malformed webhook JSON") from exc
    if not isinstance(event,dict): raise BillingError("Malformed webhook envelope")
    return event

def project(row:SubscriptionRecord,known_price:str):
    status=row.provider_status.lower(); plan=Plan.FREE; mapped=SubscriptionStatus.AUTHENTICATED_FREE
    if row.price_id==known_price and status=="trialing": plan,mapped=Plan.PRO,SubscriptionStatus.TRIALING
    elif row.price_id==known_price and status=="active": plan,mapped=Plan.PRO,(SubscriptionStatus.CANCELED_PERIOD_END if row.cancel_at_period_end else SubscriptionStatus.ACTIVE)
    elif status=="past_due": mapped=SubscriptionStatus.PAST_DUE
    elif status in {"canceled","unpaid","incomplete_expired","paused"}: mapped=SubscriptionStatus.EXPIRED
    return EntitlementSnapshot(plan,True,"billing_database",mapped,row.app_user_id,str(row.period_end or ""))

class WebhookProcessor:
    def __init__(self,config,store,stripe): self.config=config; self.store=store; self.stripe=stripe
    def process(self,event):
        eid=str(event.get("id") or ""); typ=str(event.get("type") or ""); created=int(event.get("created") or 0); live=event.get("livemode")
        if not eid or not typ or created<=0 or not isinstance(live,bool): raise BillingError("Malformed webhook envelope")
        if live is not self.config.live_mode: raise BillingError("Webhook mode mismatch")
        fingerprint=hashlib.sha256(json.dumps(event,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        claim=self.store.claim_event(eid,typ,created,fingerprint,live)
        if claim in {EventClaim.DUPLICATE,EventClaim.IN_PROGRESS}: return claim.value
        try:
            if typ not in SUPPORTED_EVENTS:
                self.store.mark_event_processed(eid); return "ignored"
            obj=((event.get("data") or {}).get("object") or {})
            if typ.startswith("customer.subscription."): sub=obj
            else:
                sid=str(obj.get("subscription") or "")
                if not sid: self.store.mark_event_processed(eid); return "ignored"
                sub=self.stripe.retrieve_subscription(sid)
            cid=str(sub.get("customer") or ""); owner=self.store.customer_by_stripe_id(cid)
            if not owner: raise BillingError("Stripe customer has no trusted owner")
            meta=sub.get("metadata") or {}
            if meta.get("app_user_id") and meta.get("app_user_id")!=owner.app_user_id: raise BillingError("Ownership metadata conflict")
            items=((sub.get("items") or {}).get("data") or [{}]); price=str(((items[0].get("price") or {}).get("id") or ""))
            row=SubscriptionRecord(owner.app_user_id,cid,str(sub.get("id") or ""),price,str(sub.get("status") or ""),int(sub.get("current_period_end") or 0),bool(sub.get("cancel_at_period_end")),eid,created)
            if self.store.apply_subscription_if_newer(row): self.store.save_entitlement(row.app_user_id,project(row,self.config.pro_price_id),eid,created,row.subscription_id)
            self.store.mark_event_processed(eid); return "processed"
        except Exception as exc: self.store.mark_event_failed(eid,exc); raise
