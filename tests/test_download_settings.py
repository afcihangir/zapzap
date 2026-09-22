"""Tests for persisted download behavior and automatic media opening."""

from pathlib import Path
import tempfile
import unittest

from PyQt6.QtCore import QSettings

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
