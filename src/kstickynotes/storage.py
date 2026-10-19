from dataclasses import dataclass
from pathlib import Path
import json
import os
import sqlite3
import uuid
from .sync_model import canonical, heads, resolve, revision, validate


@dataclass(frozen=True)
class Note:
    id: int
    title: str
    body: str


def xdg_path(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, '')
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def data_directory() -> Path:
    return xdg_path('XDG_DATA_HOME', '.local/share') / 'kstickynotes'


def config_file() -> Path:
    return xdg_path('XDG_CONFIG_HOME', '.config') / 'kstickynotes' / 'settings.ini'


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=1)
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA synchronous=FULL')
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version > 2:
                raise RuntimeError('数据库版本比此应用新，请使用较新版本打开。')
            if version == 1:
                self.backup(path.parent / 'backups' / ('before-sync-' + uuid.uuid4().hex + '.sqlite3'))
            with self.db:
                self.db.execute('''CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
                self.db.execute('''CREATE TABLE IF NOT EXISTS sync_revisions (
                    revision TEXT PRIMARY KEY, note TEXT NOT NULL, record TEXT NOT NULL)''')
                self.db.execute('CREATE INDEX IF NOT EXISTS revisions_note ON sync_revisions(note)')
                self.db.execute('''CREATE TABLE IF NOT EXISTS sync_notes (
                    uuid TEXT PRIMARY KEY, note_id INTEGER UNIQUE REFERENCES notes(id) ON DELETE SET NULL)''')
                for note in self.notes():
                    if not self.db.execute('SELECT 1 FROM sync_notes WHERE note_id=?', (note.id,)).fetchone():
                        self._record(note.id, {'title': note.title, 'body': note.body, 'deleted': False})
                self.db.execute('PRAGMA user_version=2')
        except Exception:
            self.db.close()
            raise

    def backup(self, path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Precreate with owner-only permissions, including on permissive umasks.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with sqlite3.connect(path) as destination:
            self.db.backup(destination)

    def notes(self) -> list[Note]:
        return [Note(*r) for r in self.db.execute('SELECT id,title,body FROM notes ORDER BY id')]

    def note(self, note_id: int) -> Note | None:
        row = self.db.execute('SELECT id,title,body FROM notes WHERE id=?', (note_id,)).fetchone()
        return Note(*row) if row else None

    def _insert_revision(self, record):
        self.db.execute('INSERT OR IGNORE INTO sync_revisions VALUES (?,?,?)',
                        (record['id'], record['note'], canonical(record)))

    def _record(self, note_id, payload):
        row = self.db.execute('SELECT uuid FROM sync_notes WHERE note_id=?', (note_id,)).fetchone()
        uid = row[0] if row else uuid.uuid4().hex
        if row is None:
            self.db.execute('INSERT INTO sync_notes VALUES (?,?)', (uid, note_id))
        history = [json.loads(r[0]) for r in self.db.execute('SELECT record FROM sync_revisions WHERE note=?', (uid,))]
        self._insert_revision(revision(uid, [r['id'] for r in heads(history)], payload))

    def create(self, title: str = '新便签') -> Note:
        with self.db:
            cursor = self.db.execute('INSERT INTO notes(title) VALUES (?)', (title,))
            self._record(cursor.lastrowid, {'title': title, 'body': '', 'deleted': False})
        return Note(cursor.lastrowid, title, '')

    def save(self, changes: dict[int, str]):
        with self.db:
            for note_id, body in changes.items():
                note = self.note(note_id)
                if note is None:
                    raise RuntimeError(f'便签 {note_id} 不存在，修改尚未保存。')
                if body == note.body:
                    continue
                self.db.execute('UPDATE notes SET body=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (body, note_id))
                self._record(note_id, {'title': note.title, 'body': body, 'deleted': False})

    def rename(self, note_id: int, title: str):
        with self.db:
            note = self.note(note_id)
            if note is None:
                raise RuntimeError('便签不存在')
            if title != note.title:
                self.db.execute('UPDATE notes SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (title, note_id))
                self._record(note_id, {'title': title, 'body': note.body, 'deleted': False})

    def delete(self, note_id: int):
        with self.db:
            note = self.note(note_id)
            if note:
                self._record(note_id, {'title': note.title, 'body': note.body, 'deleted': True})
                self.db.execute('DELETE FROM notes WHERE id=?', (note_id,))

    def revisions(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT record FROM sync_revisions ORDER BY rowid')]

    def merge(self, incoming):
        before = self.revisions()
        ordered = validate(before + incoming)
        additions, conflicts = resolve(ordered)
        with self.db:
            for record in ordered + additions:
                self._insert_revision(record)
            grouped = {}
            for record in ordered + additions:
                grouped.setdefault(record['note'], []).append(record)
            for uid, history in grouped.items():
                leaves = heads(history)
                assert len(leaves) == 1
                payload = leaves[0]['payload']
                row = self.db.execute('SELECT note_id FROM sync_notes WHERE uuid=?', (uid,)).fetchone()
                note_id = row[0] if row else None
                if payload['deleted']:
                    if note_id is not None:
                        self.db.execute('DELETE FROM notes WHERE id=?', (note_id,))
                    self.db.execute('INSERT OR IGNORE INTO sync_notes VALUES (?,NULL)', (uid,))
                elif note_id is None:
                    cursor = self.db.execute('INSERT INTO notes(title,body) VALUES (?,?)', (payload['title'], payload['body']))
                    self.db.execute('INSERT INTO sync_notes VALUES (?,?) ON CONFLICT(uuid) DO UPDATE SET note_id=excluded.note_id', (uid, cursor.lastrowid))
                else:
                    note = self.note(note_id)
                    if (note.title, note.body) != (payload['title'], payload['body']):
                        self.db.execute('UPDATE notes SET title=?,body=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                                        (payload['title'], payload['body'], note_id))
        return conflicts

    def close(self):
        self.db.close()
