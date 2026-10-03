"""Exact immutable Thaliris Git blobs retained for adapter migration tests."""
from pathlib import Path
import hashlib
import json

def historical_blob(reference: str, *, text: bool = False):
    base = Path(__file__).parents[1] / 'fixtures/history'
    item = json.loads((base / 'provenance.json').read_text(encoding='utf-8'))[reference]
    raw = (base / 'blobs' / item['sha256']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == item['sha256']
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == item['git_blob']
    return raw.decode('utf-8') if text else raw
