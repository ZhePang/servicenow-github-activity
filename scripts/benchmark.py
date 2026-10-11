"""Independent snapshot verification and actual HTTP measurements on a disposable DB copy.

Run with python -m scripts.benchmark. Stop any writers to the source DB first.
First requests do not flush the operating-system cache; this is a local feasibility check.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import statistics
import tempfile
import threading
import time

import httpx

from scripts.e2e import live_server


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)


def percentile(values, fraction):
    ordered=sorted(values)
    if not ordered:raise ValueError('At least one sample is required.')
    position=(len(ordered)-1)*fraction;lower=math.floor(position);upper=math.ceil(position)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def latency_summary(milliseconds):
    return {'samples':len(milliseconds),'median_ms':statistics.median(milliseconds),
            'p95_ms':percentile(milliseconds,.95),'max_ms':max(milliseconds)}


def read_reference(path):
    """Read raw JSON independently of app normalization and SQL."""
    rows=[];hashes={};raw_count=0
    with gzip.open(path,'rt',encoding='utf-8') as source:
        for sequence,line in enumerate(source,1):
            raw_count+=1;event=json.loads(line);identifier=str(event['id'])
            digest=hashlib.sha256(json.dumps(event,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            if identifier in hashes:
                assert hashes[identifier]==digest,'Conflicting duplicate in reference input'
                continue
            hashes[identifier]=digest;payload=event.get('payload') or {}
            rows.append(dict(event_id=identifier,repo_id=event['repo']['id'],repo_name=event['repo']['name'],
                             actor_id=event['actor']['id'],actor_login=event['actor']['login'],
                             event_type=event['type'],action=payload.get('action'),
                             pr_number=payload.get('number') or (payload.get('pull_request') or {}).get('number'),
                             occurred_at=timestamp(event['created_at']),ingest_seq=sequence))
    return rows,raw_count


def reference_trends(rows,start,end,comparison,sort,limit=50):
    names={}
    for row in sorted(rows,key=lambda r:(r['occurred_at'],r['ingest_seq'])):names[row['repo_id']]=row['repo_name']
    current=Counter();previous=Counter();previous_start=start-(end-start) if comparison else start
    for row in rows:
        if row['event_type']!='WatchEvent' or row['action']!='started':continue
        if start<=row['occurred_at']<end:current[row['repo_id']]+=1
        elif comparison and previous_start<=row['occurred_at']<start:previous[row['repo_id']]+=1
    result=[dict(repo_id=repo,repo_name=names[repo],stars=count,
                 previous_stars=previous[repo] if comparison else None,
                 momentum=count-previous[repo] if comparison else None) for repo,count in current.items()]
    return sorted(result,key=lambda r:(-r['momentum'],-r['stars'],r['repo_id'])
                  if comparison and sort=='momentum' else (-r['stars'],r['repo_id']))[:limit]


def reference_repository(rows,start,end,include_bots):
    states={};opens={};merges={};activity=Counter();people={}
    hourly=end-start<=timedelta(hours=48)
    for row in sorted(rows,key=lambda r:(r['occurred_at'],r['ingest_seq'])):
        kind,action,when,pr=row['event_type'],row['action'],row['occurred_at'],row['pr_number']
        if kind=='PullRequestEvent':
            if action in ('opened','reopened','closed','merged'):states[pr]=row
            if action=='opened':opens.setdefault(pr,when)
            if action=='merged':merges.setdefault(pr,when)
        if not start<=when<end:continue
        bucket=when.replace(minute=0,second=0,microsecond=0)
        if not hourly:bucket=bucket.replace(hour=0)
        activity[(bucket.isoformat(),kind)]+=1
        contribution=kind=='PushEvent' or (kind in ('PullRequestEvent','IssuesEvent') and action=='opened') or (
            kind in ('PullRequestReviewEvent','IssueCommentEvent','PullRequestReviewCommentEvent') and action=='created')
        if not contribution or (not include_bots and row['actor_login'].lower().endswith('[bot]')):continue
        person=people.setdefault(row['actor_id'],dict(actor_id=row['actor_id'],contributions=0,pushes=0,pull_requests=0,issues=0,reviews=0,comments=0))
        person['contributions']+=1
        field={'PushEvent':'pushes','PullRequestEvent':'pull_requests','IssuesEvent':'issues',
               'PullRequestReviewEvent':'reviews','IssueCommentEvent':'comments','PullRequestReviewCommentEvent':'comments'}[kind]
        person[field]+=1
    selected={pr:when for pr,when in merges.items() if start<=when<end}
    durations=[(when-opens[pr]).total_seconds() for pr,when in selected.items() if pr in opens and when>=opens[pr]]
    stats=dict(merged_prs=len(selected),paired_prs=len(durations),coverage=len(durations)/len(selected) if selected else None,
               median_seconds=statistics.median(durations) if durations else None,
               mean_seconds=statistics.mean(durations) if durations else None,
               p90_seconds=percentile(durations,.9) if durations else None)
    observed=sorted((row for row in states.values() if row['action'] in ('opened','reopened')),
                    key=lambda r:(-r['occurred_at'].timestamp(),r['pr_number']))
    return {'activity_counts':activity,'open_numbers':[r['pr_number'] for r in observed],
            'merge_stats':stats,'contributors':sorted(people.values(),key=lambda r:(-r['contributions'],r['actor_id']))[:10]}


def checked_get(client,path,params):
    response=client.get(path,params=params);response.raise_for_status();return response.json()


def verify_snapshot(client,rows,raw_count):
    meta=checked_get(client,'/api/meta',{})
    groups=defaultdict(list)
    for row in rows:groups[row['repo_id']].append(row)
    assert meta['unique_event_count']==len(rows)==137302
    assert meta['repository_count']==len(groups)==500
    assert raw_count==138676
    assert timestamp(meta['watermark'])==max(r['occurred_at'] for r in rows)
    start=timestamp(meta['coverage_start']);end=timestamp(meta['coverage_end'])
    ranges=[(start,end),(end-timedelta(days=7),end),(end-timedelta(hours=1),end)]
    for lower,upper in ranges:
        comparison=lower-(upper-lower)>=start
        for sort in ('momentum','stars'):
            actual=checked_get(client,'/api/trending',dict(start=lower.isoformat(),end=upper.isoformat(),sort=sort,limit=50))
            assert actual['repositories']==reference_trends(rows,lower,upper,comparison,sort)
    selected_repos=sorted(groups,key=lambda repo:len(groups[repo]),reverse=True)[:3]
    checks=0
    for repo,events in groups.items():
        for lower,upper,bots in [(start,end,False)]+([(ranges[1][0],end,True),(ranges[2][0],end,False)] if repo in selected_repos else []):
            params=dict(start=lower.isoformat(),end=upper.isoformat(),include_bots=str(bots).lower(),pr_limit=50)
            report=checked_get(client,f'/api/repos/{repo}',params)
            reference=reference_repository(events,lower,upper,bots)
            counts={(bucket,series['type']):count for series in report['activity']['series']
                    for bucket,count in zip(report['activity']['buckets'],series['counts']) if count}
            assert counts==reference['activity_counts'],('activity',repo)
            assert report['open_prs']['total']==len(reference['open_numbers']),('PR total',repo)
            numbers=[p['number'] for p in report['open_prs']['items']]
            for offset in range(50,len(reference['open_numbers']),50):
                page=checked_get(client,f'/api/repos/{repo}',dict(params,pr_offset=offset))
                numbers.extend(p['number'] for p in page['open_prs']['items'])
            assert numbers==reference['open_numbers'],('PR states',repo)
            for key,value in reference['merge_stats'].items():
                actual=report['merge_stats'][key]
                assert actual==value if value is None else math.isclose(actual,value,rel_tol=1e-10,abs_tol=1e-8),('merge',repo,key)
            contributors=[{key:person[key] for key in reference['contributors'][0]} for person in report['contributors']] if reference['contributors'] else report['contributors']
            assert contributors==reference['contributors'],('contributors',repo)
            checks+=1
    totals=Counter(row['event_type'] for row in rows)
    global_stats=[reference_repository(events,start,end,True)['merge_stats'] for events in groups.values()]
    return {'raw_rows':raw_count,'unique_events':len(rows),'duplicate_rows':raw_count-len(rows),
            'repositories':len(groups),'repository_reports_verified':checks,'trend_reports_verified':6,
            'event_types':dict(totals),'merged_prs':sum(s['merged_prs'] for s in global_stats),
            'paired_merged_prs':sum(s['paired_prs'] for s in global_stats)}


def timed_get(client,path,params):
    began=time.perf_counter();checked_get(client,path,params);return (time.perf_counter()-began)*1000


def measure(database,snapshot,samples,writes):
    rows,raw_count=read_reference(snapshot)
    grouped=Counter(r['repo_id'] for r in rows)
    busiest=grouped.most_common(1)[0][0]
    end=max(r['occurred_at'] for r in rows).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    lower=min(r['occurred_at'] for r in rows).replace(hour=0,minute=0,second=0,microsecond=0)
    seven=end-timedelta(days=7)
    workloads={
        'trending_7d':('/api/trending',dict(start=seven.isoformat(),end=end.isoformat())),
        'trending_1h':('/api/trending',dict(start=(end-timedelta(hours=1)).isoformat(),end=end.isoformat())),
        'trending_month':('/api/trending',dict(start=lower.isoformat(),end=end.isoformat())),
        'repository_7d':(f'/api/repos/{busiest}',dict(start=seven.isoformat(),end=end.isoformat())),
        'repository_month':(f'/api/repos/{busiest}',dict(start=lower.isoformat(),end=end.isoformat()))}
    with live_server(database) as client:
        latency={}
        for name,(path,params) in workloads.items():
            first=timed_get(client,path,params)
            latency[name]={'first_request_ms':first,'warm':latency_summary([timed_get(client,path,params) for _ in range(samples)])}
        verified=verify_snapshot(client,rows,raw_count)
        stop=threading.Event();ready=threading.Event();reads=defaultdict(list);errors=[]
        def reader():
            try:
                with httpx.Client(base_url=str(client.base_url),timeout=30) as read_client:
                    ready.set()
                    while not stop.is_set():
                        for name in ('trending_7d','repository_7d'):
                            path,params=workloads[name];reads[name].append(timed_get(read_client,path,params))
            except Exception as error:errors.append(repr(error));ready.set()
        thread=threading.Thread(target=reader);thread.start();ready.wait(5)
        write_times=[];began=time.perf_counter()
        try:
            for i in range(writes):
                event={'id':f'benchmark-{i}','type':'WatchEvent','created_at':(end-timedelta(hours=1)).isoformat(),
                       'repo':{'id':900000000001,'name':'benchmark/disposable'},'actor':{'id':900000000002,'login':'benchmark'},'payload':{'action':'started'}}
                tick=time.perf_counter();response=client.post('/api/events',json=event)
                assert response.status_code==201,response.text
                write_times.append((time.perf_counter()-tick)*1000)
            elapsed=time.perf_counter()-began
        finally:
            stop.set();thread.join(timeout=30)
        assert not thread.is_alive() and not errors,errors
        assert client.post('/api/events',json=event).status_code==200
        meta=checked_get(client,'/api/meta',{})
        assert meta['unique_event_count']==len(rows)+writes
        ingestion={'events':writes,'elapsed_seconds':elapsed,'events_per_second':writes/elapsed,
                   'write_latency':latency_summary(write_times),'concurrent_reads':{name:latency_summary(values) for name,values in reads.items()},
                   'duplicate_replay_verified':True,'reader_threads':1,'writer_threads':1,'commits':'one event per HTTP request'}
    return {'independent_verification':verified,'http_latency':latency,'http_ingestion':ingestion}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path('data/events.duckdb'))
    parser.add_argument('--snapshot',type=Path,default=Path('data/events.jsonl.gz'))
    parser.add_argument('--output',type=Path,default=Path('docs/final-benchmark.json'))
    parser.add_argument('--samples',type=int,default=30)
    parser.add_argument('--writes',type=int,default=1000)
    args=parser.parse_args()
    if args.samples<1 or args.writes<1:parser.error('Samples and writes must be positive.')
    wal=Path(str(args.db)+'.wal')
    if wal.exists() and wal.stat().st_size:parser.error('Stop writers and checkpoint the source DB before copying it.')
    with tempfile.TemporaryDirectory(prefix='github-benchmark-') as temporary:
        copy=Path(temporary)/'events.duckdb';shutil.copy2(args.db,copy)
        result=measure(copy,args.snapshot,args.samples,args.writes)
    result.update(timestamp_utc=datetime.now(timezone.utc).isoformat(),environment={
        'os':platform.platform(),'architecture':platform.machine(),'python':platform.python_version(),
        'duckdb_threads':2,'source_database_bytes':args.db.stat().st_size,
        'snapshot_gzip_bytes':args.snapshot.stat().st_size},limitations=[
        'Local loopback HTTP, a single API process, two DuckDB threads; not a production load test.',
        'First request is per workload in this process; operating-system caches were not flushed.',
        'One concurrent reader alternates trends and full repository reports; one writer sends individual events.',
        'Event-time snapshot rates estimate activity, not network arrival rate or all GitHub traffic.',
        'Source DB is copied while no writers are running and no pending WAL is present.'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':str(args.output),'verified':result['independent_verification'],
                      'ingestion_events_per_second':result['http_ingestion']['events_per_second']},indent=2))


if __name__=='__main__':main()
