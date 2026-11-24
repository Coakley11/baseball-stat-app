-- READ-ONLY (2026-11-24): profile of the most recently created Auth account (account #4). Categories, times and
-- counts only: no email address, id or IP is printed.
with au as (select u.*, row_number() over (order by u.created_at, u.id) as acct_no from auth.users u),
n as (select * from au order by created_at desc, id desc limit 1),
owners as (select * from au where split_part(lower(email), '@', 1) in ('daniel.cohen11') or split_part(lower(email), '@', 1) like 'coakley11%'),
prof as (select s.user_id as profile_id from public.suite_user_settings s, n
         where s.app = '_auth_binding' and s.settings ->> 'auth_user_id' = n.id::text),
sess as (select to_jsonb(s) as j from auth.sessions s, n where s.user_id = n.id)
select * from (
  select '1 account' as section, 'account number' as "check", (select acct_no::text from n) as value
  union all select '1 account', 'created (UTC)', (select to_char(created_at at time zone 'utc', 'YYYY-MM-DD HH24:MI') from n)
  union all select '1 account', 'email confirmed', (select case when email_confirmed_at is null then 'no' else 'yes, ' || to_char(email_confirmed_at at time zone 'utc', 'YYYY-MM-DD HH24:MI') end from n)
  union all select '1 account', 'last sign-in (UTC)', (select coalesce(to_char(last_sign_in_at at time zone 'utc', 'YYYY-MM-DD HH24:MI'), 'never') from n)
  union all select '1 account', 'sign-in providers', (select coalesce(string_agg(distinct i.provider, ', '), 'none') from auth.identities i, n where i.user_id = n.id)
  union all select '1 account', 'anonymous user', (select coalesce(to_jsonb(n) ->> 'is_anonymous', 'unknown') from n)
  union all select '1 account', 'banned', (select case when to_jsonb(n) ->> 'banned_until' is null then 'no' else 'yes' end from n)
  union all select '2 email (no address shown)', 'same domain as one of your accounts',
                   (select (split_part(lower(n.email), '@', 2) in (select split_part(lower(email), '@', 2) from owners))::text from n)
  union all select '2 email (no address shown)', 'local part looks like a protected name (daniel / coakley / ariel / guest / test)',
                   (select (split_part(lower(n.email), '@', 1) ~ '(daniel|coakley|ariel|guest|test)')::text from n)
  union all select '3 sessions', 'sessions', (select count(*)::text from sess)
  union all select '3 sessions', 'client types', (select coalesce(string_agg(distinct coalesce(nullif(split_part(j ->> 'user_agent', '/', 1), ''), 'unknown'), ', '), '-') from sess)
  union all select '3 sessions', 'distinct IP addresses', (select count(distinct j ->> 'ip')::text from sess)
  union all select '4 workspace', 'profiles bound to this account', (select count(*)::text from prof)
  union all select '4 workspace', 'bound profile is a protected one (daniel / coakley11 / ariel / guest / test_user)',
                   (select coalesce(bool_or(u.external_id in ('daniel', 'coakley11', 'ariel', 'guest', 'test_user'))::text, 'no profile') from prof join public.suite_users u on u.id = prof.profile_id)
  union all select '4 workspace', 'saved items in its profile', (select count(*)::text from public.suite_saved_items i where i.user_id in (select profile_id from prof))
  union all select '4 workspace', 'browser-session (link) records in its profile', (select count(*)::text from public.suite_saved_items i where i.user_id in (select profile_id from prof) and i.app = '_auth_browser')
  union all select '4 workspace', 'settings rows in its profile', (select count(*)::text from public.suite_user_settings s where s.user_id in (select profile_id from prof))
  union all select '5 activity', 'apps used', (select coalesce(string_agg(distinct e.app, ', '), 'none recorded') from public.suite_activity_events e where e.user_id in (select profile_id from prof))
  union all select '5 activity', 'first / last activity (UTC)', (select coalesce(to_char(min(e.timestamp) at time zone 'utc', 'YYYY-MM-DD HH24:MI') || ' / ' || to_char(max(e.timestamp) at time zone 'utc', 'YYYY-MM-DD HH24:MI'), '-') from public.suite_activity_events e where e.user_id in (select profile_id from prof))
  union all select '6 totals', 'Auth users now', (select count(*)::text from auth.users)
) x
order by 1, 2;
