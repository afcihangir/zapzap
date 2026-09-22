"""Download behavior settings domain."""

from __future__ import annotations

import json
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
    """Stable site permission values for repeated downloads."""

    ASK = "ask"
    ALLOW = "allow"
    BLOCK = "block"

    VALUES = {ASK, ALLOW, BLOCK}


class DownloadSettings(BaseSettings):
    """Semantic access to download behavior preferences."""

    _BEHAVIOR = ("downloads/behavior", DownloadBehavior.DIALOG)
    _AUTO_OPEN_MEDIA = ("downloads/auto_open_media", False)
    _MULTIPLE_DOWNLOAD_PERMISSIONS = (
        "downloads/multiple_download_permissions",
        "{}",
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

    def _multiple_download_permissions(self) -> dict[str, str]:
        raw = self._get_str(self._MULTIPLE_DOWNLOAD_PERMISSIONS)
        try:
            value = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = {}

        if not isinstance(value, dict):
            value = {}

        cleaned = {
            str(origin): str(permission)
            for origin, permission in value.items()
            if str(permission) in {
                MultipleDownloadPermission.ALLOW,
                MultipleDownloadPermission.BLOCK,
            }
        }
        if cleaned != value:
            self._set_str(
                self._MULTIPLE_DOWNLOAD_PERMISSIONS,
                json.dumps(cleaned, ensure_ascii=False, sort_keys=True),
            )
        return cleaned

    def multiple_download_permission(self, origin: str) -> str:
        if not origin:
            return MultipleDownloadPermission.ASK
        return self._multiple_download_permissions().get(
            origin,
            MultipleDownloadPermission.ASK,
        )

    def set_multiple_download_permission(
        self,
        origin: str,
        permission: str,
    ) -> None:
        if not origin:
            return

        permissions = self._multiple_download_permissions()
        if permission in {
            MultipleDownloadPermission.ALLOW,
            MultipleDownloadPermission.BLOCK,
        }:
            permissions[origin] = permission
        else:
            permissions.pop(origin, None)

        self._set_str(
            self._MULTIPLE_DOWNLOAD_PERMISSIONS,
            json.dumps(permissions, ensure_ascii=False, sort_keys=True),
        )

    def clear_multiple_download_permissions(self) -> None:
        self._set_str(self._MULTIPLE_DOWNLOAD_PERMISSIONS, "{}")
