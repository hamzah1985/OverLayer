import copy
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(os.name == "nt", "Native Windows overlay integration")
class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from overlayer.app import STYLE

        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        from overlayer.app import Controller
        from overlayer.settings import Store

        self.temp = tempfile.TemporaryDirectory()
        self.controller = Controller(Store(Path(self.temp.name) / "settings.json"))
        self.app.processEvents()

    def tearDown(self):
        self.controller.shutdown()
        self.app.removeNativeEventFilter(self.controller.hotkeys)
        self.controller.hide()
        self.controller.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_lock_sets_native_input_transparency(self):
        from overlayer import windows as win

        c = self.controller
        hwnd = int(c.overlay.winId())
        self.assertFalse(win.get_style(hwnd, -20) & 0x20)
        c.toggle_lock()
        self.app.processEvents()
        style = win.get_style(hwnd, -20)
        self.assertTrue(style & 0x20)
        self.assertTrue(style & 0x80000)
        self.assertTrue(style & 0x08000000)
        c.toggle_lock()
        self.assertFalse(win.get_style(hwnd, -20) & 0x20)

    def test_closing_free_controls_hides_guides_without_exiting(self):
        c = self.controller
        c.show()
        self.app.processEvents()
        c.close()
        self.app.processEvents()
        self.assertFalse(c.isVisible())
        self.assertFalse(c.overlay.isVisible())
        c.overlay.close()
        self.assertFalse(c.overlay.isVisible())
        c.show_panel()
        self.app.processEvents()
        self.assertTrue(c.isVisible())

    def test_closing_attached_controls_keeps_sticky_guides(self):
        c = self.controller
        c.target = 99
        c.show()
        c.close()
        self.assertFalse(c.isVisible())
        self.assertTrue(c.overlay.isVisible())
        c.target = None

    def test_hidden_controls_reopen_through_native_single_instance_message(self):
        from PySide6.QtTest import QTest
        from overlayer import windows as win

        c = self.controller
        c.show()
        c.hide()
        self.app.processEvents()
        self.assertTrue(win.request_existing_controls())
        QTest.qWait(100)
        self.assertTrue(c.isVisible())

    def test_closed_target_hides_guides_instead_of_leaking_to_desktop(self):
        from unittest.mock import patch
        from overlayer import windows as win

        c = self.controller
        c.target = 99
        with patch.object(win.user32, "IsWindow", return_value=False):
            c.follow_target()
        self.assertIsNone(c.target)
        self.assertFalse(c.overlay.isVisible())
        c.follow_target()
        self.assertFalse(c.overlay.isVisible())

    def test_emergency_hide_is_idempotent_and_timer_does_not_restore_guides(self):
        c = self.controller
        for _ in range(2):
            c.hide_overlay()
            c.follow_target()
            self.assertFalse(c.overlay.isVisible())

    def test_shutdown_cannot_be_undone_by_pending_follow_or_picker(self):
        c = self.controller
        c.shutdown()
        c.follow_target()
        c.draw_area()
        c.show_panel()
        self.assertFalse(c.overlay.isVisible())
        self.assertIsNone(c.picker)

    def test_saved_locked_frame_starts_hidden_until_user_requests_it(self):
        from overlayer.app import Controller
        from overlayer.settings import Store

        store = Store(Path(self.temp.name) / "locked.json")
        store.state["locked"] = True
        other = Controller(store)
        try:
            self.assertFalse(other.overlay.isVisible())
            other.toggle_overlay()
            self.assertTrue(other.overlay.isVisible())
        finally:
            other.shutdown()
            self.app.removeNativeEventFilter(other.hotkeys)
            other.deleteLater()

    def test_native_hotkey_message_hides_guides_and_restores_controls(self):
        import ctypes
        from ctypes import wintypes as W
        from PySide6.QtTest import QTest
        from overlayer import windows as win

        post = win.user32.PostThreadMessageW
        post.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]
        post.restype = W.BOOL
        thread = ctypes.windll.kernel32.GetCurrentThreadId()
        c = self.controller
        self.assertTrue(post(thread, 0x312, 6, 0))
        QTest.qWait(80)
        self.assertFalse(c.overlay.isVisible())
        c.hide()
        self.assertTrue(post(thread, 0x312, 3, 0))
        QTest.qWait(80)
        self.assertTrue(c.isVisible())

    def test_taskbar_relaunch_icon_and_name_are_explicit_and_cleaned_up(self):
        from overlayer import taskbar

        c = self.controller
        self.assertTrue(c.taskbar_configured)
        properties = taskbar.WindowProperties(int(c.winId()))
        try:
            self.assertEqual(properties.get(5), taskbar.APP_ID)
            self.assertEqual(properties.get(4), "OverLayer")
            self.assertTrue(properties.get(3).endswith("overlayer.ico,0"))
            self.assertIn("run.py", properties.get(2))
            c.shutdown()
            for pid in (2, 3, 4, 5):
                self.assertIsNone(properties.get(pid))
        finally:
            properties.close()

    def test_drag_on_each_monitor_keeps_exact_selection_size_and_position(self):
        from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QWidget

        c = self.controller
        for screen in self.app.screens():
            c.draw_area()
            self.app.processEvents()
            surface = next(s for s in c.picker.surfaces if s.screen() == screen)
            self.assertEqual(surface.geometry(), screen.geometry())
            self.assertEqual(surface.devicePixelRatioF(), screen.devicePixelRatio())
            start, end = QPoint(40, 60), QPoint(540, 360)
            expected = QRect(
                surface.mapToGlobal(start).x(), surface.mapToGlobal(start).y(), 500, 300
            )

            def event(kind, point, button):
                return QMouseEvent(
                    kind,
                    QPointF(point),
                    QPointF(surface.mapToGlobal(point)),
                    button,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )

            surface.mousePressEvent(
                event(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
            )
            self.assertIs(QWidget.mouseGrabber(), surface)
            for point in (QPoint(100, 100), QPoint(300, 200), end):
                surface.mouseMoveEvent(
                    event(QEvent.Type.MouseMove, point, Qt.MouseButton.NoButton)
                )
            self.assertEqual(surface.selection().size(), expected.size())
            surface.mouseReleaseEvent(
                event(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton)
            )
            self.app.processEvents()
            self.assertEqual(c.overlay.geometry(), expected)
            self.assertIsNone(QWidget.mouseGrabber())
            self.assertIsNone(c.picker)

    def test_picker_clamps_drag_and_keeps_clear_area_hit_testable(self):
        from PySide6.QtCore import QPoint

        c = self.controller
        c.draw_area()
        self.app.processEvents()
        surface = c.picker.surfaces[0]
        self.assertEqual(
            surface.bounded_point(QPoint(-200, 100000)), QPoint(0, surface.height())
        )
        surface.start = QPoint(30, 40)
        surface.current = QPoint(600, 400)
        image = surface.grab().toImage()
        ratio = surface.devicePixelRatioF()
        self.assertGreater(
            image.pixelColor(round(150 * ratio), round(150 * ratio)).alpha(), 0
        )
        c.picker.finish(None)

    def test_enter_locks_without_toggling_back_off(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        c = self.controller
        c.show_panel()
        self.app.processEvents()
        QTest.qWait(50)
        QTest.keyClick(c, Qt.Key.Key_Return)
        self.assertTrue(c.state["locked"])
        QTest.keyClick(c, Qt.Key.Key_Return)
        self.assertTrue(c.state["locked"])
        c.toggle_lock()
        c.overlay.activateWindow()
        self.app.processEvents()
        QTest.qWait(50)
        QTest.keyClick(c.overlay, Qt.Key.Key_Enter)
        self.assertTrue(c.state["locked"])

    def test_positions_autosave_and_restore_on_each_monitor(self):
        from PySide6.QtTest import QTest
        from overlayer.app import Controller
        from overlayer.settings import Store

        c = self.controller
        for screen_name in [screen.name() for screen in self.app.screens()]:
            screen = next(
                screen for screen in self.app.screens() if screen.name() == screen_name
            )
            area = screen.availableGeometry()
            c.show_panel()
            c.setGeometry(area.x() + 120, area.y() + 110, 500, 600)
            c.overlay.setGeometry(area.x() + 50, area.y() + 70, 760, 480)
            self.app.processEvents()
            QTest.qWait(650)
            panel_rect, overlay_rect = c.geometry(), c.overlay.geometry()
            loaded = Store(c.store.path)
            self.assertIn("panel_rect", loaded.ui)
            self.assertEqual(loaded.ui["overlay_screen"], screen.name())
            other = Controller(loaded)
            try:
                other.show_panel()
                self.app.processEvents()
                QTest.qWait(80)
                self.assertEqual(other.geometry(), panel_rect)
                self.assertEqual(other.overlay.geometry(), overlay_rect)
                for _ in range(3):
                    other.hide()
                    other.show_panel()
                    self.app.processEvents()
                    self.assertEqual(other.geometry(), panel_rect)
            finally:
                other.shutdown()
                self.app.removeNativeEventFilter(other.hotkeys)
                other.hide()
                other.deleteLater()

    def test_every_guide_renders_and_preset_restores(self):
        from overlayer.geometry import GUIDES

        c = self.controller
        for key in GUIDES:
            c.state["guides"] = [key]
            c.overlay.update()
            self.app.processEvents()
            self.assertFalse(c.overlay.grab().isNull(), key)
        value = copy.deepcopy(c.state)
        value.update(rotation=3, flip_h=True, locked=True)
        c.apply_preset(value)
        self.app.processEvents()
        self.assertEqual(c.state["rotation"], 3)
        self.assertTrue(c.state["locked"])
        c.save()
        self.assertTrue(c.store.path.exists())

    def test_control_panel_fits_without_horizontal_scrolling(self):
        from PySide6.QtWidgets import QScrollArea

        c = self.controller
        c.show()
        self.app.processEvents()
        self.assertEqual(c.findChild(QScrollArea).horizontalScrollBar().maximum(), 0)

    def test_show_hide_preserves_locked_style(self):
        from overlayer import windows as win

        c = self.controller
        c.toggle_lock()
        c.toggle_overlay()
        self.app.processEvents()
        self.assertFalse(c.overlay.isVisible())
        c.toggle_overlay()
        self.app.processEvents()
        self.assertTrue(c.overlay.isVisible())
        self.assertTrue(win.get_style(int(c.overlay.winId()), -20) & 0x20)

    def test_resize_uses_mouse_down_rect_without_accumulating_delta(self):
        from PySide6.QtCore import QPointF, QEvent, Qt
        from PySide6.QtGui import QMouseEvent

        overlay = self.controller.overlay
        overlay.setGeometry(100, 100, 600, 400)
        start = QPointF(699, 499)
        original = overlay.geometry()
        overlay.drag = (("resize", "rb"), start, original)
        for delta in (5, 10, 15, 20):
            event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(599 + delta, 399 + delta),
                start + QPointF(delta, delta),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            overlay.mouseMoveEvent(event)
        self.assertEqual(overlay.width(), 620)
        self.assertEqual(overlay.height(), 420)
        self.assertEqual(original.width(), 600)

    def test_shift_drag_moves_at_one_fifth_speed(self):
        from PySide6.QtCore import QPointF, QEvent, Qt
        from PySide6.QtGui import QMouseEvent

        overlay = self.controller.overlay
        overlay.setGeometry(100, 100, 600, 400)
        start = QPointF(699, 499)
        overlay.drag = (("resize", "rb"), start, overlay.geometry())
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(649, 449),
            start + QPointF(50, 50),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
        )
        overlay.mouseMoveEvent(event)
        self.assertEqual(overlay.width(), 610)
        self.assertEqual(overlay.height(), 410)

    def test_area_selection_commits_and_cancel_preserves_frame(self):
        from PySide6.QtCore import QRect

        c = self.controller
        c.draw_area()
        self.app.processEvents()
        self.assertFalse(c.overlay.isVisible())
        c.picker.finish(QRect(110, 130, 700, 450))
        self.app.processEvents()
        self.assertEqual(c.overlay.geometry(), QRect(110, 130, 700, 450))
        self.assertFalse(c.state["locked"])
        c.draw_area()
        c.picker.finish(None)
        self.app.processEvents()
        self.assertEqual(c.overlay.geometry(), QRect(110, 130, 700, 450))
        self.assertTrue(c.overlay.isVisible())

    def test_reverse_direction_selection_normalizes_rectangle(self):
        from PySide6.QtCore import QPoint, QRect
        from overlayer.picker import selection_rect

        self.assertEqual(
            selection_rect(QPoint(800, 600), QPoint(200, 100)),
            QRect(200, 100, 600, 500),
        )

    def test_eight_frame_points_offer_expected_resize_edges(self):
        from PySide6.QtCore import QPointF

        overlay = self.controller.overlay
        overlay.setGeometry(100, 100, 600, 400)
        for (x, y), edge in (
            ((7, 7), "lt"),
            ((300, 7), "t"),
            ((593, 7), "rt"),
            ((7, 200), "l"),
            ((593, 200), "r"),
            ((7, 393), "lb"),
            ((300, 393), "b"),
            ((593, 393), "rb"),
        ):
            self.assertEqual(overlay.hit_test(QPointF(x, y)), ("resize", edge))

    def test_follow_keeps_relative_frame_and_hides_for_minimized_target(self):
        from unittest.mock import patch
        from PySide6.QtCore import QRect
        from overlayer import windows as win

        c = self.controller
        c.target = 99
        c.overlay.setGeometry(200, 180, 600, 400)
        with patch.object(c, "logical_client_rect", return_value=(100, 100, 1000, 800)):
            c.capture_relative()
        with (
            patch.object(win.user32, "IsWindow", return_value=True),
            patch.object(win.user32, "GetForegroundWindow", return_value=99),
            patch.object(c, "logical_client_rect", return_value=(300, 200, 2000, 1600)),
        ):
            c.follow_target()
            self.assertEqual(c.overlay.geometry(), QRect(500, 360, 1200, 800))
            self.assertTrue(c.overlay.isVisible())
        with (
            patch.object(win.user32, "IsWindow", return_value=True),
            patch.object(c, "logical_client_rect", return_value=None),
        ):
            c.follow_target()
            self.assertFalse(c.overlay.isVisible())

    def test_escape_in_controls_offers_quit_and_cancel_keeps_overlay(self):
        from unittest.mock import patch
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QMessageBox

        c = self.controller
        c.show_panel()
        self.app.processEvents()
        QTest.qWait(50)
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ) as question:
            QTest.keyClick(c, Qt.Key.Key_Escape)
            self.app.processEvents()
            question.assert_called_once()
        self.assertFalse(c.quitting)
        self.assertTrue(c.overlay.isVisible())

    def test_reset_preserves_frame_lock_and_named_presets(self):
        from overlayer.settings import DEFAULTS

        c = self.controller
        c.overlay.setGeometry(110, 130, 700, 450)
        c.overlay.set_locked(True)
        c.state.update(thickness=4.0, color="#ffffff", guides=["spiral"], rotation=2)
        c.store.presets["My view"] = copy.deepcopy(c.state)
        preset = copy.deepcopy(c.store.presets["My view"])
        rect = c.overlay.geometry()
        c.reset_setup()
        self.assertEqual(c.overlay.geometry(), rect)
        self.assertTrue(c.state["locked"])
        self.assertEqual(c.state["thickness"], 1.25)
        self.assertEqual(c.state["color"], "#000000")
        self.assertEqual(c.state["guides"], DEFAULTS["guides"])
        self.assertEqual(c.store.presets["My view"], preset)

    def test_changes_autosave_and_label_reports_it(self):
        from PySide6.QtTest import QTest
        from overlayer.settings import Store

        c = self.controller
        c.change("thickness", 2.5)
        c.change("guides", ["spiral", "horizon"])
        self.assertEqual(c.saved_label.text(), "Saving…")
        QTest.qWait(650)
        saved = Store(c.store.path)
        self.assertEqual(saved.state["thickness"], 2.5)
        self.assertEqual(saved.state["guides"], ["spiral", "horizon"])
        self.assertIn("All changes saved", c.saved_label.text())

    def test_notice_is_transient_and_mode_banner_tracks_lock(self):
        from PySide6.QtTest import QTest

        c = self.controller
        c.notice("Hello", 60)
        self.assertEqual(c.status.text(), "Hello")
        QTest.qWait(150)
        self.assertEqual(c.status.text(), "")
        self.assertIn("ALIGNMENT", c.mode.text())
        c.notice("Still here")
        c.toggle_lock()
        self.assertIn("LOCKED", c.mode.text())
        self.assertEqual(c.status.text(), "Still here")

    def test_reset_can_be_undone_without_touching_frame_or_lock(self):
        c = self.controller
        c.state.update(thickness=4.0, color="#ffffff", guides=["spiral"], rotation=2)
        c.overlay.setGeometry(110, 130, 700, 450)
        c.reset_setup()
        self.assertEqual(c.state["thickness"], 1.25)
        self.assertTrue(c.undo_button.isVisibleTo(c))
        c.overlay.setGeometry(130, 150, 720, 460)
        c.overlay.set_locked(True)
        c.undo_button.click()
        self.assertEqual(c.state["thickness"], 4.0)
        self.assertEqual(c.state["guides"], ["spiral"])
        self.assertEqual(c.state["rotation"], 2)
        self.assertEqual(c.overlay.geometry().getRect(), (130, 150, 720, 460))
        self.assertTrue(c.state["locked"])
        self.assertFalse(c.undo_button.isVisibleTo(c))

    def test_guide_tiles_toggle_guides_and_sections_collapse_and_persist(self):
        from overlayer.settings import Store

        c = self.controller
        c.show()
        chip = c.guide_boxes["golden"]
        chip.click()
        self.assertIn("golden", c.state["guides"])
        chip.click()
        self.assertNotIn("golden", c.state["guides"])
        section = c.sections["refs"]
        self.assertFalse(section.is_expanded())
        section.header.click()
        self.assertTrue(section.body.isVisibleTo(c))
        c.save()
        self.assertTrue(Store(c.store.path).ui["sections"]["refs"])

    def test_section_titles_keep_their_ampersand(self):
        # A lone "&" would be consumed as a keyboard-accelerator marker.
        self.assertIn("&&", self.controller.sections["frame"].header.text())

    def test_frame_options_custom_ratio_halo_and_reference_transform(self):
        c = self.controller
        c.show()
        self.app.processEvents()
        self.assertFalse(c.custom_row.isVisible())
        c.aspect.setCurrentText("Custom")
        self.app.processEvents()
        self.assertTrue(c.custom_row.isVisible())
        c.aspect.setCurrentText("16:9")
        self.app.processEvents()
        self.assertFalse(c.custom_row.isVisible())
        c.aspect.setCurrentText("Custom")
        c.custom_w.setValue(21)
        c.custom_h.setValue(9)
        self.assertAlmostEqual(c.overlay.guide_rect().width() / c.overlay.guide_rect().height(), 21 / 9, places=2)
        c.extras["dim_outside"].setChecked(True)
        c.margin_pct.setValue(10)
        c.ref_scale.setValue(150)
        self.assertEqual(c.state["margin_pct"], 10)
        self.assertEqual(c.state["reference_scale"], 150)
        for halo in (True, False):
            c.extras["halo"].setChecked(halo)
            for locked in (False, True):
                c.state["margins"] = c.state["focal"] = True
                c.overlay.set_locked(locked)
                self.app.processEvents()
                self.assertFalse(c.overlay.grab().isNull())

    def test_color_swatches_and_icon_reflect_state(self):
        c = self.controller
        c.swatches["#e9bd78"].click()
        self.assertEqual(c.state["color"], "#e9bd78")
        self.assertIn("Custom…", c.color_button.text())
        c.set_color("#123456")
        self.assertIn("#123456".upper(), c.color_button.text())
        locked_icon = c.icons[True].pixmap(64, 64).toImage()
        plain_icon = c.icons[False].pixmap(64, 64).toImage()
        self.assertNotEqual(locked_icon, plain_icon)

    def test_arrow_keys_nudge_and_ctrl_arrows_resize_unlocked_frame(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        overlay = self.controller.overlay
        overlay.setGeometry(200, 200, 600, 400)
        QTest.keyClick(overlay, Qt.Key.Key_Right)
        QTest.keyClick(overlay, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(overlay.geometry().getRect(), (201, 210, 600, 400))
        QTest.keyClick(overlay, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(overlay.width(), 601)
        self.assertTrue(overlay.hud)
        overlay.set_locked(True)
        QTest.keyClick(overlay, Qt.Key.Key_Left)
        self.assertEqual(overlay.x(), 201)

    def test_drag_shows_size_hud_and_anchor_drag_keeps_grab_offset(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        c = self.controller
        overlay = c.overlay
        overlay.setGeometry(100, 100, 600, 400)
        c.state["guides"] = ["leading"]
        start = QPointF(699, 499)
        overlay.drag = (("resize", "rb"), start, overlay.geometry())
        overlay.mouseMoveEvent(
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(609, 409),
                start + QPointF(10, 10),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertIn("610 × 410", overlay.hud)
        # Grab a vanishing point 8 px off its centre, drag 40 px right.
        before = overlay.point_position(c.state["vp"])
        grab = before + QPointF(8, 0)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            grab,
            overlay.mapToGlobal(grab),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        overlay.mousePressEvent(press)
        self.assertEqual(overlay.drag[0], ("anchor", "vp"))
        move_to = grab + QPointF(40, 0)
        overlay.mouseMoveEvent(
            QMouseEvent(
                QEvent.Type.MouseMove,
                move_to,
                overlay.mapToGlobal(move_to),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        after = overlay.point_position(c.state["vp"])
        self.assertAlmostEqual(after.x() - before.x(), 40, delta=0.5)
        overlay.drag = None

    def test_following_stays_visible_for_other_windows_of_the_same_app(self):
        from unittest.mock import patch
        from overlayer import windows as win

        c = self.controller
        c.target = 99
        c.overlay.setGeometry(200, 180, 600, 400)
        pids = {99: 4242, 100: 4242, 101: 7}
        with (
            patch.object(c, "logical_client_rect", return_value=(100, 100, 1000, 800)),
            patch.object(win.user32, "IsWindow", return_value=True),
            patch.object(win, "window_pid", side_effect=lambda h: pids.get(h, 0)),
        ):
            c.capture_relative()
            for foreground, expected in ((99, True), (100, True), (101, False)):
                with patch.object(win.user32, "GetForegroundWindow", return_value=foreground):
                    c.follow_target()
                    self.assertEqual(c.overlay.isVisible(), expected, foreground)
        c.target = None

    def test_match_window_fits_client_area_and_keeps_following(self):
        from unittest.mock import patch

        c = self.controller
        c.target = 99
        with patch.object(c, "logical_client_rect", return_value=(50, 60, 1280, 720)):
            c.match_window()
            self.assertEqual(c.overlay.geometry().getRect(), (50, 60, 1280, 720))
            self.assertEqual(c.relative, (0.0, 0.0, 1.0, 1.0))
        c.target = None

    def test_auto_follow_attaches_to_saved_app_and_restores_frame(self):
        from unittest.mock import patch
        from overlayer.app import Controller
        from overlayer.settings import Store
        from overlayer import windows as win

        store = Store(Path(self.temp.name) / "auto.json")
        store.ui.update(
            auto_follow=True, follow_exe="Host.exe", relative=[0.1, 0.2, 0.5, 0.5]
        )
        store.state["locked"] = True
        with (
            patch.object(
                win, "windows", return_value=[(77, "Host window", "host.exe"), (78, "Other", "x.exe")]
            ),
            patch.object(win, "client_rect", return_value=(0, 0, 1600, 900)),
            patch.object(win.user32, "IsWindow", return_value=True),
            patch.object(win.user32, "GetForegroundWindow", return_value=77),
        ):
            other = Controller(store)
            try:
                self.assertEqual(other.target, 77)
                self.assertEqual(other.relative, (0.1, 0.2, 0.5, 0.5))
                self.assertTrue(other.wanted_visible)
            finally:
                other.target = None
                other.shutdown()
                self.app.removeNativeEventFilter(other.hotkeys)
                other.deleteLater()

    def test_explicit_detach_stops_auto_follow_but_closed_host_retries(self):
        c = self.controller
        c.store.ui.update(auto_follow=True, follow_exe="host.exe")
        c.target = 5
        c.detach()
        self.assertFalse(c.auto_pending)
        c.detach(manual=False)
        self.assertTrue(c.auto_pending)

    def test_preset_cycling_wraps_applies_and_keeps_following(self):
        c = self.controller
        c.cycle_preset(1)  # no presets yet
        self.assertIn("No presets", c.overlay.hud)
        for name, guide in (("A", "thirds"), ("B", "spiral"), ("C", "grid")):
            c.state["guides"] = [guide]
            c.overlay.setGeometry(100, 100, 500, 400)
            c.presets.setCurrentText(name)
            c.store.presets[name] = copy.deepcopy(c.state)
        c.refresh_presets()
        c.presets.setCurrentText("A")
        c.target = 99
        c.cycle_preset(1)
        self.assertEqual(c.state["guides"], ["spiral"])
        self.assertEqual(c.target, 99)
        c.cycle_preset(1)
        c.cycle_preset(1)
        self.assertEqual(c.state["guides"], ["thirds"])
        c.cycle_preset(-1)
        self.assertEqual(c.state["guides"], ["grid"])
        self.assertIn("C", c.overlay.hud)
        c.target = None

    def test_hotkeys_can_be_rebound_and_rejects_bad_or_duplicate_shortcuts(self):
        from PySide6.QtGui import QKeySequence
        from overlayer import keys

        c = self.controller
        edit = c.key_edits["draw_area"]
        edit.setKeySequence(QKeySequence("Ctrl+Shift+F7"))
        c.hotkey_edited("draw_area")
        self.assertEqual(c.store.hotkeys["draw_area"], "Ctrl+Shift+F7")
        edit.setKeySequence(QKeySequence("Ctrl+Alt+Q"))  # used by quit
        c.hotkey_edited("draw_area")
        self.assertEqual(c.store.hotkeys["draw_area"], "Ctrl+Shift+F7")
        self.assertIn("already used", c.status.text())
        edit.setKeySequence(QKeySequence("F7"))  # no modifier
        c.hotkey_edited("draw_area")
        self.assertEqual(c.store.hotkeys["draw_area"], "Ctrl+Shift+F7")
        c.restore_hotkeys()
        self.assertEqual(c.store.hotkeys, keys.DEFAULT_HOTKEYS)
        self.assertEqual(
            edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText),
            "Ctrl+Alt+A",
        )

    def test_recording_a_shortcut_pauses_global_hotkeys(self):
        c = self.controller
        c.hotkeys.registered[:] = c.hotkeys.registered or [1]
        c.hotkey_recording(True)
        self.assertEqual(c.hotkeys.registered, [])
        c.hotkey_recording(False)
        self.assertFalse(c.recording_keys)

    def test_window_list_shows_executable_and_prefers_known_creative_apps(self):
        from unittest.mock import patch
        from overlayer import windows as win

        c = self.controller
        entries = [
            (1, "Notes", "notepad.exe"),
            (2, "D5 Render - Scene", "d5render.exe"),
            (3, "Zed", ""),
        ]
        c.window_list.clear()
        with patch.object(win, "windows", return_value=entries):
            c.refresh_windows()
        self.assertEqual(c.window_list.currentData(), 2)
        self.assertIn("d5render.exe", c.window_list.currentText())
        self.assertEqual(c.window_list.itemText(2), "Zed")
        c.window_list.setCurrentIndex(0)
        with patch.object(win, "windows", return_value=entries):
            c.refresh_windows()
        self.assertEqual(c.window_list.currentData(), 1)  # keeps user's choice

    def test_reference_that_cannot_be_read_is_reported(self):
        from PySide6.QtTest import QTest

        c = self.controller
        bad = Path(self.temp.name) / "broken.png"
        bad.write_bytes(b"not an image")
        c.state["reference"] = str(bad)
        c.overlay.update()
        c.overlay.grab()
        QTest.qWait(50)
        self.assertIn("broken.png", c.status.text())

    def test_win32_helpers_for_process_names_and_keyboard_layout(self):
        from overlayer import windows as win

        hwnd = win.user32.GetForegroundWindow()
        self.assertTrue(win.host_active(hwnd) or hwnd is None)
        self.assertEqual(win.process_name(os.getpid()).lower()[:6], "python")
        self.assertIsInstance(win.altgr_conflict(ord("A")), bool)
        self.assertFalse(win.host_active(0))
