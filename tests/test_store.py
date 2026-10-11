from datetime import datetime, timezone

from app.store import Store


def test_schema_metadata_and_reopening(tmp_path):
    path = tmp_path/'events.duckdb'
    store = Store(path)
    with store.read() as connection:
        metadata = store.metadata(connection)
        assert metadata['revision'] == 0 and metadata['unique_event_count'] == 0
        assert metadata['min_event_time'] is None
        columns = {r[1] for r in connection.execute("PRAGMA table_info('events')").fetchall()}
        assert {'raw_json','content_hash','ingest_seq','received_at','pr_number'} <= columns
    store.close()
    reopened = Store(path)
    with reopened.read() as connection:
        assert reopened.metadata(connection)['schema_version'] == 1
    reopened.close()


def test_each_reader_uses_utc_and_fetches_aware_timestamps(tmp_path):
    store = Store(tmp_path/'events.duckdb')
    with store.read() as connection:
        assert connection.execute("SELECT current_setting('TimeZone')").fetchone()[0] == 'UTC'
        value = connection.execute("SELECT TIMESTAMPTZ '2026-08-01 14:00:00+02'").fetchone()[0]
        assert value == datetime(2026,8,1,12,tzinfo=timezone.utc)
        assert value.utcoffset().total_seconds() == 0
    store.close()
