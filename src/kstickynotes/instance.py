"""A held advisory lock prevents startup races; local IPC only requests activation."""
import fcntl
import hashlib
import os
import time
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class Instance(QObject):
    activated = Signal()

    def __init__(self, directory: Path):
        super().__init__()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        identity = f"{os.getuid()}:{directory.resolve()}".encode()
        self.name = "kstickynotes-" + hashlib.sha256(identity).hexdigest()[:24]
        self.lock = open(directory / "instance.lock", "a+")
        self.primary = False
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            return
        self.primary = True
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.close()
            raise RuntimeError(self.server.errorString())
        self.server.newConnection.connect(self._accept)

    def wake(self) -> bool:
        # The primary may still be loading Qt or its database.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(150):
                socket.disconnectFromServer()
                return True
            time.sleep(.05)
        return False

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.close()
            socket.deleteLater()
            self.activated.emit()

    def close(self):
        if self.primary:
            self.server.close()
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            self.primary = False
