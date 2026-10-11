"""Copy complete raw Codex session logs without filtering or rewriting them."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def export_logs(destination, sources):
    destination=Path(destination)
    # Read every source before changing an existing export.
    captured=[(Path(source).resolve(),Path(source).read_bytes()) for source in sources]
    destination.mkdir(parents=True,exist_ok=True)
    sessions=[]
    for source,data in captured:
        header=json.loads(data.splitlines()[0]);session_id=header['payload']['id']
        name=session_id+'.jsonl'
        (destination/name).write_bytes(data)
        sessions.append(dict(session_id=session_id,file=name,source_path=str(source),
                             bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    manifest=dict(captured_at_utc=datetime.now(timezone.utc).isoformat(),sessions=sessions,
                  note='Unedited raw JSONL copies. Refresh after the live session finishes to include its final messages.')
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,default=Path('ai-logs'))
    parser.add_argument('--source',type=Path,action='append',help='Repeat for every session. Without this, use the existing manifest source paths.')
    args=parser.parse_args()
    sources=args.source
    if not sources:
        manifest=args.destination/'manifest.json'
        if not manifest.exists():parser.error('Provide --source for every session on the first export.')
        sources=[record['source_path'] for record in json.loads(manifest.read_text())['sessions']]
    result=export_logs(args.destination,sources)
    print(f"Exported {len(result['sessions'])} unedited sessions to {args.destination}.")


if __name__=='__main__':main()
