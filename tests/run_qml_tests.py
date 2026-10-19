"""Run native Qt Quick interaction tests on a private session bus and database."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def main():
    if '--inside-private-bus' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='kstickynotes-qml-', ignore_cleanup_errors=True) as temp:
            env = dict(os.environ, XDG_DATA_HOME=temp+'/data', XDG_CONFIG_HOME=temp+'/config', XDG_CACHE_HOME=temp+'/cache',
                       QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
            return subprocess.run(['dbus-run-session', '--', sys.executable, __file__,
                                   '--inside-private-bus'], env=env).returncode
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    root = Path(__file__).resolve().parents[1]
    tool = shutil.which('qmltestrunner6')
    if not tool:
        bins = subprocess.check_output(['qtpaths6', '--query', 'QT_INSTALL_BINS'], text=True).strip()
        tool = str(Path(bins) / 'qmltestrunner')
    app = QCoreApplication([sys.argv[0]])
    shutil.copytree(root/'plasmoid', Path(os.environ['XDG_DATA_HOME'])/'plasma/plasmoids/org.marco.kstickynotes')
    env = dict(os.environ, PYTHONPATH=str(root/'src'))
    with tempfile.TemporaryFile(mode='w+') as log:
        service = subprocess.Popen([sys.executable, '-m', 'kstickynotes.service'], env=env, stdout=log, stderr=log)
        try:
            bus = QDBusConnection.sessionBus()
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                if bus.interface().isServiceRegistered('org.kstickynotes.Service').value():
                    break
                if service.poll() is not None:
                    raise RuntimeError('保存服务提前退出')
                time.sleep(.05)
            else:
                raise RuntimeError('保存服务启动超时')
            interface = QDBusInterface('org.kstickynotes.Service', '/Notes', 'org.kstickynotes.Notes1', bus)
            response = interface.call('Request', '{"op":"snapshot"}')
            if not response.arguments() or '"ok": true' not in str(response.arguments()[0]):
                raise RuntimeError(str(response.arguments()))
            return subprocess.run([tool, '-input', str(root/'tests/qml'), '-o', '-,txt'], env=env, timeout=40).returncode
        finally:
            service.terminate()
            try:
                service.wait(timeout=5)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait()
            log.seek(0)
            details = log.read()
            if details:
                print(details, file=sys.stderr)


if __name__ == '__main__':
    raise SystemExit(main())
