import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from baseball_activity import log_player_comparison
from suite_deep_links import build_resume_action_url, comparison_players, comparison_resume_key, resume_metrics_from_item_key
from suite_resume_launch import _apply_baseball


def test_comparison_producer_preserves_pair_trio_and_distinct_third_player():
    with patch('baseball_activity._record') as record:
        log_player_comparison('Aaron Judge', 'Juan Soto')
        log_player_comparison(players=['Aaron Judge', 'Juan Soto', 'Mike Trout'])
        log_player_comparison(players=['Aaron Judge', 'Juan Soto', 'Mookie Betts'])
    calls=[call.kwargs for call in record.call_args_list]
    assert [x['metrics']['players'] for x in calls] == [
        ['Aaron Judge','Juan Soto'], ['Aaron Judge','Juan Soto','Mike Trout'], ['Aaron Judge','Juan Soto','Mookie Betts']]
    assert len({x['resume_key'] for x in calls}) == 3
    assert calls[0]['resume_key'] == 'compare:Aaron Judge:Juan Soto'
    assert calls[1]['resume_subtitle'] == 'Aaron Judge vs Juan Soto vs Mike Trout'


def test_duplicate_player_is_not_recorded_as_a_third_identity():
    with patch('baseball_activity._record') as record:
        log_player_comparison(players=['Aaron Judge','Juan Soto','Aaron Judge'])
        assert record.call_args.kwargs['metrics']['players'] == ['Aaron Judge','Juan Soto']
        record.reset_mock()
        log_player_comparison(players=['Aaron Judge','Aaron Judge'])
        record.assert_not_called()


def test_historical_pair_and_trio_restore_replace_newer_context():
    for players in (['Aaron Judge','Juan Soto'], ['Mike Trout','Mookie Betts','Freddie Freeman']):
        key=comparison_resume_key(players)
        page,metrics=resume_metrics_from_item_key('baseball',key)
        assert metrics['player_b']==players[1]
        url=build_resume_action_url('baseball',resume_key=key,page=page,metrics=metrics,base_url='http://localhost')
        query={k:v[0] for k,v in parse_qs(urlparse(url).query).items()}
        assert json.loads(query['suite_players'])==players
        st=SimpleNamespace(query_params=query,session_state={'pending_compare_players':['Newer','Global','State']})
        _apply_baseball(st,key,page)
        assert st.session_state['pending_compare_players']==players
    legacy=SimpleNamespace(query_params={},session_state={'pending_compare_players':['Newer','State']})
    _apply_baseball(legacy,'compare:Aaron Judge:Juan Soto','Comparison Tool')
    assert legacy.session_state['pending_compare_players']==['Aaron Judge','Juan Soto']


def test_canonical_list_wins_without_inventing_a_third_player():
    assert comparison_players({'players':['A','B'],'player_a':'X','player_b':'Y'},'compare:X:Y:Z')==['A','B']
    assert comparison_players({'players':['A',None,'A','B','C','D']})==['A','B','C']
