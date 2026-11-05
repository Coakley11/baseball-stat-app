-- READ-ONLY (SELECT only). Run in the QA project only. Nothing is changed.
-- Account ids are shown as 6-character hashes; compare hashes across sections.

-- Q1 accounts: username (external_id) and hash, one row per QA account
select 'Q1_account' as section, left(md5(id::text), 6) as item,
       concat_ws(' | ', 'username ' || external_id,
                        'email ' || left(coalesce(email, ''), 2) || '***@' || split_part(coalesce(email, ''), '@', 2)) as value
from public.suite_users
union all
-- Q2 leagues: origin, commissioner, counts
select 'Q2_league', league_id,
       concat_ws(' | ', 'name ' || coalesce(shared_league_json->>'league_name', '?'),
         'origin ' || coalesce(shared_league_json->>'created_from', '?') || '/' || coalesce(shared_league_json->>'source', '?'),
         'commissioner ' || coalesce(left(md5(nullif(shared_league_json->>'commissioner_user_id', '')), 6), 'NONE'),
         'revision ' || revision::text,
         'updated ' || to_char(updated_at at time zone 'UTC', 'HH24:MI:SS') || ' UTC')
from public.baseball_shared_leagues
union all
-- Q3a invites per league
select 'Q3_invite', l.league_id || ' / ' || coalesce(i->>'invite_id', '?'),
       concat_ws(' | ', 'status ' || coalesce(i->>'status', '?'),
         'to ' || coalesce(nullif(i->>'invitee_external_id', ''), '?'),
         'account ' || coalesce(left(md5(nullif(i->>'invitee_user_id', '')), 6), 'EMPTY'),
         'claimed ' || coalesce(nullif(i->>'claimed_team', ''), '-'))
from public.baseball_shared_leagues l
cross join lateral jsonb_array_elements(
  case when jsonb_typeof(l.shared_league_json->'league_invites') = 'array' then l.shared_league_json->'league_invites' else '[]'::jsonb end) i
union all
-- Q3b team owners per league
select 'Q3_team', l.league_id || ' / ' || t.key,
       concat_ws(' | ', 'owner ' || coalesce(left(md5(nullif(coalesce(t.value->>'user_id', t.value->>'account_user_id'), '')), 6), 'NONE'),
                        'status ' || coalesce(nullif(t.value->>'claim_status', ''), '-'))
from public.baseball_shared_leagues l
cross join lateral jsonb_each(
  case when jsonb_typeof(l.shared_league_json->'team_ownership') = 'object' then l.shared_league_json->'team_ownership' else '{}'::jsonb end) t
union all
-- Q4 rooms: status, picks, seats
select 'Q4_room', room_code,
       concat_ws(' | ', 'status ' || status, 'revision ' || revision::text,
         'picks ' || coalesce(jsonb_array_length(case when jsonb_typeof(shared_room_json->'room'->'draft_board') = 'array'
                                                      then shared_room_json->'room'->'draft_board' end), 0)::text,
         'seats ' || coalesce((select string_agg(coalesce(p.value->>'assigned_team', '?') || '=' ||
                                 coalesce(left(md5(nullif(coalesce(p.value->>'account_user_id', p.value->>'user_id'), '')), 6), 'NONE'), ', ')
                               from jsonb_each(case when jsonb_typeof(shared_room_json->'participants') = 'object'
                                                    then shared_room_json->'participants' else '{}'::jsonb end) p), '-'),
         'updated ' || to_char(updated_at at time zone 'UTC', 'HH24:MI:SS') || ' UTC')
from public.baseball_shared_draft_rooms
order by 1, 2;
