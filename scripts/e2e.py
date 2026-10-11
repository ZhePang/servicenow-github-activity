"""Integration checks against an actual local Uvicorn process and DuckDB file."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT=Path(__file__).resolve().parent.parent


@contextmanager
def live_server(database):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    environment=dict(os.environ,GHT_DB_PATH=str(database))
    process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--log-level','warning'],
                             cwd=ROOT,env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=10) as client:
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError(process.stdout.read())
                try:
                    if client.get('/api/health').status_code==200:break
                except httpx.ConnectError:pass
                time.sleep(.1)
            else:raise RuntimeError('Server did not start.')
            yield client
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()


def run():
    with tempfile.TemporaryDirectory(prefix='github-e2e-') as temporary:
        with live_server(Path(temporary)/'events.duckdb') as client:
            event={'id':'e2e-1','type':'WatchEvent','created_at':'2026-08-01T12:00:00Z',
                   'repo':{'id':10,'name':'owner/project'},'actor':{'id':20,'login':'alice'},'payload':{'action':'started'}}
            assert client.post('/api/events',json=event).status_code==201
            assert client.post('/api/events',json=event).json()['status']=='duplicate'
            assert client.post('/api/events',json={}).status_code==422
            changed=dict(event,type='DifferentEvent')
            assert client.post('/api/events',json=changed).status_code==409
            params={'start':'2026-08-01T00:00:00Z','end':'2026-08-02T00:00:00Z'}
            meta=client.get('/api/meta').json();assert meta['unique_event_count']==1
            trends=client.get('/api/trending',params=params).json()
            assert trends['repositories'][0]['stars']==1 and not trends['comparison_available']
            detail=client.get('/api/repos/10',params=params).json()
            assert detail['repo_name']=='owner/project'
            assert sum(detail['activity']['series'][0]['counts'])==1
            fresh=dict(event,id='e2e-2')
            assert client.post('/api/events',json=fresh).status_code==201
            assert client.get('/api/trending',params=params).json()['repositories'][0]['stars']==2
            assert client.post('/api/events',json=fresh).status_code==200
            assert client.get('/api/trending',params=params).json()['repositories'][0]['stars']==2
    print('Real HTTP ingestion, analytics, and immediate visibility E2E passed.')


if __name__=='__main__':run()
