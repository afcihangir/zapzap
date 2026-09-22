from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QStandardPaths
from zapzap.core.config.settings_manager import SettingsManager
from zapzap.features.downloads.download_naming_service import DownloadNamingService
from PyQt6.QtWidgets import QFileDialog

from gettext import gettext as _


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

        if download.state() != QWebEngineDownloadRequest.DownloadState.DownloadRequested:
            return

        if not DownloadManager._set_initial_download_parameters(download):
            return

        def remember_completed(state):
            if (
                state ==
                QWebEngineDownloadRequest.DownloadState.DownloadCompleted
            ):
                DownloadManager._record_completed_download(download)

        download.stateChanged.connect(remember_completed)
        DownloadManager._active_downloads.append(download)

        dialog = DownloadDialog(download, parent)
        DownloadManager._floating_cards.append(dialog)

        try:
            dialog.exec()
        finally:
            DownloadManager._release_download(download, dialog)

    @staticmethod
    def _release_download(download: QWebEngineDownloadRequest, dialog):
        if download in DownloadManager._active_downloads:
            DownloadManager._active_downloads.remove(download)

        if dialog in DownloadManager._floating_cards:
            DownloadManager._floating_cards.remove(dialog)

    @staticmethod
    def _record_completed_download(download: QWebEngineDownloadRequest):
        try:
            directory = download.downloadDirectory()
            file_name = download.downloadFileName()
        except RuntimeError:
            return

        if not directory or not file_name:
            return

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

        try:
            download.cancel()
        except Exception:
            logger.exception("Failed to cancel a download with no valid target")
        return False

    @staticmethod
    def open_folder_dialog(parent):
        directory = DownloadManager.get_path()

        options = (
            QFileDialog.Option.DontUseNativeDialog
            if SettingsManager.get("system/DontUseNativeDialog", False)
            else QFileDialog.Option(0)
        )

        folder_path = QFileDialog.getExistingDirectory(
            parent=parent,
            caption=_("Select folder"),
            directory=directory,
            options=options
        )

        return folder_path or None
