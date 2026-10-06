"""Dedicated trusted ASGI billing service. Run separately from Streamlit."""
from __future__ import annotations
import hashlib
from typing import Mapping
import requests
from baseball_billing import *
from baseball_billing_config import BillingConfig
from baseball_billing_supabase import SupabaseBillingStore

class StripeHttpGateway:
    def __init__(self,key):
        if not key: raise BillingUnavailable("Stripe server key is not configured")
        self.key=key
    def _request(self,method,path,data=None,idempotency=""):
        r=requests.request(method,"https://api.stripe.com/v1/"+path,auth=(self.key,""),data=data or {},headers={"Idempotency-Key":idempotency} if idempotency else {},timeout=15)
        if not r.ok: raise BillingError(f"Stripe request failed ({r.status_code})")
        return r.json()
    def create_customer(self,*,app_user_id,email): return self._request("POST","customers",{"email":email,"metadata[app_user_id]":app_user_id},"baseball-customer-"+hashlib.sha256(app_user_id.encode()).hexdigest()).get("id")
    def create_checkout(self,**k): return self._request("POST","checkout/sessions",{"mode":"subscription","customer":k["customer_id"],"line_items[0][price]":k["price_id"],"line_items[0][quantity]":"1","success_url":k["success_url"],"cancel_url":k["cancel_url"],"subscription_data[metadata][app_user_id]":k["app_user_id"]},k["idempotency_key"])
    def create_portal(self,**k): return self._request("POST","billing_portal/sessions",{"customer":k["customer_id"],"return_url":k["return_url"]})
    def retrieve_subscription(self,s): return self._request("GET","subscriptions/"+s)

def verify_supabase_user(config,token):
    if not token or not config.supabase_url or not config.supabase_anon_key: raise AuthenticationRequired("Verified sign-in required")
    r=requests.get(config.supabase_url.rstrip("/")+"/auth/v1/user",headers={"apikey":config.supabase_anon_key,"Authorization":"Bearer "+token},timeout=10)
    if not r.ok: raise AuthenticationRequired("Supabase session verification failed")
    v=r.json(); user=VerifiedUser(str(v.get("id") or ""),str(v.get("email") or ""))
    if not user.user_id: raise AuthenticationRequired("Verified user id missing")
    return user

try:
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    def deps():
        c=BillingConfig.from_environ(); return c,SupabaseBillingStore(c),StripeHttpGateway(c.stripe_secret_key)
    def bearer(r):
        scheme,_,token=r.headers.get("authorization","").partition(" "); return token if scheme.lower()=="bearer" else ""
    async def limited_raw_body(request,limit=1_000_000):
        try: declared=int(request.headers.get("content-length","0") or 0)
        except ValueError: raise BillingError("Invalid content length")
        if declared<0: raise BillingError("Invalid content length")
        if declared>limit: raise OverflowError("Webhook body too large")
        if hasattr(request,"stream"):
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>limit: raise OverflowError("Webhook body too large")
            return bytes(body)
        raw=await request.body()
        if len(raw)>limit: raise OverflowError("Webhook body too large")
        return raw
    async def health(_): return JSONResponse(BillingConfig.from_environ().public_status())
    async def checkout(r):
        try:
            c,s,g=deps(); u=verify_supabase_user(c,bearer(r)); v=CheckoutService(c,s,g).create(u,intent="pro"); return JSONResponse({"url":v.get("url")},status_code=201)
        except AuthenticationRequired as e: return JSONResponse({"error":str(e)},status_code=401)
        except BillingError as e: return JSONResponse({"error":str(e)},status_code=503)
    async def portal(r):
        try:
            c,s,g=deps(); u=verify_supabase_user(c,bearer(r)); v=CheckoutService(c,s,g).portal(u); return JSONResponse({"url":v.get("url")},status_code=201)
        except AuthenticationRequired as e: return JSONResponse({"error":str(e)},status_code=401)
        except BillingError as e: return JSONResponse({"error":str(e)},status_code=503)
    async def webhook(r):
        try: raw=await limited_raw_body(r)
        except OverflowError: return JSONResponse({"error":"Webhook body too large"},status_code=413)
        except BillingError as exc: return JSONResponse({"error":str(exc)},status_code=400)
        try:
            c,s,g=deps()
            if not c.webhook_enabled: raise BillingUnavailable("Webhook disabled")
            event=parse_verified_event(raw,r.headers.get("stripe-signature",""),c.stripe_webhook_secret)
            return JSONResponse({"received":True,"result":WebhookProcessor(c,s,g).process(event)})
        except InvalidWebhookSignature as e: return JSONResponse({"error":str(e)},status_code=400)
        except BillingError as e: return JSONResponse({"error":str(e)},status_code=400)
        except Exception: return JSONResponse({"error":"Webhook processing failed"},status_code=500)
    app=Starlette(routes=[Route("/billing/health",health),Route("/billing/checkout",checkout,methods=["POST"]),Route("/billing/portal",portal,methods=["POST"]),Route("/billing/webhooks/stripe",webhook,methods=["POST"])])
except ImportError:
    app=None
