"""Verify the installer and on-demand service activation without user data."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time


def main():
    if '--inside-private-bus' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='kstickynotes-activation-', ignore_cleanup_errors=True) as temp:
            env = dict(os.environ, XDG_DATA_HOME=temp+'/data', XDG_CONFIG_HOME=temp+'/config', XDG_CACHE_HOME=temp+'/cache',
                       QT_QPA_PLATFORM='offscreen')
            return subprocess.run(['dbus-run-session', '--', sys.executable, __file__,
                                   '--inside-private-bus'], env=env).returncode
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root/'install-widget.py')], check=True)
    app = QCoreApplication([sys.argv[0]])
    bus = QDBusConnection.sessionBus()
    interface = QDBusInterface('org.kstickynotes.Service', '/Notes', 'org.kstickynotes.Notes1', bus)
    try:
        response = interface.call('Request', '{"op":"snapshot"}')
        payload = json.loads(response.arguments()[0])
        assert payload['ok'], payload
        note = payload['snapshot']['notes'][0]
        assert json.loads(interface.call('Request', json.dumps({'op':'edit','id':note['id'],
                            'body':'按需启动与退出保存', 'expected':''})).arguments()[0])['ok']
        # Stop must flush the final pending edit before leaving the bus.
        assert json.loads(interface.call('Request', '{"op":"stop"}').arguments()[0])['ok']
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if not bus.interface().isServiceRegistered('org.kstickynotes.Service').value():
                break
            time.sleep(.05)
        else:
            raise AssertionError('服务未正常退出')
        path = Path(os.environ['XDG_DATA_HOME'])/'kstickynotes/notes.sqlite3'
        with sqlite3.connect(path) as database:
            assert database.execute('SELECT body FROM notes').fetchone()[0] == '按需启动与退出保存'
            assert database.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        print('安装、D-Bus 按需启动、退出提交：通过')
    finally:
        if bus.interface().isServiceRegistered('org.kstickynotes.Service').value():
            interface.call('Request', '{"op":"stop"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
