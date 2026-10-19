#!/usr/bin/env python3
"""Install a user-level Plasmoid and its D-Bus activation file."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def xdg(name, default):
    value = os.environ.get(name, '')
    return Path(value) if value and Path(value).is_absolute() else Path.home() / default


def main():
    root = Path(__file__).resolve().parent
    python = root / '.venv/bin/python'
    if not python.exists():
        raise SystemExit('请先在项目目录执行 uv sync --frozen')
    tool = shutil.which('kpackagetool6')
    if not tool:
        raise SystemExit('缺少 kpackagetool6，请先安装 Plasma 6 的 kpackagetool6 软件包')
    data = xdg('XDG_DATA_HOME', '.local/share')
    services = data / 'dbus-1/services'
    services.mkdir(parents=True, exist_ok=True)
    # D-Bus Exec uses command-line quoting, not a shell.
    executable = str(python).replace('\\', '\\\\').replace('"', '\\"')
    service_text = ('[D-BUS Service]\nName=org.kstickynotes.Service\n'
                    f'Exec="{executable}" -m kstickynotes.service\n')
    service_path = services / 'org.kstickynotes.Service.service'
    package_root = data / 'plasma/plasmoids'
    target = package_root / 'org.marco.kstickynotes'
    operation = '--upgrade' if target.exists() else '--install'
    subprocess.run([tool, '--type', 'Plasma/Applet', '--packageroot', str(package_root),
                    operation, str(root / 'plasmoid')], check=True)
    service_path.write_text(service_text)
    print('已安装 KStickyNotes 小部件和按需启动的保存服务。')
    print('右键 KDE 面板 → 添加小部件 → 搜索 KStickyNotes → 拖到面板。')
    print('不需要再启动独立窗口版；若它仍在运行，请先从其托盘菜单退出。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
