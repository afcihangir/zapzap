from __future__ import annotations

import os

from gettext import gettext as _

from PyQt6.QtCore import (
    QFileInfo,
    QMimeDatabase,
    QPoint,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAbstractFileIconProvider,
    QColor,
    QDesktopServices,
    QGuiApplication,
    QIcon,
)
from PyQt6.QtWidgets import (
    QFileIconProvider,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from zapzap.assets.icons.system_icon import SystemIcon
from zapzap.core.theme.theme_manager import ThemeManager
from zapzap.features.downloads.download_events import download_events
from zapzap.features.downloads.download_manager import DownloadManager


class DownloadRow(QFrame):
    """Chrome-like download row with the platform's native file-type icon."""

    open_requested = pyqtSignal(str)
    folder_requested = pyqtSignal(str)

    _file_icon_provider = None

    @classmethod
    def _native_icon_provider(cls):
        """Create the platform icon provider lazily after Qt is available."""
        if cls._file_icon_provider is None:
            cls._file_icon_provider = QFileIconProvider()
        return cls._file_icon_provider

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = dict(item)
        self.key = item.get("key")
        self.path = item.get("path", "")
        self.setObjectName("DownloadRow")

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

        self.transfer_details = QLabel(center)
        self.transfer_details.setStyleSheet(
            "color: palette(placeholder-text);"
        )
        self.transfer_details.hide()
        center_layout.addWidget(self.transfer_details)

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

    @staticmethod
    def _elide_file_name(name: str, max_length: int = 38) -> str:
        """Elide the middle while preserving the extension and tail."""
        if len(name) <= max_length:
            return name

        stem, extension = os.path.splitext(name)
        if len(extension) >= max_length - 8:
            return f"{name[: max_length - 1]}…"

        available = max_length - len(extension) - 1
        prefix_len = max(8, int(available * 0.65))
        suffix_len = max(4, available - prefix_len)
        if prefix_len + suffix_len >= len(stem):
            return name

        return (
            f"{stem[:prefix_len]}…{stem[-suffix_len:]}"
            f"{extension}"
        )

    @classmethod
    def _system_file_icon(cls, path: str, name: str) -> QIcon:
        """Resolve the native file-type icon without generating a preview."""
        provider = cls._native_icon_provider()
        candidate = path or name

        # Existing files get the exact icon chosen by the host OS/desktop.
        # This is the primary path for completed and most active downloads.
        if path and QFileInfo.exists(path):
            icon = provider.icon(QFileInfo(path))
            if not icon.isNull():
                return icon

        # Ask the native provider for the filename/extension even when the
        # target does not exist yet (queued/requested downloads). Some native
        # backends can resolve the associated application/type from this.
        native_candidate = (
            provider.icon(QFileInfo(candidate))
            if candidate
            else QIcon()
        )
        generic_native = provider.icon(
            QAbstractFileIconProvider.IconType.File
        )
        if (
            not native_candidate.isNull()
            and (
                generic_native.isNull()
                or native_candidate.cacheKey() != generic_native.cacheKey()
            )
        ):
            return native_candidate

        # Freedesktop MIME icons are especially useful on Linux. On Qt 6.7+
        # QIcon can also access native icon libraries on Windows and macOS, so
        # these names are a safe cross-platform fallback when available.
        mime = QMimeDatabase().mimeTypeForFile(
            name or candidate,
            QMimeDatabase.MatchMode.MatchExtension,
        )
        if mime.isValid():
            for icon_name in (mime.iconName(), mime.genericIconName()):
                if not icon_name:
                    continue
                icon = QIcon.fromTheme(icon_name)
                if not icon.isNull():
                    return icon

        # Never invent a bundled PDF/image icon: if the platform has no
        # type-specific icon, use its own generic file icon.
        if not native_candidate.isNull():
            return native_candidate
        if not generic_native.isNull():
            return generic_native
        return QIcon()

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

        self.name_button.setText(self._elide_file_name(name))
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

            details = self._transfer_details_text(item)
            self.transfer_details.setText(details)
            self.transfer_details.setVisible(bool(details))
        else:
            self.transfer_details.hide()

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

    @staticmethod
    def _format_speed(speed_bps):
        if speed_bps is None or speed_bps <= 0:
            return ""

        value = float(speed_bps)
        units = ("B/s", "KB/s", "MB/s", "GB/s")
        unit = units[0]
        for candidate in units:
            unit = candidate
            if value < 1024.0 or candidate == units[-1]:
                break
            value /= 1024.0

        if value >= 100:
            return f"{value:.0f} {unit}"
        if value >= 10:
            return f"{value:.1f} {unit}"
        return f"{value:.2f} {unit}"

    @staticmethod
    def _format_eta(eta_seconds):
        if eta_seconds is None or eta_seconds < 0:
            return ""

        seconds = max(0, int(round(eta_seconds)))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours:
            return f"⏱ {hours}:{minutes:02d}:{seconds:02d}"
        return f"⏱ {minutes}:{seconds:02d}"

    @classmethod
    def _transfer_details_text(cls, item):
        speed = cls._format_speed(item.get("speed_bps"))
        eta = cls._format_eta(item.get("eta_seconds"))
        return "  •  ".join(part for part in (speed, eta) if part)

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


class DownloadsPopover(QFrame):
    """Compact Chrome-like downloads window shared by both download buttons."""

    interacted = pyqtSignal()

    WIDTH = 440
    SHADOW_MARGIN = 10
    MAX_ITEMS_HEIGHT = 330

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        self.setObjectName("DownloadsPopover")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedWidth(self.WIDTH)

        self._setup_ui()
        self._apply_style()
        self._refresh_theme()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(75)
        self._refresh_timer.timeout.connect(self._refresh_if_visible)
        download_events.items_changed.connect(self._schedule_refresh)
        ThemeManager.instance().theme_changed.connect(self._refresh_theme)

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            self.SHADOW_MARGIN,
            self.SHADOW_MARGIN,
            self.SHADOW_MARGIN,
            self.SHADOW_MARGIN,
        )

        self.surface = QFrame(self)
        self.surface.setObjectName("DownloadsPopoverSurface")
        outer.addWidget(self.surface)

        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 75))
        self.surface.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 0, 0)
        header.setSpacing(8)

        self.title_label = QLabel(_("Downloads"), self.surface)
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.close_button = QPushButton(self.surface)
        self.close_button.setObjectName("DownloadsCloseButton")
        self.close_button.setFlat(True)
        self.close_button.setFixedSize(QSize(28, 28))
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button)

        layout.addLayout(header)

        separator = QFrame(self.surface)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        self.items_scroll = QScrollArea(self.surface)
        self.items_scroll.setObjectName("DownloadsScroll")
        self.items_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.items_scroll.setWidgetResizable(True)
        self.items_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.items_widget = QWidget(self.items_scroll)
        self.items_widget.setObjectName("DownloadsItems")
        self.items_layout = QVBoxLayout(self.items_widget)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(2)
        self.items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.items_scroll.setWidget(self.items_widget)
        layout.addWidget(self.items_scroll)

        footer_separator = QFrame(self.surface)
        footer_separator.setFrameShape(QFrame.Shape.HLine)
        footer_separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(footer_separator)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)

        self.clear_button = QPushButton(
            _("Clear download history"),
            self.surface,
        )
        self.clear_button.setObjectName("DownloadsFooterButton")
        self.clear_button.setFlat(True)
        self.clear_button.clicked.connect(self._clear_history)
        footer.addWidget(self.clear_button)

        footer.addStretch(1)

        self.open_folder_button = QPushButton(
            _("Open downloads folder"),
            self.surface,
        )
        self.open_folder_button.setObjectName("DownloadsFooterButton")
        self.open_folder_button.setFlat(True)
        self.open_folder_button.clicked.connect(self._open_downloads_folder)
        footer.addWidget(self.open_folder_button)

        layout.addLayout(footer)

    def _apply_style(self):
        self.setStyleSheet(
            """
            QFrame#DownloadsPopover {
                background: transparent;
                border: 0;
            }
            QFrame#DownloadsPopoverSurface {
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 12px;
            }
            QWidget#DownloadsItems,
            QScrollArea#DownloadsScroll,
            QScrollArea#DownloadsScroll > QWidget > QWidget {
                background: transparent;
                border: 0;
            }
            QFrame#DownloadRow {
                background: transparent;
                border: 0;
                border-radius: 8px;
            }
            QFrame#DownloadRow:hover {
                background: palette(alternate-base);
            }
            QPushButton#DownloadsCloseButton,
            QPushButton#DownloadsFooterButton {
                border: 0;
                border-radius: 7px;
                padding: 5px 7px;
                background: transparent;
            }
            QPushButton#DownloadsCloseButton:hover,
            QPushButton#DownloadsFooterButton:hover {
                background: palette(alternate-base);
            }
            QPushButton#DownloadsFooterButton:disabled {
                color: palette(placeholder-text);
            }
            """
        )

    def _refresh_theme(self, *_args):
        self.close_button.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_TitleBarCloseButton
            )
        )
        icon_theme = SystemIcon.Type[
            ThemeManager.get_current_color_scheme().name
        ]
        self.clear_button.setIcon(SystemIcon.get_icon("trash", icon_theme))
        self.open_folder_button.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_DirOpenIcon
            )
        )
        self.update()

    def _schedule_refresh(self):
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _refresh_if_visible(self):
        if self.isVisible():
            self.refresh()

    def _clear_rows(self):
        while self.items_layout.count():
            item = self.items_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def refresh(self):
        self._clear_rows()
        items = DownloadManager.download_items()

        if items:
            for item in items:
                row = DownloadRow(item, self.items_widget)
                row.open_requested.connect(self._open_file)
                row.folder_requested.connect(self._open_parent_folder)
                self.items_layout.addWidget(row)
            body_height = min(
                self.MAX_ITEMS_HEIGHT,
                max(82, len(items) * 76),
            )
        else:
            empty = QLabel(_("No recent downloads"), self.items_widget)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(16, 18, 16, 18)
            empty.setEnabled(False)
            self.items_layout.addWidget(empty)
            body_height = 72

        self.items_scroll.setFixedHeight(body_height)
        self.clear_button.setEnabled(
            any(not item.get("live") for item in items)
        )
        self._refresh_theme()
        self.adjustSize()

    def popup_for(self, anchor, *, below=False, activate=True):
        self.refresh()
        self.adjustSize()

        if below:
            anchor_point = anchor.mapToGlobal(
                QPoint(anchor.width(), anchor.height() + 4)
            )
            target = QPoint(
                anchor_point.x() - self.width(),
                anchor_point.y(),
            )
        else:
            anchor_point = anchor.mapToGlobal(
                QPoint(anchor.width() + 8, 0)
            )
            target = QPoint(
                anchor_point.x(),
                anchor_point.y() + (anchor.height() - self.height()) // 2,
            )

        screen = (
            QGuiApplication.screenAt(
                anchor.mapToGlobal(anchor.rect().center())
            )
            or QGuiApplication.primaryScreen()
        )
        if screen is not None:
            available = screen.availableGeometry()
            target.setX(
                min(
                    max(target.x(), available.left()),
                    available.right() - self.width() + 1,
                )
            )
            target.setY(
                min(
                    max(target.y(), available.top()),
                    available.bottom() - self.height() + 1,
                )
            )

        self.move(target)
        self.show()
        self.raise_()
        if activate:
            self.activateWindow()
            self.setFocus(Qt.FocusReason.PopupFocusReason)
        return True

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
        self.interacted.emit()
        DownloadManager.clear_recent_downloads()
        self.refresh()

    def _open_downloads_folder(self):
        self.close()
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(DownloadManager.get_path())
        )

    def enterEvent(self, event):
        self.interacted.emit()
        super().enterEvent(event)

    def mousePressEvent(self, event):
        self.interacted.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)
