"""HTTP contracts and application lifecycle."""
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.domain import EventConflictError, EventValidationError, normalize_event, parse_timestamp, TimeRange
from app.store import Store
from app import queries
from typing import Literal

ROOT=Path(__file__).resolve().parent.parent
logger=logging.getLogger('github-trending')


def create_app(database: str | Path | None = None):
    @asynccontextmanager
    async def lifespan(application):
        application.state.store=Store(database or os.environ.get('GHT_DB_PATH',str(ROOT/'data/events.duckdb')))
        yield
        application.state.store.close()

    application=FastAPI(title='GitHub activity explorer',lifespan=lifespan)
    application.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')

    @application.get('/',include_in_schema=False)
    def dashboard():
        return FileResponse(ROOT/'web/index.html')

    @application.exception_handler(EventValidationError)
    async def validation_error(request,error):
        return JSONResponse(status_code=422,content={'detail':[{'field':error.field,'message':str(error)}]})

    @application.exception_handler(EventConflictError)
    async def conflict_error(request,error):
        return JSONResponse(status_code=409,content={'detail':str(error)})

    @application.exception_handler(Exception)
    async def unexpected_error(request,error):
        logger.error('Request failed',exc_info=error)
        return JSONResponse(status_code=500,content={'detail':'Storage operation failed. Please retry.'})

    @application.get('/api/health')
    def health(request: Request):
        with request.app.state.store.read() as cursor:
            cursor.execute('SELECT 1')
            metadata=Store.metadata(cursor)
        return {'status':'ok','schema_version':metadata['schema_version']}

    @application.post('/api/events')
    def receive_event(body: dict,request: Request):
        event=normalize_event(body)
        result=request.app.state.store.ingest([event])
        return JSONResponse(status_code=201 if result.inserted else 200,
                            content={'event_id':event.event_id,'status':'inserted' if result.inserted else 'duplicate','revision':result.revision})

    @application.get('/api/meta')
    def meta(request: Request):
        with request.app.state.store.read() as cursor:
            return queries.metadata(cursor)

    @application.get('/api/trending')
    def trends(request: Request,start: str,end: str,sort: Literal['momentum','stars']='momentum',
               limit: int=Query(20,ge=1,le=50),q: str=''):
        period=TimeRange(parse_timestamp(start,'start'),parse_timestamp(end,'end'))
        with request.app.state.store.read() as cursor:
            return queries.trending(cursor,period,sort,limit,q)

    @application.get('/api/repos/{repo_id}')
    def repository(request: Request,repo_id: int,start: str,end: str,include_bots: bool=False,
                   pr_offset: int=Query(0,ge=0),pr_limit: int=Query(25,ge=1,le=50)):
        period=TimeRange(parse_timestamp(start,'start'),parse_timestamp(end,'end'))
        with request.app.state.store.read() as cursor:
            report=queries.repository_report(cursor,repo_id,period,include_bots,pr_offset,pr_limit)
        if report is None:raise HTTPException(status_code=404,detail='Repository not found.')
        return report

    return application


app=create_app()
