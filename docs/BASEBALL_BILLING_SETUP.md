# Baseball Explorer authentication and test billing

The app uses the existing Supabase email/password account flow and
`public.subscriptions` as the only entitlement authority. Streamlit reads the
signed-in user's row through their JWT and RLS. A separate trusted ASGI service
creates Stripe sessions and applies signed webhook events with a Supabase
service-role/secret key.

Streamlit Community Cloud hosts the Streamlit process only. Deploy
`baseball_billing_service:app` on a service that can receive HTTPS POST requests;
do not try to run its webhook listener as a second port inside Streamlit Cloud.

## Streamlit configuration (public values only)

Use `.streamlit/secrets.toml` locally or the Streamlit Cloud Secrets editor:

```toml
[suite_activity]
supabase_url = "https://YOUR_PROJECT.supabase.co"
supabase_anon_key = "YOUR_PUBLIC_ANON_OR_PUBLISHABLE_KEY"
suite_auth_enabled = true

[baseball_billing]
rollout = "test"
stripe_mode = "test"
service_url = "https://YOUR_BILLING_SERVICE"
public_base_url = "https://YOUR_STREAMLIT_APP"
```

Equivalent local environment variables are:

- `SUITE_AUTH_ENABLED=1`
- `SUITE_SUPABASE_URL`
- `SUITE_SUPABASE_ANON_KEY`
- `BASEBALL_BILLING_ROLLOUT=test`
- `BASEBALL_STRIPE_MODE=test`
- `BASEBALL_BILLING_SERVICE_URL`
- `BASEBALL_PUBLIC_BASE_URL`

Never put a Stripe secret, webhook secret, or Supabase service-role/secret key in
the browser, session state, query string, or public client configuration.

## Billing-service environment (server only)

Set all of the following on the separately deployed billing service:

- `BASEBALL_BILLING_ROLLOUT=test`
- `BASEBALL_STRIPE_MODE=test`
- `STRIPE_SECRET_KEY` — Stripe test secret key (`sk_test_...`)
- `STRIPE_WEBHOOK_SECRET` — signing secret for this test webhook endpoint
- `STRIPE_BASEBALL_PRO_TEST_PRICE_ID=price_1UO5FtGot4wcmURUVFW5wWiw`
- `BASEBALL_PUBLIC_BASE_URL` — Streamlit app URL used for Checkout/Portal returns
- `BASEBALL_BILLING_SUPABASE_URL`
- `BASEBALL_BILLING_SUPABASE_ANON_KEY` — public key used only to verify user JWTs
- `BASEBALL_BILLING_SUPABASE_SECRET_KEY` — server-only Supabase secret key

`BASEBALL_BILLING_SUPABASE_SERVICE_ROLE_KEY` is accepted as a legacy alternative
to `BASEBALL_BILLING_SUPABASE_SECRET_KEY`. Set one, not both. Do not configure a
live price or live Stripe key during this test phase.

Start locally with:

```powershell
python -m uvicorn baseball_billing_service:app --host 127.0.0.1 --port 8000
python -m streamlit run streamlit_app.py
```

For loopback testing, set both public URLs to `http://localhost`/`127.0.0.1`
addresses. Non-loopback test and all live URLs must use HTTPS.

## Supabase manual setup

1. Run the read-only
   `supabase/preflight/baseball_billing_preflight.sql` and save its results.
   Confirm the documented columns/constraints, RLS ownership policy, absence of
   client write policies, grants, signup trigger definition, and baseline row
   counts. Default write grants can remain only if RLS behavior tests prove that
   user JWT writes are denied.
2. Confirm the signup trigger still inserts one default Free/inactive row into
   `public.subscriptions`.
3. Apply
   `supabase/migrations/20261008_baseball_billing_runtime.sql` in the dedicated
   Baseball project. It fails closed when the existing RLS/grant contract is not
   present and otherwise adds only private bookkeeping tables and service-only
   functions. It does not alter `public.subscriptions` or its existing rows.
4. Re-run the preflight and confirm the three row counts are unchanged and the
   six runtime objects are now present.
5. With two test users, verify each JWT can select only its own row and that both
   users receive permission errors for insert, update, and delete.
6. Confirm anon cannot read the table. The migration also creates private-to-
   clients webhook ledger/version tables and service-role-only RPC functions.

The migration assumes the table and its `free`/`pro` plan plus
`inactive`/`active`/`trialing`/`past_due`/`canceled` status constraints already
exist. It does not recreate the signup trigger.

## Stripe test-mode manual setup

1. Keep Product `prod_VOt1C1y8eR5p6R` and monthly test Price
   `price_1UO5FtGot4wcmURUVFW5wWiw` active.
2. Enable/configure the Stripe test Billing Portal.
3. Add an HTTPS webhook endpoint at
   `https://YOUR_BILLING_SERVICE/billing/webhooks/stripe`.
4. Subscribe it to `checkout.session.completed`,
   `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.paid`, and
   `invoice.payment_failed`.
5. Put that endpoint's test signing secret in `STRIPE_WEBHOOK_SECRET`.

Checkout sends both `client_reference_id` and metadata, but webhook ownership is
accepted only when the Stripe customer matches the server-owned
`stripe_customer_id` on `public.subscriptions`. Browser redirects never grant
access. Active/trialing grants Pro; past-due/canceled states retain subscription
history but do not grant Pro. A scheduled cancellation stays active until Stripe
reports the subscription ended.

## Local review

```powershell
python -m pytest -q -p no:cacheprovider tests/test_baseball_billing_m2.py tests/test_baseball_billing_m3_hardening.py tests/test_baseball_monetization.py tests/test_baseball_monetization_apptest.py tests/test_baseball_account_workspace.py
```

Then sign up, sign out/in, complete test Checkout, refresh, open Manage
Subscription, cancel at period end, and replay a webhook from the Stripe test
dashboard. Current product pages intentionally remain available while the final
Free-vs-Pro feature split is undecided.
