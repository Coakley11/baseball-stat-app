import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from draft_archive_state import get_draft_archive
from draft_room_state import build_snake_board, coerce_board_table, prepare_draft_room_state, ensure_simulator_board_for_settings
from draft_actions import draft_player
from draft_state import add_player_to_draft_queue
from fantasy_league_context import save_simulator_league_context
from saved_draft_library_selection import repair_incoherent_active_library_selection
from saved_mock_resume import apply_pending_saved_mock_resume, resumed_mock_save_owner, save_resumed_mock_board


@pytest.fixture
def drafts(monkeypatch):
    monkeypatch.setattr('draft_library_manifest.publish_library_manifest_to_cloud',lambda *a,**k:None)
    monkeypatch.setattr('fantasy_shared_league_store.sync_context_with_shared_store',lambda session,context:context)
    s={}
    for id,players in [('A',['Aaron Judge','Juan Soto','Mike Trout']),('B',['Freddie Freeman','Corey Seager','Bryce Harper'])]:
        board=build_snake_board(['QA A','QA B'],rounds=6)
        for i,name in enumerate(players):board.at[i,'Player']=name
        save_simulator_league_context(s,board,my_team_name='QA A',draft_name='QA Mock '+id,draft_id=id,
            reuse_session_draft_id=False,config={'teams':['QA A','QA B'],'rounds':6,'fantasy_format':'5x5 Roto'})
    return s


def resume(s,id):
    s['_suite_resume_saved_draft_id']=id
    result=apply_pending_saved_mock_resume(s)
    assert result.get('applied'),result
    prepare_draft_room_state(s)
    ensure_simulator_board_for_settings(s)
    assert resumed_mock_save_owner(s)==id
    repair_incoherent_active_library_selection(s)
    assert resumed_mock_save_owner(s)==id
    assert s['draft_room_state']['saved_mock_draft_id']==id
    assert s['draft_room_table']['Player'].tolist()==[x['Player'] for x in get_draft_archive(s,id)['draft_board']]


def test_old_a_old_b_and_repeated_switches_are_coherent(drafts):
    for id in ['A','B','A','B']:
        resume(drafts,id)


@pytest.mark.parametrize('target,other',[('A','B'),('B','A')])
def test_post_resume_player_action_and_save_touch_only_target(drafts,target,other):
    original_other=copy.deepcopy(get_draft_archive(drafts,other))
    resume(drafts,target)
    add_player_to_draft_queue(drafts,'Kyle Tucker')
    result=draft_player(drafts,'Kyle Tucker',source='queue')
    assert result['ok'],result
    assert resumed_mock_save_owner(drafts)==target
    assert save_resumed_mock_board(drafts,drafts['draft_room_table'])==target
    assert any(x.get('Player')=='Kyle Tucker' for x in get_draft_archive(drafts,target)['draft_board'])
    assert get_draft_archive(drafts,other)==original_other
    resume(drafts,other);resume(drafts,target)
    assert 'Kyle Tucker' in drafts['draft_room_table']['Player'].tolist()


def test_page_widget_cleanup_cannot_remove_bound_mock_team(drafts):
    resume(drafts, 'A')
    drafts.pop('room_your_team', None)
    add_player_to_draft_queue(drafts, 'Kyle Tucker')
    result = draft_player(drafts, 'Kyle Tucker', source='queue')
    assert result['ok'], result
    assert save_resumed_mock_board(drafts, drafts['draft_room_table']) == 'A'
    assert get_draft_archive(drafts, 'A')['team_name'] == 'QA A'


def test_explicit_bound_save_does_not_reactivate_rendered_widgets(drafts):
    resume(drafts, 'A')
    with patch('fantasy_league_context.activate_league_context', side_effect=AssertionError('widget already rendered')):
        assert save_resumed_mock_board(drafts, drafts['draft_room_table']) == 'A'


def test_stale_runtime_board_cannot_be_retagged_by_a_player_action(drafts):
    resume(drafts, 'B');stale = drafts['draft_room_table'].copy()
    resume(drafts, 'A');drafts['draft_room_table'] = stale
    result = draft_player(drafts, 'Kyle Tucker', source='queue')
    assert not result['ok']
    assert result['error'] == 'saved_mock_owner_mismatch'


@pytest.mark.parametrize('resume_key', ['bb:saved_draft:A', 'compare:Aaron Judge:Juan Soto:Mike Trout', 'trend:Aaron Judge'])
def test_resource_resume_hydrates_workspace_before_mutating_it(resume_key):
    from suite_cloud_state import should_skip_workspace_restore_for_resume
    st = SimpleNamespace(session_state={}, query_params={'suite_resume':resume_key, 'suite_page':'Saved Draft Library'})
    assert not should_skip_workspace_restore_for_resume(st, 'baseball')
    st.query_params['suite_ami_insight'] = 'qa-insight'
    assert should_skip_workspace_restore_for_resume(st, 'baseball')


def test_saved_id_only_resume_hydrates_and_preserves_parked_slot(drafts):
    from suite_cloud_state import should_skip_workspace_restore_for_resume
    from baseball_persistent_state import build_baseball_disk_state, apply_baseball_disk_state
    st = SimpleNamespace(session_state={}, query_params={'suite_saved_draft':'A'})
    assert not should_skip_workspace_restore_for_resume(st, 'baseball')
    slot = {'kind':'resumable_live_draft_slot','draft_id':'QA-SOLO','room':{'draft_board':[{'Player':'QA Player'}]*14},'queues':{'draft_queue':['Ketel Marte']}}
    drafts['resumable_live_draft_slot'] = copy.deepcopy(slot)
    resume(drafts, 'A')
    payload = build_baseball_disk_state(SimpleNamespace(session_state=drafts,query_params={}))
    apply_baseball_disk_state(st, json.loads(json.dumps(payload,default=str)))
    assert st.session_state['resumable_live_draft_slot'] == slot


@pytest.mark.parametrize('players', [['Aaron Judge','Juan Soto'], ['Aaron Judge','Juan Soto','Mike Trout']])
def test_historical_comparison_wins_after_full_workspace_hydration(players):
    from suite_resume_launch import _apply_baseball, apply_pending_baseball_analysis_resume
    from baseball_persistent_state import apply_baseball_disk_state
    from comparison_state import prepare_comparison_tool_page
    st = SimpleNamespace(session_state={}, query_params={'suite_players':json.dumps(players)})
    _apply_baseball(st, 'compare:'+':'.join(players), 'Comparison Tool')
    apply_baseball_disk_state(st, {'comparison_state':{'players':['Manny Machado','Juan Soto']}})
    assert apply_pending_baseball_analysis_resume(st.session_state)
    labels={name:name for name in players+['Manny Machado']}
    assert prepare_comparison_tool_page(st.session_state, labels, lambda name:name)==players
    assert not apply_pending_baseball_analysis_resume(st.session_state)


def test_historical_trend_wins_after_full_workspace_hydration():
    from suite_resume_launch import _apply_baseball, apply_pending_baseball_analysis_resume
    from baseball_persistent_state import apply_baseball_disk_state
    from trend_state import prepare_trend_value_page
    st = SimpleNamespace(session_state={}, query_params={'suite_trend_player':'Aaron Judge'})
    _apply_baseball(st, 'trend:Aaron Judge', 'Trend Value')
    apply_baseball_disk_state(st, {'trend_state':{'chart_player':'Mike Trout','players_multi':['Mike Trout']}})
    assert apply_pending_baseball_analysis_resume(st.session_state)
    prepare_trend_value_page(st.session_state, {'Aaron Judge':1,'Mike Trout':2}, lambda name:name)
    assert st.session_state['trend_state']['chart_player']=='Aaron Judge'
    assert st.session_state['single_trend_dashboard_player']=='Aaron Judge'
    assert not apply_pending_baseball_analysis_resume(st.session_state)


def test_queue_scope_is_not_copied_from_previous_mock(drafts):
    resume(drafts,'A');add_player_to_draft_queue(drafts,'Kyle Tucker')
    resume(drafts,'B');assert drafts['draft_queue']==[]
    add_player_to_draft_queue(drafts,'Manny Machado')
    resume(drafts,'A');assert drafts['draft_queue']==['Kyle Tucker']
    resume(drafts,'B');assert drafts['draft_queue']==['Manny Machado']


def test_owner_drift_rejects_player_action_and_save(drafts):
    resume(drafts,'A')
    drafts['_simulator_session_library_draft_id']='B'
    with pytest.raises(ValueError):save_resumed_mock_board(drafts,drafts['draft_room_table'])
    result=draft_player(drafts,'Kyle Tucker',source='queue')
    assert result['error']=='saved_mock_owner_mismatch'


def test_same_content_in_b_cannot_redirect_an_explicit_a_save(drafts):
    resume(drafts,'A');original_b=copy.deepcopy(get_draft_archive(drafts,'B'))
    board=coerce_board_table(original_b['draft_board'])
    board.attrs['saved_mock_draft_id']='A' # Deliberate A edit resulting in B's same content.
    save_resumed_mock_board(drafts,board)
    assert resumed_mock_save_owner(drafts)=='A'
    assert get_draft_archive(drafts,'B')==original_b


def test_rosters_save_only_updates_the_bound_mock_instead_of_forking(drafts):
    resume(drafts,'A');original_b=copy.deepcopy(get_draft_archive(drafts,'B'))
    board=drafts['draft_room_table'].copy();board.at[3,'Player']='Kyle Tucker'
    entry,_=save_simulator_league_context(drafts,board,my_team_name='QA A',draft_name='QA Mock A',save_only=True)
    assert entry['draft_id']=='A'
    assert get_draft_archive(drafts,'B')==original_b


def test_binding_survives_serialization_and_rerun_without_replaying_board(drafts):
    resume(drafts,'A')
    from baseball_persistent_state import build_baseball_disk_state
    payload=build_baseball_disk_state(SimpleNamespace(session_state=drafts,query_params={}))
    assert payload['draft_room_state']['saved_mock_draft_id']=='A'
    assert payload['draft_room_table']['saved_mock_draft_id']=='A'
    # Match the persisted canonical-blob boundary; runtime DataFrames are rebuilt.
    restored={k:copy.deepcopy(v) for k,v in drafts.items() if k in (
        'draft_archive_teams','fantasy_league_context_state','active_draft_archive_id','draft_room_state',
        'saved_mock_edit_draft_id','saved_mock_board_draft_id','saved_mock_workflows',
        '_simulator_session_library_draft_id','_simulator_library_draft_name','room_your_team')}
    restored=json.loads(json.dumps(restored,default=str))
    restored['draft_room_table']=coerce_board_table(restored['draft_room_state'])
    assert resumed_mock_save_owner(restored)=='A'
    assert apply_pending_saved_mock_resume(restored)=={}


def test_missing_target_never_falls_back_to_latest(drafts):
    before=copy.deepcopy(drafts)
    drafts['_suite_resume_saved_draft_id']='MISSING'
    assert apply_pending_saved_mock_resume(drafts).get('error')
    assert drafts['active_draft_archive_id']==before['active_draft_archive_id']


def test_richer_stale_other_draft_cache_is_not_a_save_authority(drafts):
    resume(drafts,'B')
    stale=drafts['draft_room_table'].copy();stale.at[3,'Player']='Kyle Tucker'
    resume(drafts,'A')
    drafts['draft_room_board_editor_cache']=stale
    from draft_room_state import _resolve_richest_draft_board
    board,count,source=_resolve_richest_draft_board(drafts)
    assert count==3
    assert 'Freddie Freeman' not in board['Player'].tolist()
    with pytest.raises(ValueError):save_resumed_mock_board(drafts,stale)
