"""Tests for download settings, queue state and media handling."""

from pathlib import Path
import tempfile
import unittest

from PyQt6.QtCore import QSettings
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

from zapzap.core.config.settings.downloads import (
    DownloadBehavior,
    DownloadSettings,
    MultipleDownloadPermission,
)
from zapzap.core.config.settings_manager import SettingsManager
from zapzap.features.downloads.download_manager import DownloadManager


class TemporarySettingsTest(unittest.TestCase):

    def setUp(self):
        self._previous_settings = SettingsManager._settings
        self._temporary_directory = tempfile.TemporaryDirectory()
        settings_path = Path(self._temporary_directory.name) / "settings.ini"
        SettingsManager._settings = QSettings(
            str(settings_path),
            QSettings.Format.IniFormat,
        )

    def tearDown(self):
        SettingsManager._settings = self._previous_settings
        self._temporary_directory.cleanup()


class DownloadSettingsTests(TemporarySettingsTest):

    def test_defaults_preserve_existing_download_dialog(self):
        settings = DownloadSettings()

        self.assertEqual(settings.behavior, DownloadBehavior.DIALOG)
        self.assertFalse(settings.auto_open_media)

    def test_download_behavior_choices_are_persisted(self):
        settings = DownloadSettings()

        for behavior in (
            DownloadBehavior.DIALOG,
            DownloadBehavior.AUTOMATIC,
            DownloadBehavior.ASK_EVERY_TIME,
        ):
            settings.behavior = behavior
            self.assertEqual(DownloadSettings().behavior, behavior)

    def test_invalid_download_behavior_is_repaired_to_dialog(self):
        SettingsManager.set("downloads/behavior", "invalid")

        self.assertEqual(DownloadSettings().behavior, DownloadBehavior.DIALOG)
        self.assertEqual(
            SettingsManager.get("downloads/behavior"),
            DownloadBehavior.DIALOG,
        )

    def test_auto_open_media_is_persisted(self):
        settings = DownloadSettings()
        settings.auto_open_media = True

        self.assertTrue(DownloadSettings().auto_open_media)

    def test_multiple_download_permissions_default_to_ask(self):
        settings = DownloadSettings()

        self.assertEqual(
            settings.multiple_download_permission("https://example.com"),
            MultipleDownloadPermission.ASK,
        )

    def test_multiple_download_permissions_can_be_remembered_and_reset(self):
        settings = DownloadSettings()
        origin = "https://example.com"

        settings.set_multiple_download_permission(
            origin,
            MultipleDownloadPermission.ALLOW,
        )
        self.assertEqual(
            DownloadSettings().multiple_download_permission(origin),
            MultipleDownloadPermission.ALLOW,
        )

        settings.set_multiple_download_permission(
            origin,
            MultipleDownloadPermission.BLOCK,
        )
        self.assertEqual(
            DownloadSettings().multiple_download_permission(origin),
            MultipleDownloadPermission.BLOCK,
        )

        settings.clear_multiple_download_permissions()
        self.assertEqual(
            DownloadSettings().multiple_download_permission(origin),
            MultipleDownloadPermission.ASK,
        )


class FakeDownload:

    def __init__(
        self,
        received,
        total,
        *,
        state=QWebEngineDownloadRequest.DownloadState.DownloadInProgress,
        paused=False,
        name="file.bin",
        directory="/tmp",
        finished=False,
    ):
        self._received = received
        self._total = total
        self._state = state
        self._paused = paused
        self._name = name
        self._directory = directory
        self._finished = finished

    def state(self):
        return self._state

    def isPaused(self):
        return self._paused

    def isFinished(self):
        return self._finished

    def receivedBytes(self):
        return self._received

    def totalBytes(self):
        return self._total

    def downloadDirectory(self):
        return self._directory

    def downloadFileName(self):
        return self._name

    def suggestedFileName(self):
        return self._name

    def interruptReasonString(self):
        return ""


class DownloadQueueTests(unittest.TestCase):

    def setUp(self):
        self._previous_active = DownloadManager._active_downloads
        self._previous_queued = DownloadManager._queued_downloads
        self._previous_meta = DownloadManager._download_meta
        self._previous_terminal = DownloadManager._terminal_records

        DownloadManager._active_downloads = []
        DownloadManager._queued_downloads = []
        DownloadManager._download_meta = {}
        DownloadManager._terminal_records = []

    def tearDown(self):
        DownloadManager._active_downloads = self._previous_active
        DownloadManager._queued_downloads = self._previous_queued
        DownloadManager._download_meta = self._previous_meta
        DownloadManager._terminal_records = self._previous_terminal

    def track(self, download, origin="https://example.com", sequence=1):
        DownloadManager._active_downloads.append(download)
        DownloadManager._download_meta[id(download)] = {
            "origin": origin,
            "sequence": sequence,
            "status": "active",
            "open_on_complete": False,
            "terminal_override": None,
        }

    def test_progress_is_weighted_by_total_bytes(self):
        first = FakeDownload(50, 100, name="first.bin")
        second = FakeDownload(100, 300, name="second.bin")
        self.track(first, sequence=1)
        self.track(second, sequence=2)

        self.assertEqual(DownloadManager.progress_summary(), (2, 38))

    def test_unknown_size_returns_no_percentage(self):
        download = FakeDownload(10, -1)
        self.track(download)

        self.assertEqual(DownloadManager.progress_summary(), (1, None))

    def test_no_active_downloads_returns_empty_summary(self):
        self.assertEqual(DownloadManager.progress_summary(), (0, None))

    def test_same_origin_active_limit_matches_chromium_style_cap(self):
        self.assertEqual(DownloadManager.MAX_ACTIVE_PER_ORIGIN, 6)

        for index in range(6):
            self.track(
                FakeDownload(0, 100, name=f"file-{index}.bin"),
                origin="https://example.com",
                sequence=index,
            )

        self.track(
            FakeDownload(0, 100, name="other.bin"),
            origin="https://other.example",
            sequence=10,
        )

        self.assertEqual(
            DownloadManager._origin_active_count("https://example.com"),
            6,
        )
        self.assertEqual(
            DownloadManager._origin_active_count("https://other.example"),
            1,
        )

    def test_queued_item_is_exposed_as_queued(self):
        queued = FakeDownload(
            0,
            100,
            state=QWebEngineDownloadRequest.DownloadState.DownloadRequested,
            name="queued.pdf",
        )
        self.track(queued)
        DownloadManager._queued_downloads.append(queued)

        item = DownloadManager.item_snapshot(id(queued))

        self.assertIsNotNone(item)
        self.assertEqual(item["status"], "queued")
        self.assertEqual(item["percent"], 0)


class DownloadAutoOpenTypeTests(unittest.TestCase):

    def test_pdf_is_supported_by_mime_or_extension(self):
        self.assertTrue(
            DownloadManager.supports_auto_open("application/pdf", "file.bin")
        )
        self.assertTrue(
            DownloadManager.supports_auto_open("", "document.PDF")
        )

    def test_images_are_supported_by_mime_or_extension(self):
        self.assertTrue(
            DownloadManager.supports_auto_open("image/png", "file.bin")
        )
        self.assertTrue(
            DownloadManager.supports_auto_open("", "photo.jpg")
        )

    def test_other_file_types_are_not_auto_opened(self):
        self.assertFalse(
            DownloadManager.supports_auto_open("application/zip", "archive.zip")
        )
        self.assertFalse(
            DownloadManager.supports_auto_open("text/plain", "notes.txt")
        )


if __name__ == "__main__":
    unittest.main()
