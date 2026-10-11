"""Submission logs must remain byte-for-byte copies of every source session."""
import hashlib
import json

from scripts.export_ai_logs import export_logs


def test_export_keeps_unedited_bytes_and_records_each_session(tmp_path):
    source=tmp_path/'source.jsonl'
    original=b'{"type":"session_meta","payload":{"id":"session-1"}}\n{"text":"hello \\u4e16\\u754c"}\n'
    source.write_bytes(original)
    target=tmp_path/'ai-logs'
    manifest=export_logs(target,[source])
    record=manifest['sessions'][0]
    assert (target/record['file']).read_bytes()==original
    assert record['sha256']==hashlib.sha256(original).hexdigest()
    assert record['source_path']==str(source.resolve())
    assert record['session_id']=='session-1'
    assert json.loads((target/'manifest.json').read_text())==manifest
    # Refresh follows continuing source logs without editing their contents.
    source.write_bytes(original+b'{"text":"later"}\n')
    refreshed=export_logs(target,[source])
    assert (target/refreshed['sessions'][0]['file']).read_bytes()==source.read_bytes()
