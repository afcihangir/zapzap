"""Native unread badges follow the aggregate tray counter and its preference."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from PyQt6.QtWidgets import QSystemTrayIcon

from qt_test_case import QtTestCase
from zapzap.features.tray.sys_tray_manager import SysTrayManager


class _FakeTimer:
    def __init__(self):
        self.active = False
        self.intervals = []

    def start(self, interval):
        self.active = True
        self.intervals.append(interval)

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active


class TrayActivationTests(QtTestCase):
    def setUp(self):
        self.manager = object.__new__(SysTrayManager)
        self.manager._activation_timer = _FakeTimer()
        self.manager._trayMenu = MagicMock()
        self.manager._trayMenu.isVisible.return_value = False
        self.manager._bound_window = MagicMock()

    @patch("zapzap.features.tray.sys_tray_manager.QApplication.instance")
    def test_single_click_schedules_menu_without_toggling(self, application):
        application.return_value.doubleClickInterval.return_value = 350

        self.manager._on_tray_activated(
            QSystemTrayIcon.ActivationReason.Trigger
        )

        self.assertTrue(self.manager._activation_timer.active)
        self.assertEqual(self.manager._activation_timer.intervals, [350])
        self.manager._bound_window.show_window.assert_not_called()
        self.manager._trayMenu.popup.assert_not_called()

    @patch("zapzap.features.tray.sys_tray_manager.QCursor.pos")
    def test_delayed_single_click_opens_menu(self, cursor_pos):
        position = object()
        cursor_pos.return_value = position

        self.manager._show_tray_menu()

        self.manager._trayMenu.popup.assert_called_once_with(position)
        self.manager._bound_window.show_window.assert_not_called()

    def test_double_click_cancels_pending_menu_and_toggles_once(self):
        self.manager._activation_timer.start(400)

        self.manager._on_tray_activated(
            QSystemTrayIcon.ActivationReason.DoubleClick
        )

        self.assertFalse(self.manager._activation_timer.active)
        self.manager._bound_window.show_window.assert_called_once_with()
        self.manager._trayMenu.popup.assert_not_called()
        self.manager._trayMenu.close.assert_not_called()

    def test_double_click_closes_visible_menu_before_toggling(self):
        self.manager._trayMenu.isVisible.return_value = True

        self.manager._on_tray_activated(
            QSystemTrayIcon.ActivationReason.DoubleClick
        )

        self.manager._trayMenu.close.assert_called_once_with()
        self.manager._bound_window.show_window.assert_called_once_with()

    @patch("zapzap.features.tray.sys_tray_manager.QCursor.pos")
    def test_context_click_only_opens_tray_menu(self, cursor_pos):
        position = object()
        cursor_pos.return_value = position

        self.manager._on_tray_activated(
            QSystemTrayIcon.ActivationReason.Context
        )

        self.manager._trayMenu.popup.assert_called_once_with(position)
        self.manager._bound_window.show_window.assert_not_called()
        self.assertFalse(self.manager._activation_timer.active)

    @patch("zapzap.features.tray.sys_tray_manager.QApplication.instance")
    def test_unknown_activation_uses_single_click_menu_path(self, application):
        application.return_value.doubleClickInterval.return_value = 300

        self.manager._on_tray_activated(
            QSystemTrayIcon.ActivationReason.Unknown
        )

        self.assertTrue(self.manager._activation_timer.active)
        self.assertEqual(self.manager._activation_timer.intervals, [300])
        self.manager._bound_window.show_window.assert_not_called()

    def test_middle_click_does_nothing(self):
        self.manager._on_tray_activated(
            QSystemTrayIcon.ActivationReason.MiddleClick
        )

        self.manager._bound_window.show_window.assert_not_called()
        self.manager._trayMenu.popup.assert_not_called()




class TaskbarBadgeTests(QtTestCase):
    def setUp(self):
        self.manager = object.__new__(SysTrayManager)
        self.manager._settings = SimpleNamespace(
            notification_counter_enabled=True, tray_icon_enabled=False)
        self.manager._tray = MagicMock()
        self.manager.current_icon = object()
        self.manager.number_notifications = 0
        self.application = MagicMock()
        patches = (
            patch.object(SysTrayManager, "_instance", self.manager),
            patch("zapzap.features.tray.sys_tray_manager.QApplication.instance",
                  return_value=self.application),
            patch("zapzap.features.tray.sys_tray_manager.TrayIcon.getIcon"),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_unread_updates_and_zero_reach_native_badge_with_tray_hidden(self):
        for count in (3, 8, 0):
            SysTrayManager.set_number_notifications(count)
        self.assertEqual(self.application.setBadgeNumber.call_args_list,
                         [call(3), call(8), call(0)])
        self.assertEqual(self.manager.number_notifications, 0)
        self.assertEqual(self.manager._tray.setIcon.call_count, 3)
        self.manager._tray.show.assert_not_called()

    def test_preference_refresh_clears_and_restores_current_count(self):
        SysTrayManager.set_number_notifications(5)
        self.manager._settings.notification_counter_enabled = False
        SysTrayManager.refresh()
        self.manager._settings.notification_counter_enabled = True
        SysTrayManager.refresh()
        self.assertEqual(self.application.setBadgeNumber.call_args_list,
                         [call(5), call(0), call(5)])

    def test_disabled_counter_keeps_new_unread_count_hidden(self):
        self.manager._settings.notification_counter_enabled = False
        SysTrayManager.set_number_notifications(9)
        self.application.setBadgeNumber.assert_called_once_with(0)
        self.assertEqual(self.manager.number_notifications, 9)

    def test_older_qt_still_updates_tray_without_badge_api(self):
        with patch("zapzap.features.tray.sys_tray_manager.QApplication.instance",
                   return_value=SimpleNamespace()):
            SysTrayManager.set_number_notifications(4)
        self.manager._tray.setIcon.assert_called_once()


if __name__ == "__main__":
    unittest.main()
