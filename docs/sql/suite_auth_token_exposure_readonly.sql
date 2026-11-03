-- READ-ONLY, aggregate-only checks for the plaintext tokens stored in suite_saved_items.
-- Every statement is a SELECT. Nothing returns a token, an email, a user id or an IP of a
-- single user: only counts, dates and groupings. Column names follow the current Supabase
-- Auth schema; if one statement errors on an older project, skip it and run the rest.

-- T1. How many stored browser sessions hold tokens, how old they are, how many accounts.
select count(*) as browser_session_rows,
       count(distinct user_id) as accounts,
       count(*) filter (where payload ? 'refresh_token') as with_refresh_token,
       count(*) filter (where payload ? 'access_token') as with_access_token,
       count(*) filter (where valid) as still_valid_rows,
       min(updated_at) as oldest,
       max(updated_at) as newest
from public.suite_saved_items
where app = '_auth_browser' and item_type = 'browser_session';

-- T2. Live Auth sessions: how many could be renewed with a stored refresh token.
select count(*) as sessions,
       count(distinct user_id) as accounts,
       count(*) filter (where not_after is null or not_after > now()) as not_expired,
       max(refreshed_at) as last_refresh
from auth.sessions;

select count(*) as unrevoked_refresh_tokens,
       count(distinct session_id) as sessions_with_one
from auth.refresh_tokens
where not revoked;

-- T3. Where sessions are refreshed from. Every suite app refreshes server-side, so normal
-- sessions show the server's client library and cloud addresses. Anything else (a browser
-- user agent, an unexpected network) deserves a closer look by the owner.
select coalesce(user_agent, '(none)') as user_agent, count(*) as sessions,
       min(created_at) as first_seen, max(coalesce(refreshed_at, updated_at)) as last_seen
from auth.sessions
group by 1
order by sessions desc;

select coalesce(set_masklen(ip::cidr, 16)::text, '(none)') as network_16, count(*) as sessions
from auth.sessions
group by 1
order by sessions desc;

-- T4. Auth activity by action over the last 90 days (refresh-token reuse shows up as
-- token_revoked actions; a spike in token_refreshed from new networks is the other signal).
select payload->>'action' as action, count(*) as events, max(created_at) as latest
from auth.audit_log_entries
where created_at > now() - interval '90 days'
group by 1
order by events desc;
