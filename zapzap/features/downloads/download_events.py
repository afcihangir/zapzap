"""Signals shared by download handling and application chrome."""

from PyQt6.QtCore import QObject, pyqtSignal


class DownloadEvents(QObject):
    """Application-local download lifecycle events."""

    started = pyqtSignal(str)
    completed = pyqtSignal(str)


download_events = DownloadEvents()
