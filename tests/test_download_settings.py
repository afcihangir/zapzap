"""Tests for persisted download behavior and automatic media opening."""

from pathlib import Path
import tempfile
import unittest

from PyQt6.QtCore import QSettings
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest

from zapzap.core.config.settings.downloads import DownloadBehavior, DownloadSettings
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


class FakeDownload:

    def __init__(self, received, total):
        self._received = received
        self._total = total

    def state(self):
        return QWebEngineDownloadRequest.DownloadState.DownloadInProgress

    def receivedBytes(self):
        return self._received

    def totalBytes(self):
        return self._total


class DownloadProgressTests(unittest.TestCase):

    def setUp(self):
        self._previous_active = DownloadManager._active_downloads
        DownloadManager._active_downloads = []

    def tearDown(self):
        DownloadManager._active_downloads = self._previous_active

    def test_progress_is_weighted_by_total_bytes(self):
        DownloadManager._active_downloads = [
            FakeDownload(50, 100),
            FakeDownload(100, 300),
        ]

        self.assertEqual(DownloadManager.progress_summary(), (2, 38))

    def test_unknown_size_returns_no_percentage(self):
        DownloadManager._active_downloads = [
            FakeDownload(10, -1),
        ]

        self.assertEqual(DownloadManager.progress_summary(), (1, None))

    def test_no_active_downloads_returns_empty_summary(self):
        self.assertEqual(DownloadManager.progress_summary(), (0, None))


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
