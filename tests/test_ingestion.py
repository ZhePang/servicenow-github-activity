import copy
import gzip
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.domain import EventConflictError, EventValidationError, normalize_event
from app.store import Store


def test_duplicate_conflict_and_metadata(tmp_path, event):
    store=Store(tmp_path/'events.duckdb')
    first=store.ingest([normalize_event(event)])
    assert (first.inserted,first.duplicates,first.revision)==(1,0,1)
    duplicate=store.ingest([normalize_event(event)])
    assert (duplicate.inserted,duplicate.duplicates,duplicate.revision)==(0,1,1)
    changed=copy.deepcopy(event);changed['payload']['action']='different'
    fresh=copy.deepcopy(event);fresh['id']='new'
    with pytest.raises(EventConflictError): store.ingest([normalize_event(fresh),normalize_event(changed)])
    with store.read() as c:
        assert store.metadata(c)['unique_event_count']==1
        assert c.execute('SELECT count(*) FROM events').fetchone()[0]==1
    store.close()


def test_snapshot_atomic_replay_arrival_sequence_and_parity(tmp_path,event):
    from scripts.import_snapshot import import_snapshot
    later=copy.deepcopy(event);later['id']='later';later['created_at']='2026-08-03T12:00:00Z'
    early=copy.deepcopy(event);early['id']='earlier'
    path=tmp_path/'events.jsonl.gz'
    with gzip.open(path,'wt') as out:
        for row in [later,early,later]:out.write(json.dumps(row)+'\n')
    store=Store(tmp_path/'snapshot.duckdb')
    result=import_snapshot(store,path)
    assert result.inserted==2 and result.duplicates==1
    with store.read() as c:
        assert c.execute('SELECT event_id FROM events ORDER BY ingest_seq').fetchall()==[('later',),('earlier',)]
    assert import_snapshot(store,path).inserted==0
    receiver=Store(tmp_path/'api.duckdb');receiver.ingest([normalize_event(later),normalize_event(early)])
    with store.read() as a,receiver.read() as b:
        columns='event_id,repo_id,actor_id,event_type,action,occurred_at,content_hash'
        assert a.execute('SELECT '+columns+' FROM events ORDER BY event_id').fetchall()==b.execute('SELECT '+columns+' FROM events ORDER BY event_id').fetchall()
    store.close();receiver.close()


def test_bad_line_and_conflicting_staging_abort(tmp_path,event):
    from scripts.import_snapshot import import_snapshot
    store=Store(tmp_path/'events.duckdb');path=tmp_path/'bad.gz'
    with gzip.open(path,'wt') as out:out.write(json.dumps(event)+'\n{}\n')
    with pytest.raises(EventValidationError,match='line 2'):import_snapshot(store,path)
    changed=copy.deepcopy(event);changed['type']='DifferentEvent'
    with gzip.open(path,'wt') as out:out.write(json.dumps(event)+'\n'+json.dumps(changed)+'\n')
    with pytest.raises(EventConflictError,match=r'line\(s\) 1, 2'):import_snapshot(store,path)
    with store.read() as c:assert c.execute('SELECT count(*) FROM events').fetchone()[0]==0
    store.close()


def test_reader_transaction_stays_consistent(tmp_path,event):
    store=Store(tmp_path/'events.duckdb')
    with store.read() as old:
        assert store.metadata(old)['revision']==0
        store.ingest([normalize_event(event)])
        assert store.metadata(old)['revision']==0
        assert old.execute('SELECT count(*) FROM events').fetchone()[0]==0
    with store.read() as new:assert store.metadata(new)['revision']==1
    store.close()


def test_http_receiver_and_persistence(tmp_path,event):
    from app.main import create_app
    path=tmp_path/'events.duckdb'
    with TestClient(create_app(path)) as client:
        assert client.get('/api/health').status_code==200
        assert client.post('/api/events',json=event).status_code==201
        assert client.post('/api/events',json=event).json()['status']=='duplicate'
        changed=copy.deepcopy(event);changed['type']='OtherEvent'
        assert client.post('/api/events',json=changed).status_code==409
        assert client.post('/api/events',json={}).status_code==422
    reopened=Store(path)
    with reopened.read() as c:assert reopened.metadata(c)['unique_event_count']==1
    reopened.close()
