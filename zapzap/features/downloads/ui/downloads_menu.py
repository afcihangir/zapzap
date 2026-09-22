from __future__ import annotations

import os

from gettext import gettext as _

from PyQt6.QtCore import QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from zapzap.features.downloads.download_manager import DownloadManager


class DownloadRow(QWidget):
    """One recent download with a separate folder action."""

    open_requested = pyqtSignal(str)
    folder_requested = pyqtSignal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(6)

        file_button = QPushButton(os.path.basename(path), self)
        file_button.setObjectName("RecentDownloadFile")
        file_button.setFlat(True)
        file_button.setCursor(Qt.CursorShape.PointingHandCursor)
        file_button.setToolTip(path)
        file_button.setMinimumWidth(260)
        file_button.setMaximumWidth(420)
        file_button.setStyleSheet(
            """
            QPushButton {
                text-align: left;
                padding: 7px 8px;
                border: 0;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: palette(alternate-base);
            }
            """
        )
        file_button.clicked.connect(
            lambda _checked=False: self.open_requested.emit(self.path)
        )

        folder_button = QPushButton(self)
        folder_button.setObjectName("RecentDownloadFolder")
        folder_button.setFlat(True)
        folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_button.setFixedSize(QSize(34, 34))
        folder_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        folder_button.setToolTip(_("Open folder"))
        folder_button.clicked.connect(
            lambda _checked=False: self.folder_requested.emit(self.path)
        )
        folder_button.setVisible(False)
        self.folder_button = folder_button

        layout.addWidget(file_button, 1)
        layout.addWidget(folder_button)

    def enterEvent(self, event):
        self.folder_button.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.folder_button.setVisible(False)
        super().leaveEvent(event)


class DownloadsMenu(QMenu):
    """Shared recent-download menu used by sidebar and menubar buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("downloads_menu")
        self.aboutToShow.connect(self.refresh)

    def refresh(self):
        self.clear()

        recent = DownloadManager.recent_downloads()
        if recent:
            for path in recent:
                action = QWidgetAction(self)
                row = DownloadRow(path, self)
                row.open_requested.connect(self._open_file)
                row.folder_requested.connect(self._open_parent_folder)
                action.setDefaultWidget(row)
                self.addAction(action)
        else:
            empty = QLabel(_("No recent downloads"), self)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(16, 12, 16, 12)
            empty.setEnabled(False)
            action = QWidgetAction(self)
            action.setDefaultWidget(empty)
            self.addAction(action)

        self.addSeparator()

        clear_action = self.addAction(_("Clear download history"))
        clear_action.setEnabled(bool(recent))
        clear_action.triggered.connect(self._clear_history)

        open_folder_action = self.addAction(_("Open downloads folder"))
        open_folder_action.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        open_folder_action.triggered.connect(self._open_downloads_folder)

    def _open_file(self, path: str):
        self.close()
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_parent_folder(self, path: str):
        self.close()
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.dirname(path))
        )

    def _clear_history(self):
        DownloadManager.clear_recent_downloads()
        self.refresh()

    def _open_downloads_folder(self):
        self.close()
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(DownloadManager.get_path())
        )
