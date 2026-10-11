from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.domain import normalize_event, TimeRange, parse_timestamp
from app.main import create_app
from app.store import Store


def event(number, when, kind='WatchEvent', action='started', repo=1, pr=None, bot=False):
    payload={} if action is None else {'action':action}
    if pr is not None:payload['number']=pr
    return {'id':str(number),'created_at':when,'type':kind,'payload':payload,
            'repo':{'id':repo,'name':f'owner/repo-{repo}'},
            'actor':{'id':21 if bot else 20,'login':'robot[bot]' if bot else 'alice'}}


@pytest.fixture
def store(tmp_path):
    value=Store(tmp_path/'events.duckdb')
    value.ingest([normalize_event(event('coverage-start','2026-08-01T00:00:00Z','FutureEvent',None)),
                  normalize_event(event('coverage-end','2026-08-04T23:00:00Z','FutureEvent',None))])
    yield value
    value.close()


def window(start='2026-08-03T00:00:00Z',end='2026-08-04T00:00:00Z'):
    return TimeRange(parse_timestamp(start),parse_timestamp(end))


def test_momentum_boundaries_and_unavailable_history(store):
    from app.queries import trending
    rows=[event('previous-a-'+str(i),'2026-08-02T12:00:00Z') for i in range(2)]
    rows += [event('current-a-'+str(i),'2026-08-03T00:00:00Z') for i in range(3)]
    rows += [event('current-b-'+str(i),'2026-08-03T12:00:00Z',repo=2) for i in range(5)]
    rows += [event('outside','2026-08-04T00:00:00Z')]
    store.ingest([normalize_event(row) for row in rows])
    with store.read() as c:
        value=trending(c,window(),'momentum',20,'')
        assert value['comparison_available'] and value['effective_sort']=='momentum'
        assert [(r['repo_id'],r['stars'],r['previous_stars'],r['momentum']) for r in value['repositories']]==[(2,5,0,5),(1,3,2,1)]
        all_data=trending(c,window('2026-08-01T00:00:00Z','2026-08-05T00:00:00Z'),'momentum',20,'')
        assert not all_data['comparison_available'] and all_data['effective_sort']=='stars'
        assert all_data['repositories'][0]['previous_stars'] is None
        assert trending(c,window(),'stars',20,'repo-1')['repositories'][0]['repo_id']==1


def test_activity_exact_filter_zero_fill(store):
    from app.queries import repository_report
    rows=[event('first','2026-08-03T00:30:00Z'),event('last','2026-08-03T02:29:59Z'),event('end-excluded','2026-08-03T02:30:00Z')]
    store.ingest([normalize_event(r) for r in rows])
    with store.read() as c:
        value=repository_report(c,1,window('2026-08-03T00:30:00Z','2026-08-03T02:30:00Z'),False,0,25)
        series={s['type']:s['counts'] for s in value['activity']['series']}
        assert series['WatchEvent']==[1,0,1]
        assert value['activity']['grain']=='hour'
        assert len(value['activity']['buckets'])==3


def test_pr_state_history_labeling_reopen_ties_and_pagination(store):
    from app.queries import repository_report
    rows=[event('open1','2026-08-01T12:00:00Z','PullRequestEvent','opened',pr=1),
          event('close1','2026-08-03T12:00:00Z','PullRequestEvent','closed',pr=1),
          event('label1','2026-08-04T12:00:00Z','PullRequestEvent','labeled',pr=1),
          event('open2','2026-08-01T12:00:00Z','PullRequestEvent','opened',pr=2),
          event('close2','2026-08-03T12:00:00Z','PullRequestEvent','closed',pr=2),
          event('reopen2','2026-08-04T12:00:00Z','PullRequestEvent','reopened',pr=2),
          event('tie-close','2026-08-04T12:00:00Z','PullRequestEvent','closed',pr=3),
          event('tie-open','2026-08-04T12:00:00Z','PullRequestEvent','opened',pr=3),
          event('unknown','2026-08-04T12:00:00Z','PullRequestEvent','labeled',pr=4)]
    store.ingest([normalize_event(r) for r in rows])
    with store.read() as c:
        value=repository_report(c,1,window('2026-08-02T00:00:00Z','2026-08-03T00:00:00Z'),False,0,1)
        assert value['open_prs']['total']==2
        assert value['open_prs']['items'][0]['number']==2
        second=repository_report(c,1,window(),False,1,1)
        assert second['open_prs']['items'][0]['number']==3


def test_merge_duration_opens_before_range_late_arrival_and_missing(store):
    from app.queries import repository_report
    rows=[event('merged','2026-08-03T12:00:00Z','PullRequestEvent','merged',pr=1),
          event('missing','2026-08-03T12:00:00Z','PullRequestEvent','merged',pr=2),
          event('late-open','2026-08-01T12:00:00Z','PullRequestEvent','opened',pr=1)]
    store.ingest([normalize_event(r) for r in rows])
    with store.read() as c:
        value=repository_report(c,1,window(),False,0,25)
        assert value['merge_stats']['merged_prs']==2 and value['merge_stats']['paired_prs']==1
        assert value['merge_stats']['median_seconds']==172800
        assert value['merge_stats']['coverage']==.5
        assert value['open_prs']['total']==0


def test_contributions_use_actions_and_bot_toggle(store):
    from app.queries import repository_report
    rows=[event('push','2026-08-03T12:00:00Z','PushEvent',None),
          event('label','2026-08-03T12:00:00Z','PullRequestEvent','labeled',pr=1),
          event('review','2026-08-03T12:00:00Z','PullRequestReviewEvent','created'),
          event('review-update','2026-08-03T12:00:00Z','PullRequestReviewEvent','updated'),
          event('comment','2026-08-03T12:00:00Z','IssueCommentEvent','created'),
          event('bot-push','2026-08-03T12:00:00Z','PushEvent',None,bot=True)]
    store.ingest([normalize_event(r) for r in rows])
    with store.read() as c:
        value=repository_report(c,1,window(),False,0,25)
        assert value['contributors'][0]['contributions']==3
        assert len(value['contributors'])==1
        bots=repository_report(c,1,window(),True,0,25)['contributors']
        assert [(r['actor_id'],r['contributions']) for r in bots]==[(20,3),(21,1)]


def test_read_api_contract_and_invalid_ranges(tmp_path):
    app=create_app(tmp_path/'events.duckdb')
    with TestClient(app) as client:
        for i,date in enumerate(('2026-08-01T12:00:00Z','2026-08-03T12:00:00Z')):
            assert client.post('/api/events',json=event(i,date)).status_code==201
        assert client.get('/api/meta').json()['unique_event_count']==2
        params={'start':'2026-08-03T00:00:00Z','end':'2026-08-04T00:00:00Z'}
        assert client.get('/api/trending',params=params).json()['repositories'][0]['stars']==1
        assert client.get('/api/repos/1',params=params).status_code==200
        assert client.get('/api/repos/999',params=params).status_code==404
        assert client.get('/api/trending',params={**params,'end':params['start']}).status_code==422
        assert client.get('/api/trending',params={**params,'start':'2026-07-01T00:00:00Z'}).status_code==422
        assert client.get('/api/trending',params={**params,'sort':'injected'}).status_code==422


def test_momentum_ties_empty_chart_and_duration_distribution(store):
    from app.queries import trending, repository_report
    rows=[event('base','2026-08-02T12:00:00Z')]
    rows += [event('a'+str(i),'2026-08-03T12:00:00Z') for i in range(4)]
    rows += [event('b'+str(i),'2026-08-03T12:00:00Z',repo=2) for i in range(3)]
    rows += [event('o1','2026-08-01T12:00:00Z','PullRequestEvent','opened',pr=1),
             event('m1','2026-08-03T12:00:00Z','PullRequestEvent','merged',pr=1),
             event('o2','2026-08-02T12:00:00Z','PullRequestEvent','opened',pr=2),
             event('m2','2026-08-03T12:00:00Z','PullRequestEvent','merged',pr=2)]
    store.ingest([normalize_event(r) for r in rows])
    with store.read() as c:
        assert [r['repo_id'] for r in trending(c,window())['repositories']]==[1,2]
        stats=repository_report(c,1,window())['merge_stats']
        assert stats['mean_seconds']==129600 and stats['median_seconds']==129600
        assert stats['p90_seconds']==164160
        empty=repository_report(c,1,window('2026-08-04T00:00:00Z','2026-08-04T01:00:00Z'))
        assert all(not any(series['counts']) for series in empty['activity']['series'])
        assert empty['merge_stats']['median_seconds'] is None


def test_baseline_underflow_falls_back_to_stars(tmp_path):
    from app.queries import trending
    value=Store(tmp_path/'events.duckdb')
    value.ingest([normalize_event(event('ancient','0001-01-01T12:00:00Z'))])
    with value.read() as c:
        result=trending(c,window('0001-01-01T00:00:00Z','0001-01-02T00:00:00Z'))
        assert not result['comparison_available'] and result['repositories'][0]['stars']==1
    value.close()
