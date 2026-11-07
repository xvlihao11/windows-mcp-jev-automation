"""Read-only agent change detector. No writes to agent DB, clipboard or DingTalk."""
import argparse
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(os.environ.get('DAILY_AGENT_DB', str(Path.home()/'asphalt-agent/data/app.db')))
DEFAULT_STATE = Path(__file__).parent / 'agent-watch-state.json'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot(db, include_library=True):
    result = {}
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        for row in conn.execute('SELECT id,date,author,category,narrative,polished,blocks,updated_at FROM daily'):
            r = dict(row)
            payload = {k: r.get(k) for k in ('date', 'author', 'category', 'narrative', 'polished', 'blocks')}
            result['daily:' + str(r['id'])] = {'source': 'daily', 'id': str(r['id']),
                'date': r['date'], 'author': r['author'], 'category': r['category'], 'updated_at': r['updated_at'],
                'sha256': fingerprint(payload), 'has_content': bool(r['polished'] or r['blocks'])}
        library_rows = conn.execute("SELECT id,title,author,category,text,filepath,fmt,uploaded_at FROM library WHERE doc_type='report'") if include_library else []
        for row in library_rows:
            r = dict(row)
            payload = {k: r.get(k) for k in ('title', 'author', 'category', 'text', 'filepath', 'fmt')}
            result['library:' + str(r['id'])] = {'source': 'library', 'id': str(r['id']),
                'title': r['title'], 'author': r['author'], 'uploaded_at': r['uploaded_at'],
                'fmt': r['fmt'], 'filepath': r['filepath'],
                'preview_url': 'http://127.0.0.1:5000/?report_id=' + str(r['id']),
                'sha256': fingerprint(payload), 'has_content': bool(r['text'] or r['filepath'])}
    return result


def scan(db, state_path, include_library=True):
    current = snapshot(db, include_library=include_library)
    now = datetime.now(timezone.utc).isoformat()
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['db'] != str(db.resolve()):
            raise ValueError('Source database changed; explicit new baseline required')
    else:
        state = {'schema_version': 1, 'db': str(db.resolve()), 'baseline_at': now,
                 'seen': current, 'pending': {}, 'completed': {}}
        save(state_path, state)
        return {'status': 'BASELINED', 'records': len(current), 'pending': []}
    for key, item in current.items():
        previous = state['seen'].get(key)
        revision = ':' + fingerprint(item.get('updated_at')) if item['source'] == 'daily' else ''
        version = key + ':' + item['sha256'] + revision
        changed = not previous or previous['sha256'] != item['sha256'] or (item['source'] == 'daily' and previous.get('updated_at') != item.get('updated_at'))
        if changed and version not in state['completed']:
            state['pending'][version] = dict(item, version_key=version, detected_at=now,
                                            change='new' if not previous else 'updated')
    # Deleted/revised pending versions are no longer actionable.
    state['pending'] = {k: v for k, v in state['pending'].items()
                        if v['source'] + ':' + v['id'] in current
                        and current[v['source'] + ':' + v['id']]['sha256'] == v['sha256']
                        and (v['source'] != 'daily' or current[v['source'] + ':' + v['id']].get('updated_at') == v.get('updated_at'))}
    state['seen'] = current
    state['checked_at'] = now
    save(state_path, state)
    return {'status': 'CHANGED' if state['pending'] else 'NO_CHANGE',
            'pending': list(state['pending'].values())}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.05)
    finally:
        if tmp.exists():
            tmp.unlink()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, default=DEFAULT_DB)
    p.add_argument('--state', type=Path, default=DEFAULT_STATE)
    a = p.parse_args()
    try:
        print(json.dumps(scan(a.db, a.state), ensure_ascii=False))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({'status': 'ERROR', 'error_type': type(exc).__name__}))
        raise SystemExit(1)
