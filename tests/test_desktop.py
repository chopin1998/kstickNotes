import subprocess
from pathlib import Path
from kstickynotes import desktop


def test_kde_matching_runtime_discovers_plugins(monkeypatch, tmp_path):
    plugins = tmp_path / 'plugins'
    (plugins / 'platformthemes').mkdir(parents=True)
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    monkeypatch.delenv('QT_QPA_PLATFORMTHEME', raising=False)
    monkeypatch.setattr(desktop.shutil, 'which', lambda _: '/usr/bin/qtpaths6')
    monkeypatch.setattr(desktop, 'qVersion', lambda: '6.10.2')
    monkeypatch.setattr(desktop.subprocess, 'run', lambda cmd, **kwargs:
                        subprocess.CompletedProcess(cmd, 0, '6.10.1' if cmd[-1] == '--qt-version' else str(plugins)))
    paths = []
    monkeypatch.setattr(desktop.QCoreApplication, 'addLibraryPath', paths.append)
    desktop.configure_desktop()
    assert paths == [str(plugins)]
    assert desktop.os.environ['QT_QPA_PLATFORMTHEME'] == 'kde'


def test_kde_mismatch_does_not_mix_plugins(monkeypatch):
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    monkeypatch.delenv('QT_QPA_PLATFORMTHEME', raising=False)
    monkeypatch.setattr(desktop.shutil, 'which', lambda _: '/usr/bin/qtpaths6')
    monkeypatch.setattr(desktop, 'qVersion', lambda: '6.12.0')
    monkeypatch.setattr(desktop.subprocess, 'run', lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, '6.10.2'))
    desktop.configure_desktop()
    assert 'QT_QPA_PLATFORMTHEME' not in desktop.os.environ
