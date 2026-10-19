"""Discover the distribution's KDE integration without hard-coding plugin paths."""
import os
from pathlib import Path
import shutil
import subprocess
from PySide6.QtCore import QCoreApplication, qVersion


def configure_desktop():
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":"):
        return
    executable = shutil.which("qtpaths6")
    if not executable:
        return
    try:
        def query(option):
            return subprocess.run([executable, option], check=True, capture_output=True,
                                  text=True, timeout=1).stdout.strip()
        # KDE platform themes may use private Qt APIs. Only expose system plugins
        # when their Qt major/minor matches the bundled runtime.
        if query("--qt-version").split(".")[:2] != qVersion().split(".")[:2]:
            return
        plugins = Path(query("--plugin-dir"))
        if plugins.is_absolute() and (plugins / "platformthemes").is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
            os.environ.setdefault("QT_QPA_PLATFORMTHEME", "kde")
    except (OSError, subprocess.SubprocessError):
        pass  # Standard Qt controls remain available if discovery fails.
