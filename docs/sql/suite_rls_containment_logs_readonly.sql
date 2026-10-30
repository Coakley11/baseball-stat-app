-- READ-ONLY. For the Supabase Dashboard Logs Explorer, not the SQL editor: it reads the gateway
-- logs, not the database. Aggregates only: no IP, no header value except the client-library tag,
-- no query string, no body (the gateway does not log bodies, apikey or Authorization).
-- Field names follow Supabase's log field reference (source 'edge_logs', log_attributes keys).
-- The time range comes from the Explorer's range picker; choose the longest your plan retains.
--
-- Limits:
--   * The gateway logs no role, so an anon request and a service-role request to the same path
--     look alike. The apps call these tables server-side with the service role, so the signals
--     are a different client tag, an unusual method or volume, or a burst at an odd time.
--   * Retention is plan-dependent and is probably shorter than the exposure was. An empty
--     result before the retained window proves nothing.

-- L1. Requests to the three contained tables per day, path, method, status and client tag.
-- After containment, anon requests show as 401; before it, 200.
select toDate(timestamp) as day,
       splitByChar('?', log_attributes['request.path'])[1] as path,
       log_attributes['request.method'] as method,
       toInt32OrZero(log_attributes['response.status_code']) as status,
       log_attributes['request.headers.x_client_info'] as client,
       count() as requests
from logs
where source = 'edge_logs'
  and (log_attributes['request.path'] like '/rest/v1/suite_users%'
    or log_attributes['request.path'] like '/rest/v1/suite_saved_items%'
    or log_attributes['request.path'] like '/rest/v1/suite_user_settings%')
group by day, path, method, status, client
order by day desc, requests desc;

-- L2. GraphQL requests per day and status (no suite app uses GraphQL, so any traffic is notable).
select toDate(timestamp) as day,
       toInt32OrZero(log_attributes['response.status_code']) as status,
       log_attributes['request.headers.x_client_info'] as client,
       count() as requests
from logs
where source = 'edge_logs'
  and log_attributes['request.path'] like '/graphql/v1%'
group by day, status, client
order by day desc, requests desc;
