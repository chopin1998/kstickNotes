"""Use one QApplication for mixed headless-backend and QWidget tests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='session', autouse=True)
def qt_application():
    # A QCoreApplication cannot later be upgraded to QApplication in one process.
    app = QApplication.instance() or QApplication([])
    yield app
