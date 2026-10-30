"""Local slot serialization regression; does not establish browser/ownership acceptance."""
import json
from unittest.mock import patch

from live_draft_resumable_slot import build_resumable_slot,continue_saved_draft,RESUMABLE_LIVE_DRAFT_SLOT_KEY
from draft_room_participant_state import PARTICIPANT_STATE_KEY


def test_solo_queue_and_fourteen_picks_survive_slot_json_roundtrip():
    board=[{'Pick':i,'Round':(i+1)//2,'Team':'QA A' if i%2 else 'QA B','Player':f'Player {i}','playerID':f'qa{i}'} for i in range(1,15)]
    room={'draft_room_id':'QA-S1-SOLO','status':'paused','paused':True,'timer_paused':True,'current_pick_index':14,
          'teams':['QA A','QA B'],'config':{'teams':['QA A','QA B'],'num_teams':2,'picks_per_team':14,'timer_seconds':60,'your_team':'QA A','draft_setup_mode':'solo'},
          'draft_board':board,'pick_order':board+[{'Pick':i,'Team':'QA A' if i%2 else 'QA B'} for i in range(15,29)],
          'drafted_player_ids':[f'qa{i}' for i in range(1,15)],'rosters':{'QA A':[],'QA B':[]}}
    private={'qa-local':{'queue':['Manny Machado'],'notes':'synthetic local'}}
    session={'live_draft_room':room,'draft_queue':['Manny Machado'],'watchlist_focus':['Mike Trout'],
             PARTICIPANT_STATE_KEY:private,'draft_room_participant_id':'qa-local','draft_room_participant_team':'QA A'}
    slot=json.loads(json.dumps(build_resumable_slot(session,room)))
    assert slot['queues']['draft_queue']==['Manny Machado']
    restored={RESUMABLE_LIVE_DRAFT_SLOT_KEY:slot}
    with patch('shared_draft_permissions.can_continue_saved_draft_slot',return_value=True):
        result=continue_saved_draft(restored)
    assert result['ok']
    assert restored['draft_queue']==['Manny Machado']
    assert restored['watchlist_focus']==['Mike Trout']
    assert restored[PARTICIPANT_STATE_KEY]==private
    assert len(restored['live_draft_room']['draft_board'])==14
    assert restored['live_draft_room']['draft_room_id']=='QA-S1-SOLO'
    assert restored['live_draft_room']['paused']
