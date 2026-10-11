"""Check the independent reference oracle and benchmark math with explicit fixtures."""
from datetime import datetime, timezone

import pytest

from scripts.benchmark import latency_summary, reference_repository, reference_trends


def event(identifier, kind, when, action=None, pr=None, actor=1, login='alice', seq=1):
    return dict(event_id=identifier, repo_id=10, repo_name='owner/project', actor_id=actor,
                actor_login=login, event_type=kind, action=action, pr_number=pr,
                occurred_at=datetime.fromisoformat(when).replace(tzinfo=timezone.utc), ingest_seq=seq)


def test_latency_summary_uses_interpolated_percentiles():
    result=latency_summary([10,20,30,40])
    assert result=={'samples':4,'median_ms':25,'p95_ms':38.5,'max_ms':40}
    with pytest.raises(ValueError):latency_summary([])


def test_reference_repository_resolves_state_and_sparse_merge_history():
    events=[event('1','PullRequestEvent','2026-08-01T01:00', 'opened',1),
            event('2','PullRequestEvent','2026-08-02T01:00', 'merged',1),
            event('3','PullRequestEvent','2026-08-02T02:00', 'merged',2),
            event('4','PullRequestEvent','2026-08-02T03:00', 'opened',3,seq=4),
            event('5','PullRequestEvent','2026-08-02T03:00', 'closed',3,seq=5),
            event('6','PullRequestEvent','2026-08-02T03:00', 'reopened',3,seq=6),
            event('7','PullRequestEvent','2026-08-02T04:00', 'labeled',3,seq=7),
            event('8','IssueCommentEvent','2026-08-02T05:00','created',actor=2,login='helper[bot]'),
            event('9','IssueCommentEvent','2026-08-02T05:30','deleted'),
            event('10','PushEvent','2026-08-02T06:00')]
    start=datetime(2026,8,2,tzinfo=timezone.utc);end=datetime(2026,8,3,tzinfo=timezone.utc)
    report=reference_repository(events,start,end,False)
    assert report['open_numbers']==[3]
    assert report['merge_stats']['merged_prs']==2
    assert report['merge_stats']['paired_prs']==1
    assert report['merge_stats']['median_seconds']==86400
    assert report['contributors']==[{'actor_id':1,'contributions':2,'pushes':1,'pull_requests':1,'issues':0,'reviews':0,'comments':0}]
    assert report['activity_counts'][('2026-08-02T03:00:00+00:00','PullRequestEvent')]==3
    with_bots=reference_repository(events,start,end,True)
    assert len(with_bots['contributors'])==2


def test_reference_trends_uses_equal_window_and_deterministic_ties():
    events=[event('1','WatchEvent','2026-08-01T12:00','started'),
            event('2','WatchEvent','2026-08-02T12:00','started'),
            event('3','WatchEvent','2026-08-02T13:00','started'),
            event('4','WatchEvent','2026-08-02T14:00','deleted')]
    start=datetime(2026,8,2,tzinfo=timezone.utc);end=datetime(2026,8,3,tzinfo=timezone.utc)
    assert reference_trends(events,start,end,True,'momentum')==[
        {'repo_id':10,'repo_name':'owner/project','stars':2,'previous_stars':1,'momentum':1}]
    assert reference_trends(events,start,end,False,'momentum')[0]['previous_stars'] is None
