"""Stream and validate the snapshot; apply it atomically using shared persistence."""
import argparse
import csv
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import time

from app.domain import EventValidationError, EventConflictError, normalize_event
from app.store import EVENT_COLUMNS, Store, event_values


def import_snapshot(store: Store, path: str | Path):
    with tempfile.TemporaryDirectory(prefix='github-import-') as temporary:
        staged=Path(temporary)/'events.csv'
        with gzip.open(path,'rt',encoding='utf-8') as source,staged.open('w',newline='',encoding='utf-8') as output:
            writer=csv.writer(output);writer.writerow(EVENT_COLUMNS)
            received=datetime.now(timezone.utc)
            for line_number,line in enumerate(source,1):
                try:
                    event=normalize_event(json.loads(line))
                except (json.JSONDecodeError,EventValidationError) as error:
                    raise EventValidationError('snapshot',f'Invalid snapshot line {line_number}: {error}') from error
                writer.writerow(event_values(event,line_number,received))
        try:
            return store.ingest_csv(staged)
        except EventConflictError as error:
            lines=', '.join(map(str,error.source_lines))
            raise EventConflictError(f'Snapshot line(s) {lines}: {error}',error.source_lines) from error


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path',required=True,type=Path)
    parser.add_argument('--db',default=Path('data/events.duckdb'),type=Path)
    args=parser.parse_args();store=Store(args.db);started=time.perf_counter()
    try:
        result=import_snapshot(store,args.path)
        print(json.dumps({'read':result.inserted+result.duplicates,'inserted':result.inserted,
                          'duplicates':result.duplicates,'revision':result.revision,
                          'seconds':round(time.perf_counter()-started,3)}))
    finally:store.close()


if __name__=='__main__':main()
