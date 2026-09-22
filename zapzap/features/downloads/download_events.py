"""Signals shared by download handling and application chrome."""

from PyQt6.QtCore import QObject, pyqtSignal


class DownloadEvents(QObject):
    """Application-local download lifecycle events."""

    completed = pyqtSignal(str, bool)


download_events = DownloadEvents()
