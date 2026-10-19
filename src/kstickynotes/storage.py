from dataclasses import dataclass
from pathlib import Path
import os
import sqlite3


@dataclass(frozen=True)
class Note:
    id: int
    title: str
    body: str


def xdg_path(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def data_directory() -> Path:
    return xdg_path("XDG_DATA_HOME", ".local/share") / "kstickynotes"


def config_file() -> Path:
    return xdg_path("XDG_CONFIG_HOME", ".config") / "kstickynotes" / "settings.ini"


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=1)
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA synchronous=FULL")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("数据库版本比此应用新，请使用较新版本打开。")
            with self.db:
                self.db.execute("""CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                self.db.execute("PRAGMA user_version=1")
        except Exception:
            self.db.close()
            raise

    def notes(self) -> list[Note]:
        return [Note(*row) for row in self.db.execute("SELECT id,title,body FROM notes ORDER BY id")]

    def note(self, note_id: int) -> Note | None:
        row = self.db.execute("SELECT id,title,body FROM notes WHERE id=?", (note_id,)).fetchone()
        return Note(*row) if row else None

    def create(self, title: str = "新便签") -> Note:
        with self.db:
            cursor = self.db.execute("INSERT INTO notes(title) VALUES (?)", (title,))
        return Note(cursor.lastrowid, title, "")

    def save(self, changes: dict[int, str]):
        with self.db:
            for note_id, body in changes.items():
                cursor = self.db.execute(
                    "UPDATE notes SET body=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (body, note_id))
                if cursor.rowcount != 1:
                    raise RuntimeError(f"便签 {note_id} 不存在，修改尚未保存。")

    def rename(self, note_id: int, title: str):
        with self.db:
            self.db.execute("UPDATE notes SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (title, note_id))

    def delete(self, note_id: int):
        with self.db:
            self.db.execute("DELETE FROM notes WHERE id=?", (note_id,))

    def close(self):
        self.db.close()
