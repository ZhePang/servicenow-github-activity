"""DuckDB ownership, schema, and transactions."""
from pathlib import Path
from contextlib import contextmanager
import threading
from datetime import datetime, timezone

import duckdb
from app.domain import EventConflictError, IngestResult, NormalizedEvent

SCHEMA_VERSION = 1
EVENT_COLUMNS = ['event_id','repo_id','repo_name','actor_id','actor_login','is_bot','event_type',
                 'action','occurred_at','received_at','ingest_seq','pr_number','content_hash','raw_json']
CSV_TYPES = dict(zip(EVENT_COLUMNS,['VARCHAR','BIGINT','VARCHAR','BIGINT','VARCHAR','BOOLEAN',
                    'VARCHAR','VARCHAR','TIMESTAMPTZ','TIMESTAMPTZ','BIGINT','INTEGER','VARCHAR','JSON']))


def event_values(event: NormalizedEvent, sequence: int, received: datetime):
    return [event.event_id,event.repo_id,event.repo_name,event.actor_id,event.actor_login,event.is_bot,
            event.event_type,event.action,event.occurred_at,received,sequence,event.pr_number,
            event.content_hash,event.raw_json]

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
 event_id VARCHAR PRIMARY KEY, repo_id BIGINT NOT NULL, repo_name VARCHAR NOT NULL,
 actor_id BIGINT NOT NULL, actor_login VARCHAR NOT NULL, is_bot BOOLEAN NOT NULL,
 event_type VARCHAR NOT NULL, action VARCHAR, occurred_at TIMESTAMPTZ NOT NULL,
 received_at TIMESTAMPTZ NOT NULL, ingest_seq BIGINT NOT NULL, pr_number INTEGER,
 content_hash VARCHAR NOT NULL, raw_json JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
 revision BIGINT NOT NULL, unique_event_count BIGINT NOT NULL,
 min_event_time TIMESTAMPTZ, max_event_time TIMESTAMPTZ, next_ingest_seq BIGINT NOT NULL
);
INSERT INTO metadata VALUES (1,1,0,0,NULL,NULL,1) ON CONFLICT DO NOTHING;
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.write_lock = threading.Lock()
        self.connection = duckdb.connect(':memory:', config={'threads':2})
        escaped = str(self.path).replace("'", "''")
        self.connection.execute(f"ATTACH '{escaped}' AS storage (ROW_GROUP_SIZE 16384)")
        self.connection.execute('USE storage')
        self.connection.execute("SET TimeZone='UTC'")
        self.connection.execute(SCHEMA)
        if self.metadata(self.connection)['schema_version'] != SCHEMA_VERSION:
            self.connection.close()
            raise RuntimeError('Unsupported database schema version.')

    @contextmanager
    def read(self):
        cursor = self.connection.cursor()
        try:
            cursor.execute('USE storage')
            cursor.execute("SET TimeZone='UTC'")
            cursor.execute('BEGIN TRANSACTION')
            yield cursor
            cursor.execute('COMMIT')
        except Exception:
            cursor.execute('ROLLBACK')
            raise
        finally:
            cursor.close()

    @staticmethod
    def metadata(cursor):
        result = cursor.execute('SELECT * EXCLUDE(singleton) FROM metadata WHERE singleton=1')
        names = [d[0] for d in result.description]
        return dict(zip(names,result.fetchone()))

    def close(self):
        self.connection.close()

    @contextmanager
    def _write(self):
        with self.write_lock:
            with self.read() as cursor:
                yield cursor

    def ingest(self, events: list[NormalizedEvent]) -> IngestResult:
        with self._write() as cursor:
            cursor.execute('CREATE TEMP TABLE incoming AS SELECT * FROM events WHERE false')
            if events:
                now = datetime.now(timezone.utc)
                cursor.executemany('INSERT INTO incoming VALUES ('+','.join(['?']*14)+')',
                                   [event_values(event,i,now) for i,event in enumerate(events,1)])
            return self._persist(cursor)

    def ingest_csv(self, path: str | Path) -> IngestResult:
        with self._write() as cursor:
            cursor.execute('CREATE TEMP TABLE incoming AS SELECT * FROM read_csv(?, header=true, columns=?, maximum_line_size=16777216)',
                           [str(path),CSV_TYPES])
            result = self._persist(cursor)
        self.connection.execute('CHECKPOINT')
        return result

    def _persist(self, cursor) -> IngestResult:
        metadata = self.metadata(cursor)
        count = cursor.execute('SELECT count(*) FROM incoming').fetchone()[0]
        conflict = cursor.execute('SELECT event_id FROM incoming GROUP BY event_id HAVING count(DISTINCT content_hash)>1 LIMIT 1').fetchone()
        if conflict:
            lines=[row[0] for row in cursor.execute('SELECT min(ingest_seq) FROM incoming WHERE event_id=? GROUP BY content_hash ORDER BY 1',[conflict[0]]).fetchall()]
            raise EventConflictError('Conflicting event ID: '+conflict[0],lines)
        cursor.execute('CREATE TEMP TABLE candidates AS SELECT * FROM incoming QUALIFY row_number() OVER (PARTITION BY event_id ORDER BY ingest_seq)=1')
        conflict = cursor.execute('SELECT i.event_id,i.ingest_seq FROM candidates i JOIN events e USING(event_id) WHERE i.content_hash<>e.content_hash LIMIT 1').fetchone()
        if conflict: raise EventConflictError('Conflicting event ID: '+conflict[0],[conflict[1]])
        cursor.execute('CREATE TEMP TABLE accepted AS SELECT i.* FROM candidates i ANTI JOIN events e USING(event_id)')
        inserted, earliest, latest = cursor.execute('SELECT count(*),min(occurred_at),max(occurred_at) FROM accepted').fetchone()
        if inserted:
            base = metadata['next_ingest_seq'] - 1
            cursor.execute('INSERT INTO events SELECT * REPLACE(ingest_seq+? AS ingest_seq) FROM accepted ORDER BY repo_id,occurred_at,ingest_seq',[base])
            cursor.execute('UPDATE metadata SET revision=revision+1,unique_event_count=unique_event_count+?,min_event_time=least(min_event_time,?),max_event_time=greatest(max_event_time,?),next_ingest_seq=next_ingest_seq+? WHERE singleton=1',
                           [inserted,earliest,latest,count])
        return IngestResult(inserted,count-inserted,metadata['revision']+(1 if inserted else 0))
