"""Publish immutable QML snapshots so reload never reuses stale source."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


def prepare_ui(source: Path, cache: Path) -> Path:
    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_file() and (path.suffix in (".qml", ".js", ".mjs") or path.name == "qmldir"):
            if path.is_symlink():
                raise RuntimeError("界面文件含符号链接，请检查安装目录")
            files[str(path.relative_to(source))] = path.read_bytes()
    if "NotesView.qml" not in files:
        raise RuntimeError("未找到已安装的 NotesView.qml，请先运行 install-widget.py")
    digest = hashlib.sha256()
    for name, data in files.items():
        digest.update(name.encode("utf-8") + b"\0" + data + b"\0")
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = cache / digest.hexdigest()
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".prepare-", dir=cache))
        try:
            for name, data in files.items():
                path = temporary / name
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o600)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return destination / "NotesView.qml"
