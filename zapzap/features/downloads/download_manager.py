from __future__ import annotations

import logging
import mimetypes
import os
import time
from typing import TYPE_CHECKING

from gettext import gettext as _

from PyQt6.QtCore import QStandardPaths, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog

from zapzap.core.config.settings.downloads import (
    DownloadBehavior,
    DownloadSettings,
    MultipleDownloadPermission,
)
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

    MAX_ACTIVE_DOWNLOADS = 6
    MULTIPLE_DOWNLOAD_WINDOW_SECONDS = 10.0
    MAX_RECENT_DOWNLOADS = 10
    MAX_SESSION_RECORDS = 10

    _floating_cards = []
    _active_downloads = []
    _queued_downloads = []
    _download_meta = {}
    _terminal_records = []
    _last_request_at = None
    _sequence = 0

    _RECENT_DOWNLOADS_KEY = "system/recent_downloads"

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
            DownloadManager.DOWNLOAD_PATH,
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
            DownloadManager.DOWNLOAD_PATH,
        )

    @staticmethod
    def on_downloadRequested(
        download: QWebEngineDownloadRequest,
        parent=None,
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

        DownloadManager._register_download(download)

        if not DownloadManager._authorize_repeated_download(parent):
            DownloadManager._cancel_download(download, "blocked")
            return

        settings = DownloadSettings()
        behavior = settings.behavior
        direct_mode = behavior != DownloadBehavior.DIALOG

        if behavior == DownloadBehavior.AUTOMATIC:
            DownloadManager.start_or_queue(download)
            if direct_mode:
                DownloadManager._emit_direct_activity(download)
            return

        if behavior == DownloadBehavior.ASK_EVERY_TIME:
            if DownloadManager._choose_download_target(download, parent):
                DownloadManager.start_or_queue(download)
                if direct_mode:
                    DownloadManager._emit_direct_activity(download)
            else:
                DownloadManager._cancel_download(download, "cancelled")
            return

        dialog = DownloadDialog(download, parent)
        DownloadManager._floating_cards.append(dialog)

        try:
            dialog.exec()
        finally:
            if dialog in DownloadManager._floating_cards:
                DownloadManager._floating_cards.remove(dialog)

            try:
                state = download.state()
            except RuntimeError:
                state = None

            if (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadRequested
                and download not in DownloadManager._queued_downloads
            ):
                DownloadManager._cancel_download(download, "cancelled")

    @staticmethod
    def _register_download(download):
        key = DownloadManager._download_key(download)
        if download not in DownloadManager._active_downloads:
            DownloadManager._active_downloads.append(download)

        DownloadManager._sequence += 1
        DownloadManager._download_meta[key] = {
            "sequence": DownloadManager._sequence,
            "status": "requested",
            "open_on_complete": False,
            "terminal_override": None,
        }

        download.stateChanged.connect(
            lambda state, item=download: DownloadManager._handle_state(
                item,
                state,
            )
        )
        download.receivedBytesChanged.connect(
            download_events.progress_changed.emit
        )
        download.totalBytesChanged.connect(
            download_events.progress_changed.emit
        )
        download.isPausedChanged.connect(
            download_events.items_changed.emit
        )
        download_events.items_changed.emit()

    @staticmethod
    def _authorize_repeated_download(parent) -> bool:
        from zapzap.features.downloads.ui.multiple_download_dialog import (
            MultipleDownloadDecision,
            MultipleDownloadDialog,
        )

        settings = DownloadSettings()
        permission = settings.multiple_download_permission

        now = time.monotonic()
        previous = DownloadManager._last_request_at
        DownloadManager._last_request_at = now

        is_repeated = (
            previous is not None
            and now - previous <= DownloadManager.MULTIPLE_DOWNLOAD_WINDOW_SECONDS
        )
        if not is_repeated:
            return True

        if permission == MultipleDownloadPermission.ALLOW:
            return True
        if permission == MultipleDownloadPermission.BLOCK:
            return False

        decision = MultipleDownloadDialog.ask(parent)
        if decision == MultipleDownloadDecision.ALWAYS_ALLOW:
            settings.multiple_download_permission = (
                MultipleDownloadPermission.ALLOW
            )
            return True

        if decision == MultipleDownloadDecision.ALLOW_ONCE:
            return True

        settings.multiple_download_permission = MultipleDownloadPermission.BLOCK
        return False

    @staticmethod
    def start_or_queue(download, open_on_complete=False):
        meta = DownloadManager._meta(download)
        if meta is None:
            return "unavailable"

        if open_on_complete:
            meta["open_on_complete"] = True

        if (
            DownloadManager._active_download_count()
            >= DownloadManager.MAX_ACTIVE_DOWNLOADS
        ):
            if download not in DownloadManager._queued_downloads:
                DownloadManager._queued_downloads.append(download)
            meta["status"] = "queued"
            download_events.items_changed.emit()
            download_events.progress_changed.emit()
            return "queued"

        return DownloadManager._begin_download(download)

    @staticmethod
    def _begin_download(download):
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

        meta = DownloadManager._meta(download)
        if meta is None:
            return "unavailable"

        try:
            state = download.state()
            if (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadRequested
            ):
                download.accept()
            elif (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted
            ):
                download.resume()
            elif (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadInProgress
                and download.isPaused()
            ):
                download.resume()
            elif (
                state
                != QWebEngineDownloadRequest.DownloadState.DownloadInProgress
            ):
                return "unavailable"
        except RuntimeError:
            logger.exception("Download could not be started or resumed")
            DownloadManager._cancel_download(download, "cancelled")
            return "unavailable"

        if download in DownloadManager._queued_downloads:
            DownloadManager._queued_downloads.remove(download)
        meta["status"] = "active"
        download_events.items_changed.emit()
        download_events.progress_changed.emit()
        return "started"

    @staticmethod
    def pause_download(key):
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

        download = DownloadManager._find_download(key)
        if download is None:
            return False

        try:
            if (
                download.state()
                != QWebEngineDownloadRequest.DownloadState.DownloadInProgress
                or download.isPaused()
            ):
                return False
            download.pause()
        except RuntimeError:
            return False

        meta = DownloadManager._meta(download)
        if meta is not None:
            meta["status"] = "paused"
        download_events.items_changed.emit()
        download_events.progress_changed.emit()
        DownloadManager._drain_queue()
        return True

    @staticmethod
    def resume_download(key):
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

        download = DownloadManager._find_download(key)
        if download is None:
            return False

        try:
            state = download.state()
            if (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadInProgress
                and download.isPaused()
            ):
                result = DownloadManager.start_or_queue(download)
                return result in {"started", "queued"}

            if (
                state
                != QWebEngineDownloadRequest.DownloadState.DownloadInterrupted
            ):
                return False
        except RuntimeError:
            return False

        result = DownloadManager.start_or_queue(download)
        return result in {"started", "queued"}

    @staticmethod
    def cancel_download(key):
        download = DownloadManager._find_download(key)
        if download is None:
            return False
        DownloadManager._cancel_download(download, "cancelled")
        return True

    @staticmethod
    def _cancel_download(download, status="cancelled"):
        meta = DownloadManager._meta(download)
        if meta is not None:
            meta["terminal_override"] = status

        try:
            download.cancel()
        except RuntimeError:
            logger.exception("Download could not be cancelled")
            DownloadManager._record_terminal(download, status)
            DownloadManager._release_download(download)
        return False

    @staticmethod
    def _handle_state(download, state):
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

        meta = DownloadManager._meta(download)
        if meta is None:
            return

        if state == QWebEngineDownloadRequest.DownloadState.DownloadInProgress:
            try:
                meta["status"] = (
                    "paused" if download.isPaused() else "active"
                )
            except RuntimeError:
                meta["status"] = "active"
            download_events.items_changed.emit()
            download_events.progress_changed.emit()
            return

        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            path = DownloadManager._record_completed_download(download)
            if path:
                settings = DownloadSettings()
                should_open = meta.get("open_on_complete", False)
                should_open = should_open or (
                    settings.auto_open_media
                    and DownloadManager.supports_auto_open(
                        DownloadManager._safe_mime_type(download),
                        os.path.basename(path),
                    )
                )
                if should_open:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(path))

            DownloadManager._release_download(download)
            if path:
                download_events.completed.emit(path)
            DownloadManager._drain_queue()
            return

        if state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
            status = meta.get("terminal_override") or "cancelled"
            DownloadManager._record_terminal(download, status)
            DownloadManager._release_download(download)
            DownloadManager._drain_queue()
            return

        if state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            try:
                resumable = not download.isFinished()
            except RuntimeError:
                resumable = False

            if resumable:
                meta["status"] = "interrupted"
                if download in DownloadManager._queued_downloads:
                    DownloadManager._queued_downloads.remove(download)
                download_events.items_changed.emit()
                download_events.progress_changed.emit()
                DownloadManager._drain_queue()
                return

            DownloadManager._record_terminal(download, "interrupted")
            DownloadManager._release_download(download)
            DownloadManager._drain_queue()

    @staticmethod
    def _drain_queue():
        for download in tuple(DownloadManager._queued_downloads):
            if DownloadManager._meta(download) is None:
                DownloadManager._queued_downloads.remove(download)
                continue

            if (
                DownloadManager._active_download_count()
                >= DownloadManager.MAX_ACTIVE_DOWNLOADS
            ):
                break

            DownloadManager._begin_download(download)

    @staticmethod
    def _active_download_count():
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

        count = 0
        for download in tuple(DownloadManager._active_downloads):
            try:
                if (
                    download.state()
                    == QWebEngineDownloadRequest.DownloadState.DownloadInProgress
                    and not download.isPaused()
                ):
                    count += 1
            except RuntimeError:
                continue
        return count

    @staticmethod
    def _record_terminal(download, status):
        meta = DownloadManager._meta(download) or {}
        path = DownloadManager._download_path(download)
        try:
            reason = download.interruptReasonString() or ""
        except RuntimeError:
            reason = ""

        DownloadManager._terminal_records.insert(
            0,
            {
                "key": f"terminal-{time.monotonic_ns()}",
                "path": path,
                "name": os.path.basename(path) if path else _("Download"),
                "status": status,
                "received": DownloadManager._safe_int(
                    download,
                    "receivedBytes",
                    -1,
                ),
                "total": DownloadManager._safe_int(
                    download,
                    "totalBytes",
                    -1,
                ),
                "percent": DownloadManager._percent_for_download(download),
                "reason": reason,
                "resumable": False,
                "live": False,
                "sequence": meta.get("sequence", 0),
            },
        )
        del DownloadManager._terminal_records[
            DownloadManager.MAX_SESSION_RECORDS:
        ]
        download_events.items_changed.emit()

    @staticmethod
    def _release_download(download):
        if download in DownloadManager._queued_downloads:
            DownloadManager._queued_downloads.remove(download)
        if download in DownloadManager._active_downloads:
            DownloadManager._active_downloads.remove(download)

        DownloadManager._download_meta.pop(
            DownloadManager._download_key(download),
            None,
        )
        download_events.items_changed.emit()
        download_events.progress_changed.emit()

    @staticmethod
    def _record_completed_download(download):
        path = DownloadManager._download_path(download)
        if not path:
            return None

        recent = SettingsManager.get(
            DownloadManager._RECENT_DOWNLOADS_KEY,
            [],
        )
        if isinstance(recent, str):
            recent = [recent]
        elif not isinstance(recent, (list, tuple)):
            recent = []

        normalized = os.path.normcase(path)
        recent = [
            item
            for item in recent
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
    def download_items():
        items = []
        live_paths = set()

        live_downloads = sorted(
            tuple(DownloadManager._active_downloads),
            key=lambda item: (
                DownloadManager._meta(item) or {}
            ).get("sequence", 0),
            reverse=True,
        )
        for download in live_downloads:
            item = DownloadManager._snapshot(download)
            if item is None:
                continue
            items.append(item)
            if item["path"]:
                live_paths.add(os.path.normcase(item["path"]))

        items.extend(DownloadManager._terminal_records)

        terminal_paths = {
            os.path.normcase(item["path"])
            for item in DownloadManager._terminal_records
            if item.get("path")
        }
        for index, path in enumerate(DownloadManager.recent_downloads()):
            normalized = os.path.normcase(path)
            if normalized in live_paths or normalized in terminal_paths:
                continue
            items.append(
                {
                    "key": f"completed-{index}-{path}",
                    "path": path,
                    "name": os.path.basename(path),
                    "status": "completed",
                    "received": -1,
                    "total": -1,
                    "percent": 100,
                    "reason": "",
                    "resumable": False,
                    "live": False,
                    "sequence": -index,
                }
            )

        return items

    @staticmethod
    def _snapshot(download):
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

        meta = DownloadManager._meta(download)
        if meta is None:
            return None

        path = DownloadManager._download_path(download)
        received = DownloadManager._safe_int(download, "receivedBytes", -1)
        total = DownloadManager._safe_int(download, "totalBytes", -1)
        percent = DownloadManager._percent(received, total)

        status = meta.get("status", "requested")
        resumable = False
        reason = ""

        try:
            state = download.state()
            if download in DownloadManager._queued_downloads:
                status = "queued"
            elif (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadInProgress
            ):
                status = "paused" if download.isPaused() else "active"
            elif (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted
            ):
                status = "interrupted"
                resumable = not download.isFinished()
                reason = download.interruptReasonString() or ""
            elif (
                state
                == QWebEngineDownloadRequest.DownloadState.DownloadRequested
            ):
                status = "queued" if download in DownloadManager._queued_downloads else "requested"
        except RuntimeError:
            return None

        return {
            "key": DownloadManager._download_key(download),
            "path": path,
            "name": (
                os.path.basename(path)
                if path
                else DownloadManager._safe_file_name(download)
            ),
            "status": status,
            "received": received,
            "total": total,
            "percent": percent,
            "reason": reason,
            "resumable": resumable,
            "live": True,
            "sequence": meta.get("sequence", 0),
        }

    @staticmethod
    def item_snapshot(key):
        download = DownloadManager._find_download(key)
        if download is not None:
            return DownloadManager._snapshot(download)

        for record in DownloadManager._terminal_records:
            if record.get("key") == key:
                return dict(record)
        return None

    @staticmethod
    def active_downloads():
        return [
            item["path"]
            for item in DownloadManager.download_items()
            if item.get("live") and item.get("path")
        ]

    @staticmethod
    def progress_summary():
        count = 0
        received_total = 0
        expected_total = 0
        unknown_size = False

        for item in DownloadManager.download_items():
            if not item.get("live"):
                continue
            if item["status"] not in {
                "active",
                "paused",
                "queued",
                "interrupted",
                "requested",
            }:
                continue

            count += 1
            received = item.get("received", -1)
            total = item.get("total", -1)
            if total <= 0 or received < 0:
                unknown_size = True
                continue

            received_total += min(received, total)
            expected_total += total

        if count == 0:
            return 0, None
        if unknown_size or expected_total <= 0:
            return count, None

        percent = round((received_total * 100) / expected_total)
        return count, max(0, min(99, percent))

    @staticmethod
    def recent_downloads():
        recent = SettingsManager.get(
            DownloadManager._RECENT_DOWNLOADS_KEY,
            [],
        )
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
            SettingsManager.set(
                DownloadManager._RECENT_DOWNLOADS_KEY,
                valid,
            )
        return valid

    @staticmethod
    def clear_recent_downloads():
        SettingsManager.set(DownloadManager._RECENT_DOWNLOADS_KEY, [])
        DownloadManager._terminal_records.clear()
        download_events.items_changed.emit()

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
    def _emit_direct_activity(download):
        path = DownloadManager._download_path(download)
        if path:
            download_events.started.emit(path)

    @staticmethod
    def _download_key(download):
        return id(download)

    @staticmethod
    def _meta(download):
        return DownloadManager._download_meta.get(
            DownloadManager._download_key(download)
        )

    @staticmethod
    def _find_download(key):
        for download in tuple(DownloadManager._active_downloads):
            if DownloadManager._download_key(download) == key:
                return download
        return None

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
    def _safe_file_name(download):
        try:
            return (
                download.downloadFileName()
                or download.suggestedFileName()
                or _("Download")
            )
        except RuntimeError:
            return _("Download")

    @staticmethod
    def _safe_mime_type(download) -> str:
        try:
            return download.mimeType() or ""
        except RuntimeError:
            return ""

    @staticmethod
    def _safe_int(download, method_name, fallback):
        try:
            return int(getattr(download, method_name)())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return fallback

    @staticmethod
    def _percent_for_download(download):
        return DownloadManager._percent(
            DownloadManager._safe_int(download, "receivedBytes", -1),
            DownloadManager._safe_int(download, "totalBytes", -1),
        )

    @staticmethod
    def _percent(received, total):
        if total <= 0 or received < 0:
            return None
        return max(
            0,
            min(100, round((min(received, total) * 100) / total)),
        )

    @staticmethod
    def _normalize_download_file_name(download):
        file_name = DownloadNamingService.normalized_file_name(
            download.downloadFileName() or download.suggestedFileName(),
            download.mimeType(),
            download.url().toString(),
        )

        if file_name != download.downloadFileName():
            download.setDownloadFileName(file_name)

    @staticmethod
    def _set_initial_download_parameters(download) -> bool:
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
            logger.exception(
                "Failed to cancel a download with no valid target"
            )
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
