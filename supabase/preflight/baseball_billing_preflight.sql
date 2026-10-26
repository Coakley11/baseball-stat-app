-- Read-only inspection to run in the Baseball Supabase SQL Editor BEFORE the
-- billing runtime migration. This file makes no schema or data changes.

-- 1. The established table columns, types, nullability, and defaults.
select
  column_name,
  data_type,
  is_nullable,
  column_default
from information_schema.columns
where table_schema = 'public'
  and table_name = 'subscriptions'
order by ordinal_position;

-- 2. Primary key, foreign key, unique, and plan/status check constraints.
select
  constraint_record.conname as constraint_name,
  constraint_record.contype as constraint_type,
  pg_get_constraintdef(constraint_record.oid) as definition
from pg_constraint constraint_record
where constraint_record.conrelid = 'public.subscriptions'::regclass
order by constraint_record.contype, constraint_record.conname;

-- 3. RLS enabled/forced state and every existing policy. Confirm the SELECT
-- policy limits rows to auth.uid() = user_id.
select
  relation.relrowsecurity as rls_enabled,
  relation.relforcerowsecurity as rls_forced
from pg_class relation
where relation.oid = 'public.subscriptions'::regclass;

select
  policy.policyname,
  policy.cmd,
  policy.roles,
  policy.qual,
  policy.with_check
from pg_policies policy
where policy.schemaname = 'public'
  and policy.tablename = 'subscriptions'
order by policy.policyname;

-- 4. Effective table grants. authenticated SELECT must be true. Supabase
-- projects can retain write grants while RLS denies the operation, so true
-- write-grant values require the JWT behavior tests below; the migration does
-- not rewrite working live grants.
select
  has_table_privilege('anon', 'public.subscriptions', 'SELECT') as anon_select,
  has_table_privilege('anon', 'public.subscriptions', 'INSERT') as anon_insert,
  has_table_privilege('anon', 'public.subscriptions', 'UPDATE') as anon_update,
  has_table_privilege('anon', 'public.subscriptions', 'DELETE') as anon_delete,
  has_table_privilege('authenticated', 'public.subscriptions', 'SELECT') as authenticated_select,
  has_table_privilege('authenticated', 'public.subscriptions', 'INSERT') as authenticated_insert,
  has_table_privilege('authenticated', 'public.subscriptions', 'UPDATE') as authenticated_update,
  has_table_privilege('authenticated', 'public.subscriptions', 'DELETE') as authenticated_delete;

-- 5. Existing auth.users triggers and their function definitions. Identify the
-- working new-user trigger and confirm its function inserts a Free/inactive row
-- into public.subscriptions. The runtime migration does not modify it.
select
  trigger_record.tgname as trigger_name,
  procedure_record.proname as function_name,
  pg_get_triggerdef(trigger_record.oid) as trigger_definition,
  pg_get_functiondef(procedure_record.oid) as function_definition
from pg_trigger trigger_record
join pg_class relation on relation.oid = trigger_record.tgrelid
join pg_namespace namespace on namespace.oid = relation.relnamespace
join pg_proc procedure_record on procedure_record.oid = trigger_record.tgfoid
where namespace.nspname = 'auth'
  and relation.relname = 'users'
  and not trigger_record.tgisinternal
order by trigger_record.tgname;

-- 6. Data-preservation baseline. Record these counts before and after migration;
-- they must not change.
select
  count(*) as subscription_rows,
  count(stripe_customer_id) as rows_with_stripe_customer,
  count(stripe_subscription_id) as rows_with_stripe_subscription
from public.subscriptions;

-- 7. Idempotency check: these objects may all be absent before the first run and
-- present before a safe re-run.
select
  to_regclass('private.baseball_billing_webhook_events') as webhook_events_table,
  to_regclass('private.baseball_billing_subscription_versions') as subscription_versions_table,
  to_regprocedure('public.baseball_attach_stripe_customer(uuid,text)') as attach_customer_function,
  to_regprocedure('public.baseball_claim_webhook_event(text,text,bigint,text,boolean)') as claim_event_function,
  to_regprocedure('public.baseball_apply_subscription_event(uuid,text,text,text,text,timestamptz,text,bigint,uuid)') as apply_subscription_function,
  to_regprocedure('public.baseball_finish_webhook_event(text,uuid,text,text)') as finish_event_function;
