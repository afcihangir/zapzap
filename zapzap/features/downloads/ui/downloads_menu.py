from __future__ import annotations

import os

from gettext import gettext as _

from PyQt6.QtCore import (
    QFileInfo,
    QMimeDatabase,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from zapzap.assets.icons.system_icon import SystemIcon
from zapzap.core.theme.theme_manager import ThemeManager
from zapzap.features.downloads.download_events import download_events
from zapzap.features.downloads.download_manager import DownloadManager


class DownloadRow(QWidget):
    """Chrome-like download row with system file icon and live status."""

    open_requested = pyqtSignal(str)
    folder_requested = pyqtSignal(str)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = dict(item)
        self.key = item.get("key")
        self.path = item.get("path", "")
        self._file_icon_provider = QFileIconProvider()

        self.setMinimumWidth(360)
        self.setMaximumWidth(520)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 5, 5, 5)
        root.setSpacing(8)

        self.file_icon = QLabel(self)
        self.file_icon.setFixedSize(QSize(34, 34))
        self.file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.file_icon, 0, Qt.AlignmentFlag.AlignTop)

        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(3)

        self.name_button = QPushButton(self)
        self.name_button.setFlat(True)
        self.name_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.name_button.setStyleSheet(
            """
            QPushButton {
                text-align: left;
                padding: 2px 0;
                border: 0;
                font-weight: 600;
            }
            QPushButton:hover {
                text-decoration: underline;
            }
            """
        )
        self.name_button.clicked.connect(self._open_if_completed)
        center_layout.addWidget(self.name_button)

        self.progress_row = QWidget(center)
        progress_layout = QHBoxLayout(self.progress_row)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(7)

        self.progress = QProgressBar(self.progress_row)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        self.progress.setMinimumWidth(220)
        self.progress_percent = QLabel(self.progress_row)
        self.progress_percent.setMinimumWidth(34)
        self.progress_percent.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        progress_layout.addWidget(self.progress, 1)
        progress_layout.addWidget(self.progress_percent)
        center_layout.addWidget(self.progress_row)

        self.status_row = QWidget(center)
        status_layout = QHBoxLayout(self.status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(5)
        self.status_icon = QLabel(self.status_row)
        self.status_icon.setFixedSize(QSize(16, 16))
        self.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_text = QLabel(self.status_row)
        self.status_text.setWordWrap(True)
        status_layout.addWidget(self.status_icon)
        status_layout.addWidget(self.status_text, 1)
        center_layout.addWidget(self.status_row)

        root.addWidget(center, 1)

        self.actions = QWidget(self)
        actions_layout = QHBoxLayout(self.actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(2)

        self.folder_button = self._icon_button(
            QStyle.StandardPixmap.SP_DirOpenIcon,
            _("Open folder"),
        )
        self.folder_button.clicked.connect(
            lambda: self.folder_requested.emit(self.path)
        )
        actions_layout.addWidget(self.folder_button)

        self.pause_button = self._icon_button(
            QStyle.StandardPixmap.SP_MediaPause,
            _("Pause"),
        )
        self.pause_button.clicked.connect(self._pause)
        actions_layout.addWidget(self.pause_button)

        self.resume_button = self._icon_button(
            QStyle.StandardPixmap.SP_MediaPlay,
            _("Resume"),
        )
        self.resume_button.clicked.connect(self._resume)
        actions_layout.addWidget(self.resume_button)

        self.cancel_button = self._icon_button(
            QStyle.StandardPixmap.SP_DialogCancelButton,
            _("Cancel"),
        )
        self.cancel_button.clicked.connect(self._cancel)
        actions_layout.addWidget(self.cancel_button)

        self.actions.hide()
        root.addWidget(self.actions, 0, Qt.AlignmentFlag.AlignTop)

        self._update_from_item(self.item)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self._refresh_live_item)
        if self.item.get("live"):
            self._refresh_timer.start()

    def _icon_button(self, standard_icon, tooltip):
        button = QPushButton(self)
        button.setFlat(True)
        button.setFixedSize(QSize(30, 30))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(self.style().standardIcon(standard_icon))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        return button

    def _system_file_icon(self, path: str, name: str) -> QIcon:
        if path and os.path.exists(path):
            icon = self._file_icon_provider.icon(QFileInfo(path))
            if not icon.isNull():
                return icon

        mime = QMimeDatabase().mimeTypeForFile(
            name or path,
            QMimeDatabase.MatchMode.MatchExtension,
        )
        if mime.isValid():
            icon = QIcon.fromTheme(mime.iconName())
            if not icon.isNull():
                return icon

        return self._file_icon_provider.icon(QFileInfo(path or name))

    def _status_standard_icon(self, status: str):
        mapping = {
            "queued": QStyle.StandardPixmap.SP_BrowserReload,
            "requested": QStyle.StandardPixmap.SP_BrowserReload,
            "paused": QStyle.StandardPixmap.SP_MediaPause,
            "interrupted": QStyle.StandardPixmap.SP_MessageBoxWarning,
            "cancelled": QStyle.StandardPixmap.SP_DialogCancelButton,
            "blocked": QStyle.StandardPixmap.SP_MessageBoxCritical,
            "completed": QStyle.StandardPixmap.SP_DialogApplyButton,
        }
        return mapping.get(
            status,
            QStyle.StandardPixmap.SP_FileIcon,
        )

    def _status_label(self, item: dict) -> str:
        status = item.get("status")
        labels = {
            "queued": _("Queued"),
            "requested": _("Queued"),
            "paused": _("Paused"),
            "interrupted": _("Interrupted"),
            "cancelled": _("Cancelled"),
            "blocked": _("Blocked"),
            "completed": _("Completed"),
        }
        label = labels.get(status, "")
        reason = item.get("reason", "")
        if reason and status == "interrupted":
            return f"{label} — {reason}"
        return label

    def _update_from_item(self, item: dict):
        self.item = dict(item)
        self.path = item.get("path", "")
        name = item.get("name") or os.path.basename(self.path) or _("Download")
        status = item.get("status", "completed")

        icon = self._system_file_icon(self.path, name)
        self.file_icon.setPixmap(icon.pixmap(QSize(30, 30)))

        self.name_button.setText(name)
        name_font = self.name_button.font()
        name_font.setStrikeOut(status in {"cancelled", "blocked"})
        self.name_button.setFont(name_font)
        self.name_button.setToolTip(self.path or name)
        self.name_button.setCursor(
            Qt.CursorShape.PointingHandCursor
            if status == "completed"
            else Qt.CursorShape.ArrowCursor
        )

        show_progress = status == "active"
        self.progress_row.setVisible(show_progress)
        self.status_row.setVisible(not show_progress)

        if show_progress:
            percent = item.get("percent")
            if percent is None:
                self.progress.setRange(0, 0)
                self.progress_percent.setText("…")
            else:
                self.progress.setRange(0, 100)
                self.progress.setValue(int(percent))
                self.progress_percent.setText(f"{int(percent)}%")

        if not show_progress:
            status_icon = self.style().standardIcon(
                self._status_standard_icon(status)
            )
            self.status_icon.setPixmap(status_icon.pixmap(QSize(14, 14)))
            self.status_text.setText(self._status_label(item))

        live = bool(item.get("live"))
        self.folder_button.setVisible(bool(self.path))
        self.pause_button.setVisible(live and status == "active")
        self.resume_button.setVisible(
            live
            and (
                status == "paused"
                or (
                    status == "interrupted"
                    and bool(item.get("resumable"))
                )
            )
        )
        self.cancel_button.setVisible(
            live
            and status in {
                "active",
                "paused",
                "queued",
                "requested",
                "interrupted",
            }
        )

    def _refresh_live_item(self):
        item = DownloadManager.item_snapshot(self.key)
        if item is None:
            self._refresh_timer.stop()
            return
        self._update_from_item(item)

    def _open_if_completed(self):
        if self.item.get("status") != "completed":
            return
        if self.path and os.path.isfile(self.path):
            self.open_requested.emit(self.path)

    def _pause(self):
        DownloadManager.pause_download(self.key)

    def _resume(self):
        DownloadManager.resume_download(self.key)

    def _cancel(self):
        DownloadManager.cancel_download(self.key)

    def enterEvent(self, event):
        self.actions.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.actions.hide()
        super().leaveEvent(event)


class DownloadsMenu(QMenu):
    """Shared recent-download menu used by sidebar and menubar buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("downloads_menu")
        self.aboutToShow.connect(self.refresh)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(75)
        self._refresh_timer.timeout.connect(self._refresh_if_visible)
        download_events.items_changed.connect(self._schedule_refresh)

    def _schedule_refresh(self):
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _refresh_if_visible(self):
        if self.isVisible():
            self.refresh()

    def refresh(self):
        self.clear()

        items = DownloadManager.download_items()
        if items:
            for item in items:
                action = QWidgetAction(self)
                row = DownloadRow(item, self)
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
        clear_action.setEnabled(any(not item.get("live") for item in items))
        icon_theme = SystemIcon.Type[
            ThemeManager.get_current_color_scheme().name
        ]
        clear_action.setIcon(SystemIcon.get_icon("trash", icon_theme))
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
        directory = path if os.path.isdir(path) else os.path.dirname(path)
        if not directory:
            return
        self.close()
        QDesktopServices.openUrl(QUrl.fromLocalFile(directory))

    def _clear_history(self):
        DownloadManager.clear_recent_downloads()
        self.close()

    def _open_downloads_folder(self):
        self.close()
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(DownloadManager.get_path())
        )
