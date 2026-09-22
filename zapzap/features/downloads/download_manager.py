from __future__ import annotations

import logging
import mimetypes
import os
from typing import TYPE_CHECKING

from gettext import gettext as _

from PyQt6.QtCore import QStandardPaths, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog

from zapzap.core.config.settings.downloads import DownloadBehavior, DownloadSettings
from zapzap.core.config.settings_manager import SettingsManager
from zapzap.features.downloads.download_events import download_events
from zapzap.features.downloads.download_naming_service import DownloadNamingService


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest


class DownloadManager:
    DOWNLOAD_PATH = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DownloadLocation
    )

    _floating_cards = []
    _active_downloads = []
    _RECENT_DOWNLOADS_KEY = "system/recent_downloads"
    MAX_RECENT_DOWNLOADS = 10

    @staticmethod
    def set_path(new_path):
        path = (
            new_path
            if isinstance(new_path, str) and new_path.strip()
            else DownloadManager.DOWNLOAD_PATH
        )
        SettingsManager.set("system/download_path", path)

    @staticmethod
    def get_path():
        path = SettingsManager.get(
            "system/download_path",
            DownloadManager.DOWNLOAD_PATH
        )
        if not isinstance(path, str) or not path.strip():
            logger.warning(
                "Invalid stored download directory; replacing it with the default"
            )
            path = DownloadManager.DOWNLOAD_PATH
            DownloadManager.set_path(path)
        return path

    @staticmethod
    def restore_path():
        SettingsManager.set(
            "system/download_path",
            DownloadManager.DOWNLOAD_PATH
        )

    @staticmethod
    def on_downloadRequested(
        download: QWebEngineDownloadRequest,
        parent=None
    ):
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest
        from zapzap.features.downloads.ui.download_dialog import DownloadDialog

        if (
            download.state()
            != QWebEngineDownloadRequest.DownloadState.DownloadRequested
        ):
            return

        if not DownloadManager._set_initial_download_parameters(download):
            return

        settings = DownloadSettings()
        behavior = settings.behavior
        direct_mode = behavior != DownloadBehavior.DIALOG

        def handle_state(state):
            terminal_states = {
                QWebEngineDownloadRequest.DownloadState.DownloadCompleted,
                QWebEngineDownloadRequest.DownloadState.DownloadCancelled,
                QWebEngineDownloadRequest.DownloadState.DownloadInterrupted,
            }

            if (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            ):
                path = DownloadManager._record_completed_download(download)
                if path:
                    if (
                        settings.auto_open_media
                        and DownloadManager.supports_auto_open(
                            DownloadManager._safe_mime_type(download),
                            os.path.basename(path),
                        )
                    ):
                        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
                    DownloadManager._release_download(download, None)
                    download_events.completed.emit(path)
                    return

            if state in terminal_states:
                DownloadManager._release_download(download, None)

        download.stateChanged.connect(handle_state)
        DownloadManager._active_downloads.append(download)

        if behavior == DownloadBehavior.AUTOMATIC:
            if DownloadManager._accept_download(download) and direct_mode:
                path = DownloadManager._download_path(download)
                if path:
                    download_events.started.emit(path)
            return

        if behavior == DownloadBehavior.ASK_EVERY_TIME:
            if DownloadManager._choose_download_target(download, parent):
                if DownloadManager._accept_download(download) and direct_mode:
                    path = DownloadManager._download_path(download)
                    if path:
                        download_events.started.emit(path)
            else:
                DownloadManager._cancel_download(download)
            return

        dialog = DownloadDialog(download, parent)
        DownloadManager._floating_cards.append(dialog)

        try:
            dialog.exec()
        finally:
            DownloadManager._release_download(download, dialog)

    @staticmethod
    def _accept_download(download):
        try:
            download.accept()
            return True
        except RuntimeError:
            logger.exception("Download could not be started")
            DownloadManager._cancel_download(download)
            return False

    @staticmethod
    def _cancel_download(download):
        try:
            download.cancel()
        except RuntimeError:
            logger.exception("Download could not be cancelled")
        DownloadManager._release_download(download, None)

    @staticmethod
    def _release_download(download: QWebEngineDownloadRequest, dialog=None):
        if download in DownloadManager._active_downloads:
            DownloadManager._active_downloads.remove(download)

        if dialog is not None and dialog in DownloadManager._floating_cards:
            DownloadManager._floating_cards.remove(dialog)

    @staticmethod
    def _record_completed_download(download: QWebEngineDownloadRequest):
        try:
            directory = download.downloadDirectory()
            file_name = download.downloadFileName()
        except RuntimeError:
            return None

        if not directory or not file_name:
            return None

        path = os.path.normpath(os.path.join(directory, file_name))
        recent = SettingsManager.get(DownloadManager._RECENT_DOWNLOADS_KEY, [])
        if isinstance(recent, str):
            recent = [recent]
        elif not isinstance(recent, (list, tuple)):
            recent = []

        normalized = os.path.normcase(path)
        recent = [
            item for item in recent
            if isinstance(item, str)
            and os.path.normcase(os.path.normpath(item)) != normalized
        ]
        recent.insert(0, path)
        SettingsManager.set(
            DownloadManager._RECENT_DOWNLOADS_KEY,
            recent[:DownloadManager.MAX_RECENT_DOWNLOADS],
        )
        return path

    @staticmethod
    def _download_path(download):
        try:
            directory = download.downloadDirectory()
            file_name = download.downloadFileName()
        except RuntimeError:
            return ""
        if not directory or not file_name:
            return ""
        return os.path.normpath(os.path.join(directory, file_name))

    @staticmethod
    def active_downloads():
        paths = []
        for download in tuple(DownloadManager._active_downloads):
            path = DownloadManager._download_path(download)
            if path and path not in paths:
                paths.append(path)
        return paths

    @staticmethod
    def recent_downloads():
        recent = SettingsManager.get(DownloadManager._RECENT_DOWNLOADS_KEY, [])
        if isinstance(recent, str):
            recent = [recent]
        elif not isinstance(recent, (list, tuple)):
            recent = []

        valid = [
            os.path.normpath(item)
            for item in recent
            if isinstance(item, str) and os.path.isfile(item)
        ][:DownloadManager.MAX_RECENT_DOWNLOADS]

        if list(recent) != valid:
            SettingsManager.set(DownloadManager._RECENT_DOWNLOADS_KEY, valid)
        return valid

    @staticmethod
    def clear_recent_downloads():
        SettingsManager.set(DownloadManager._RECENT_DOWNLOADS_KEY, [])

    @staticmethod
    def supports_auto_open(mime_type: str, file_name: str) -> bool:
        mime_type = (mime_type or "").strip().lower()
        if mime_type == "application/pdf" or mime_type.startswith("image/"):
            return True

        guessed_type, _encoding = mimetypes.guess_type(file_name or "")
        guessed_type = (guessed_type or "").lower()
        return (
            guessed_type == "application/pdf"
            or guessed_type.startswith("image/")
        )

    @staticmethod
    def _safe_mime_type(download) -> str:
        try:
            return download.mimeType() or ""
        except RuntimeError:
            return ""

    @staticmethod
    def _normalize_download_file_name(download: QWebEngineDownloadRequest):
        file_name = DownloadNamingService.normalized_file_name(
            download.downloadFileName() or download.suggestedFileName(),
            download.mimeType(),
            download.url().toString()
        )

        if file_name != download.downloadFileName():
            download.setDownloadFileName(file_name)

    @staticmethod
    def _set_initial_download_parameters(download) -> bool:
        """Set the target safely, retrying with the default before cancelling."""
        configured_path = DownloadManager.get_path()
        try:
            download.setDownloadDirectory(configured_path)
            DownloadManager._normalize_download_file_name(download)
            return True
        except Exception:
            logger.exception(
                "Failed to apply the configured download target; retrying "
                "with the default directory"
            )

        try:
            download.setDownloadDirectory(DownloadManager.DOWNLOAD_PATH)
            DownloadManager._normalize_download_file_name(download)
            DownloadManager.restore_path()
            return True
        except Exception:
            logger.exception(
                "Failed to apply the default download target; cancelling "
                "the download"
            )

        DownloadManager._cancel_download(download)
        return False

    @staticmethod
    def _file_dialog_options():
        return (
            QFileDialog.Option.DontUseNativeDialog
            if SettingsManager.get("system/DontUseNativeDialog", False)
            else QFileDialog.Option(0)
        )

    @staticmethod
    def _choose_download_target(download, parent=None) -> bool:
        try:
            directory = download.downloadDirectory()
            file_name = download.downloadFileName()
            mime_type = download.mimeType()
            url = download.url().toString()
        except RuntimeError:
            return False

        suffix = os.path.splitext(file_name)[1].lstrip(".")
        name_filter = f"*.{suffix}" if suffix else "*"

        path, _selected_filter = QFileDialog.getSaveFileName(
            parent,
            _("Save file"),
            os.path.join(directory, file_name),
            name_filter,
            options=DownloadManager._file_dialog_options(),
        )
        if not path:
            return False

        normalized_file_name = DownloadNamingService.normalized_file_name(
            os.path.basename(path),
            mime_type,
            url,
        )

        try:
            download.setDownloadDirectory(os.path.dirname(path))
            download.setDownloadFileName(normalized_file_name)
        except RuntimeError:
            return False
        return True

    @staticmethod
    def open_folder_dialog(parent):
        directory = DownloadManager.get_path()

        folder_path = QFileDialog.getExistingDirectory(
            parent=parent,
            caption=_("Select folder"),
            directory=directory,
            options=DownloadManager._file_dialog_options(),
        )

        return folder_path or None
