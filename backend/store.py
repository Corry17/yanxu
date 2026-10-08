"""SQLite 是本地权威状态；原件和历史版本不可覆盖。"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import uuid
from .domain import digest

ROOT = Path(__file__).resolve().parents[1]

def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix='item'):
    return prefix + '-' + uuid.uuid4().hex[:16]


def safe_path(root: Path, relative: str, exists=False):
    if not relative or '\\' in relative or '\x00' in relative or Path(relative).is_absolute():
        raise ValueError('非法相对路径')
    current = root.resolve()
    for part in relative.split('/'):
        if part in ('', '.', '..') or part.startswith('.'):
            raise ValueError('路径越界或隐藏文件')
        current = current / part
        if current.is_symlink():
            raise ValueError('禁止符号链接')
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('路径越界')
    if exists and not current.is_file():
        raise ValueError('文件不存在')
    return current


class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv('RESEARCH_DATA', ROOT / '.research')).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'research.sqlite3'
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS records (
              id TEXT, version INTEGER, project TEXT, kind TEXT, visibility TEXT,
              content TEXT, hash TEXT, created TEXT, PRIMARY KEY(id,version));
            CREATE INDEX IF NOT EXISTS record_project ON records(project,kind);
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(id UNINDEXED,project UNINDEXED,text);
            CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT, kind TEXT,
              visibility TEXT, payload TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, project TEXT, kind TEXT, payload TEXT, key TEXT UNIQUE,
              status TEXT, result TEXT, error TEXT, created TEXT, updated TEXT);
            CREATE TABLE IF NOT EXISTS approvals (
              id TEXT PRIMARY KEY, project TEXT, spec_id TEXT, spec_hash TEXT,
              payload TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS schedules (
              id TEXT PRIMARY KEY, project TEXT, kind TEXT, interval_seconds INTEGER,
              next_due TEXT, payload TEXT, enabled INTEGER);
            CREATE TABLE IF NOT EXISTS usage (
              id INTEGER PRIMARY KEY, project TEXT, created TEXT, reserved REAL,
              actual REAL, status TEXT);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, project, kind, payload, visibility='dev', db=None):
        if db is None:
            with self.connect() as conn:
                return self.event(project, kind, payload, visibility, conn)
        cursor = db.execute('INSERT INTO events(project,kind,visibility,payload,created) VALUES(?,?,?,?,?)',
                            (project, kind, visibility, json.dumps(payload, ensure_ascii=False), now()))
        return cursor.lastrowid

    def events(self, project, after=0, dev_only=False):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE project=? AND seq>? AND (?=0 OR visibility=?) ORDER BY seq LIMIT 500',
                              (project, after, int(dev_only), 'dev')).fetchall()
        return [dict(row) | {'payload': json.loads(row['payload'])} for row in rows]

    def put(self, kind, project, content, id=None, visibility='dev', expected=None):
        id = id or identifier(kind)
        for ref in content.get('refs', []):
            evidence = self.get(ref['id'], ref['version'], project)
            latest = self.get(ref['id'], project=project)
            if evidence['visibility'] == 'final' or latest['visibility'] == 'final':
                visibility = 'final'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prev = db.execute('SELECT * FROM records WHERE id=? ORDER BY version DESC LIMIT 1', (id,)).fetchone()
            if prev and (prev['project'] != project or prev['kind'] != kind):
                raise ValueError('记录所属项目或类型不匹配')
            if expected is not None and (prev['version'] if prev else 0) != expected:
                raise ValueError('记录已更新，请刷新后重试')
            if prev and prev['visibility'] == 'final':
                visibility = 'final'
            version = prev['version'] + 1 if prev else 1
            record = dict(id=id, version=version, project=project, kind=kind, visibility=visibility,
                          content=content, hash=digest(content), created=now())
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?)',
                       (id, version, project, kind, visibility, json.dumps(content, ensure_ascii=False), record['hash'], record['created']))
            db.execute('DELETE FROM search WHERE id=?', (id,))
            if visibility == 'dev' and kind not in ('remote', 'report'):
                db.execute('INSERT INTO search(id,project,text) VALUES(?,?,?)',
                           (id, project, json.dumps(content, ensure_ascii=False)))
            self.event(project, kind + '.saved', {'id': id, 'version': version, 'title': content.get('title', kind)}, visibility, db)
        return record

    def get(self, id, version=None, project=None):
        with self.connect() as db:
            row = db.execute('SELECT * FROM records WHERE id=? AND (? IS NULL OR version=?) ORDER BY version DESC LIMIT 1',
                             (id, version, version)).fetchone()
        if not row or (project is not None and row['project'] != project):
            raise ValueError('记录不存在')
        return dict(row) | {'content': json.loads(row['content'])}

    def list(self, project=None, kind=None, dev_only=False):
        with self.connect() as db:
            rows = db.execute('''SELECT r.* FROM records r JOIN
                (SELECT id,MAX(version) v FROM records GROUP BY id) latest
                ON r.id=latest.id AND r.version=latest.v
                WHERE (? IS NULL OR r.project=?) AND (? IS NULL OR r.kind=?)
                AND (?=0 OR r.visibility='dev') ORDER BY r.created DESC''',
                              (project, project, kind, kind, int(dev_only))).fetchall()
        return [dict(row) | {'content': json.loads(row['content'])} for row in rows]

    def asof(self, project, cutoff):
        with self.connect() as db:
            rows = db.execute('''SELECT r.* FROM records r JOIN
                (SELECT id, MAX(version) version FROM records WHERE project=? AND created<? GROUP BY id) latest
                ON r.id=latest.id AND r.version=latest.version ORDER BY r.created''', (project, cutoff)).fetchall()
        return [dict(row) | {'content': json.loads(row['content'])} for row in rows]

    def check_refs(self, project, refs, dev_only=False):
        for ref in refs:
            if hasattr(ref, 'model_dump'):
                ref = ref.model_dump()
            record = self.get(ref['id'], ref['version'], project)
            if dev_only and (record['visibility'] != 'dev' or self.get(ref['id'])['visibility'] != 'dev'):
                raise ValueError('测试证据及派生内容不可用于研究规划')
        return True

    def stale(self, record, visited=None):
        visited = set() if visited is None else visited
        if record['id'] in visited:
            return False
        visited.add(record['id'])
        for ref in record['content'].get('refs', []):
            latest = self.get(ref['id'])
            if latest['version'] != ref['version'] or self.stale(latest, visited):
                return True
        return False

    def save_blob(self, content: bytes, suffix: str):
        if not re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
            raise ValueError('非法扩展名')
        relative = 'blobs/' + hashlib.sha256(content).hexdigest() + suffix
        path = safe_path(self.root, relative)
        path.parent.mkdir(exist_ok=True)
        try:
            with path.open('xb') as output:
                output.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError('原件 hash 冲突')
        return relative

    def setting(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (key, json.dumps(value, ensure_ascii=False)))
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def enqueue(self, project, kind, payload, key=None):
        with self.connect() as db:
            id = identifier('job')
            key = key or id
            db.execute('INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (id, project, kind, json.dumps(payload), key, 'queued', None, None, now(), now()))
            row = db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone()
        return dict(row)

    def jobs(self, project):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM jobs WHERE project=? ORDER BY created DESC LIMIT 100', (project,))]

    def recover(self):
        # 只重放幂等任务；远端提交通过相同任务 ID 对账，绝不重新生成训练 ID。
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='queued',updated=? WHERE status='running' AND kind IN ('submit','sync','cancel','search','batch-submit','batch-cancel')", (now(),))
            db.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE status='running'",
                       ('本地服务中断，生成任务需人工确认后重新发起，防止重复收费或重复导出。', now()))

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (now(), row['id']))
                return dict(row) | {'payload': json.loads(row['payload'])}

    def finish(self, id, result=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,result=?,error=?,updated=? WHERE id=?',
                       ('failed' if error else 'done', json.dumps(result, ensure_ascii=False), error, now(), id))
