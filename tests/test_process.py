"""Exercise the real entry point, second launch, and normal signal shutdown."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


def test_second_process_and_sigterm(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_DATA_HOME=str(tmp_path / "data"),
               XDG_CONFIG_HOME=str(tmp_path / "config"))
    command = [sys.executable, "-m", "kstickynotes", "--tray"]
    log = tmp_path / "process.log"
    with log.open("w") as output:
        first = subprocess.Popen(command, env=env, stdout=output, stderr=output)
        try:
            db = tmp_path / "data/kstickynotes/notes.sqlite3"
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                assert first.poll() is None, log.read_text()
                if db.exists():
                    try:
                        with sqlite3.connect(db) as connection:
                            if connection.execute("SELECT count(*) FROM notes").fetchone()[0]:
                                break
                    except sqlite3.OperationalError:
                        pass
                time.sleep(.05)
            else:
                raise AssertionError(log.read_text())
            second = subprocess.run(command, env=env, capture_output=True, timeout=8)
            assert second.returncode == 0, second.stderr.decode()
            assert first.poll() is None
            first.terminate()
            assert first.wait(timeout=8) == 0, log.read_text()
            with sqlite3.connect(db) as connection:
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert (tmp_path / "config/kstickynotes/settings.ini").exists()
        finally:
            if first.poll() is None:
                first.kill()
                first.wait()
