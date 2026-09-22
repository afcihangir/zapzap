"""Download behavior settings domain."""

from __future__ import annotations

import logging

from zapzap.core.config.settings.base import BaseSettings


logger = logging.getLogger(__name__)


class DownloadBehavior:
    """Stable persisted identifiers for download handling."""

    DIALOG = "dialog"
    AUTOMATIC = "automatic"
    ASK_EVERY_TIME = "ask_every_time"

    VALUES = {DIALOG, AUTOMATIC, ASK_EVERY_TIME}


class MultipleDownloadPermission:
    """Stable permission values for repeated WhatsApp downloads."""

    ASK = "ask"
    ALLOW = "allow"
    BLOCK = "block"

    VALUES = {ASK, ALLOW, BLOCK}


class DownloadSettings(BaseSettings):
    """Semantic access to download behavior preferences."""

    _BEHAVIOR = ("downloads/behavior", DownloadBehavior.DIALOG)
    _AUTO_OPEN_MEDIA = ("downloads/auto_open_media", False)
    _MULTIPLE_DOWNLOAD_PERMISSION = (
        "downloads/whatsapp_multiple_download_permission",
        MultipleDownloadPermission.ASK,
    )

    @property
    def behavior(self) -> str:
        raw_value = self._get(self._BEHAVIOR)
        value = (
            raw_value
            if isinstance(raw_value, str)
            and raw_value in DownloadBehavior.VALUES
            else DownloadBehavior.DIALOG
        )
        if value != raw_value:
            logger.warning(
                "Invalid stored download behavior; replacing it with dialog"
            )
            self._set_str(self._BEHAVIOR, value)
        return value

    @behavior.setter
    def behavior(self, value: str) -> None:
        normalized = (
            value if value in DownloadBehavior.VALUES
            else DownloadBehavior.DIALOG
        )
        self._set_str(self._BEHAVIOR, normalized)

    @property
    def auto_open_media(self) -> bool:
        return self._get_bool(self._AUTO_OPEN_MEDIA)

    @auto_open_media.setter
    def auto_open_media(self, value: bool) -> None:
        self._set_bool(self._AUTO_OPEN_MEDIA, value)

    @property
    def multiple_download_permission(self) -> str:
        raw_value = self._get_str(self._MULTIPLE_DOWNLOAD_PERMISSION)
        if raw_value in MultipleDownloadPermission.VALUES:
            return raw_value

        self._set_str(
            self._MULTIPLE_DOWNLOAD_PERMISSION,
            MultipleDownloadPermission.ASK,
        )
        return MultipleDownloadPermission.ASK

    @multiple_download_permission.setter
    def multiple_download_permission(self, permission: str) -> None:
        normalized = (
            permission
            if permission in MultipleDownloadPermission.VALUES
            else MultipleDownloadPermission.ASK
        )
        self._set_str(self._MULTIPLE_DOWNLOAD_PERMISSION, normalized)

    def clear_multiple_download_permission(self) -> None:
        self.multiple_download_permission = MultipleDownloadPermission.ASK
