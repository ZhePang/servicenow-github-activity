"""Analytical queries over the canonical event table; raw JSON is never scanned."""
from dataclasses import asdict
from datetime import timedelta

from app.domain import EventValidationError, RepositoryReport, TimeRange, TrendRow
from app.store import Store

CONTRIBUTION = """(event_type='PushEvent'
 OR (event_type IN ('PullRequestEvent','IssuesEvent') AND action='opened')
 OR (event_type IN ('PullRequestReviewEvent','IssueCommentEvent','PullRequestReviewCommentEvent') AND action='created'))"""


def records(cursor,sql,parameters=None):
    result=cursor.execute(sql,parameters or [])
    columns=[d[0] for d in result.description]
    return [dict(zip(columns,row)) for row in result.fetchall()]


def metadata(cursor):
    value=Store.metadata(cursor)
    value['repository_count']=cursor.execute('SELECT count(DISTINCT repo_id) FROM events').fetchone()[0]
    earliest,latest=value['min_event_time'],value['max_event_time']
    value['coverage_start']=earliest.replace(hour=0,minute=0,second=0,microsecond=0) if earliest else None
    value['coverage_end']=latest.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1) if latest else None
    value['watermark']=latest
    return value


def validate_range(period,meta):
    if meta['coverage_start'] is not None:
        if period.start<meta['coverage_start'] or period.end>meta['coverage_end']:
            raise EventValidationError('range','Select a range within the available UTC date bounds.')


def trending(cursor,period: TimeRange,sort='momentum',limit=20,search=''):
    meta=metadata(cursor);validate_range(period,meta)
    duration=period.end-period.start
    comparison=meta['coverage_start'] is not None and duration<=period.start-meta['coverage_start']
    previous_start=period.start-duration if comparison else None
    effective=sort if comparison else 'stars'
    order='momentum DESC,stars DESC,s.repo_id' if effective=='momentum' else 'stars DESC,s.repo_id'
    sql=f"""
    WITH names AS (
      SELECT repo_id,repo_name FROM events
      QUALIFY row_number() OVER (PARTITION BY repo_id ORDER BY occurred_at DESC,ingest_seq DESC)=1
    ), stars AS (
      SELECT repo_id,count(*) FILTER(WHERE occurred_at>=?) AS stars,
        count(*) FILTER(WHERE occurred_at<?) AS previous_stars
      FROM events WHERE event_type='WatchEvent' AND action='started'
        AND occurred_at>=? AND occurred_at<? GROUP BY repo_id
    ) SELECT s.repo_id,n.repo_name,s.stars,s.previous_stars,
        s.stars-s.previous_stars AS momentum
      FROM stars s JOIN names n USING(repo_id)
      WHERE stars>0 AND n.repo_name ILIKE ? ORDER BY {order} LIMIT ?
    """
    values=records(cursor,sql,[period.start,period.start,previous_start if comparison else period.start,
                               period.end,'%'+search+'%',limit])
    rows=[asdict(TrendRow(r['repo_id'],r['repo_name'],r['stars'],r['previous_stars'] if comparison else None,
                         r['momentum'] if comparison else None)) for r in values]
    return {'repositories':rows,'comparison_available':comparison,'requested_sort':sort,'effective_sort':effective,
            'previous_start':previous_start if comparison else None,'revision':meta['revision'],
            'watermark':meta['watermark'],'start':period.start,'end':period.end,
            'metric':'New star events; momentum is current minus previous equal-length window.'}


def activity(cursor,repo_id,period):
    grain='hour' if period.end-period.start<=timedelta(hours=48) else 'day'
    step=timedelta(hours=1) if grain=='hour' else timedelta(days=1)
    floor=period.start.replace(minute=0,second=0,microsecond=0)
    if grain=='day':floor=floor.replace(hour=0)
    buckets=[]
    while floor<period.end:
        buckets.append(floor);floor+=step
    kinds=[r[0] for r in cursor.execute('SELECT DISTINCT event_type FROM events WHERE repo_id=? ORDER BY event_type',[repo_id]).fetchall()]
    counts=cursor.execute(f"SELECT date_trunc('{grain}',occurred_at),event_type,count(*) FROM events WHERE repo_id=? AND occurred_at>=? AND occurred_at<? GROUP BY 1,2",[repo_id,period.start,period.end]).fetchall()
    lookup={(t,kind):n for t,kind,n in counts}
    return {'grain':grain,'buckets':buckets,'series':[{'type':kind,'counts':[lookup.get((t,kind),0) for t in buckets]} for kind in kinds]}


STATE_CTE="""
WITH states AS (
 SELECT pr_number,action,occurred_at,ingest_seq FROM events
 WHERE repo_id=? AND event_type='PullRequestEvent'
   AND action IN ('opened','reopened','closed','merged')
 QUALIFY row_number() OVER (PARTITION BY pr_number ORDER BY occurred_at DESC,ingest_seq DESC)=1
), opens AS (
 SELECT pr_number,occurred_at AS opened_at,actor_login AS opened_by FROM events
 WHERE repo_id=? AND event_type='PullRequestEvent' AND action='opened'
 QUALIFY row_number() OVER (PARTITION BY pr_number ORDER BY occurred_at,ingest_seq)=1
), observed AS (
 SELECT s.pr_number AS number,s.action,s.occurred_at AS state_at,s.ingest_seq,o.opened_at,o.opened_by
 FROM states s LEFT JOIN opens o USING(pr_number) WHERE s.action IN ('opened','reopened')
)
"""


def open_prs(cursor,repo_id,offset,limit,watermark):
    total=cursor.execute(STATE_CTE+'SELECT count(*) FROM observed',[repo_id,repo_id]).fetchone()[0]
    items=records(cursor,STATE_CTE+'SELECT * EXCLUDE(ingest_seq) FROM observed ORDER BY state_at DESC,number LIMIT ? OFFSET ?',
                  [repo_id,repo_id,limit,offset])
    return {'total':total,'items':items,'offset':offset,'limit':limit,'as_of':watermark,
            'note':'Observed state from available history; not a complete list of current GitHub PRs.'}


def merge_stats(cursor,repo_id,period):
    sql="""
    WITH pairs AS (
      SELECT pr_number,min(occurred_at) FILTER(WHERE action='opened') AS opened,
        min(occurred_at) FILTER(WHERE action='merged') AS merged
      FROM events WHERE repo_id=? AND event_type='PullRequestEvent' GROUP BY pr_number
    ), selected AS (
      SELECT CASE WHEN opened IS NOT NULL AND merged>=opened THEN epoch(merged-opened) END AS duration_s
      FROM pairs WHERE merged>=? AND merged<?
    ) SELECT count(*) AS merged_prs,count(duration_s) AS paired_prs,
      median(duration_s) AS median_seconds,avg(duration_s) AS mean_seconds,
      quantile_cont(duration_s,.9) AS p90_seconds FROM selected
    """
    row=records(cursor,sql,[repo_id,period.start,period.end])[0]
    row['coverage']=row['paired_prs']/row['merged_prs'] if row['merged_prs'] else None
    row['note']='Time from first observed opening to merge. Missing opening history is excluded.'
    return row


def contributors(cursor,repo_id,period,include_bots):
    sql=f"""
    SELECT actor_id,arg_max(actor_login,struct_pack(t:=occurred_at,s:=ingest_seq)) AS login,
      count(*) AS contributions,
      count(*) FILTER(WHERE event_type='PushEvent') AS pushes,
      count(*) FILTER(WHERE event_type='PullRequestEvent') AS pull_requests,
      count(*) FILTER(WHERE event_type='IssuesEvent') AS issues,
      count(*) FILTER(WHERE event_type='PullRequestReviewEvent') AS reviews,
      count(*) FILTER(WHERE event_type IN ('IssueCommentEvent','PullRequestReviewCommentEvent')) AS comments
    FROM events WHERE repo_id=? AND occurred_at>=? AND occurred_at<?
      AND (? OR NOT is_bot) AND {CONTRIBUTION}
    GROUP BY actor_id ORDER BY contributions DESC,actor_id LIMIT 10
    """
    return records(cursor,sql,[repo_id,period.start,period.end,include_bots])


def repository_report(cursor,repo_id,period,include_bots=False,offset=0,limit=25):
    meta=metadata(cursor);validate_range(period,meta)
    name=cursor.execute('SELECT repo_name FROM events WHERE repo_id=? ORDER BY occurred_at DESC,ingest_seq DESC LIMIT 1',[repo_id]).fetchone()
    if not name:return None
    report=RepositoryReport(repo_id,name[0],activity(cursor,repo_id,period),
                            open_prs(cursor,repo_id,offset,limit,meta['watermark']),
                            merge_stats(cursor,repo_id,period),contributors(cursor,repo_id,period,include_bots),meta['revision'])
    return {**asdict(report),'start':period.start,'end':period.end,'include_bots':include_bots,
            'contributor_metric':'Contribution events: pushes, opened PRs/issues, created reviews and comments.'}
