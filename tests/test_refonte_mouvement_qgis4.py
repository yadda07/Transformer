# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Real Qt 6 interaction and paint assertions, with no profile or external data."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QSize, Qt
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from Transfomer.shared import icons, interface_config
from Transfomer.shared.compat import icon_pixmap
from Transfomer.widgets.fluent import (
    FluentButton, FluentTabWidget, StableStatus, apply_fluent_style, role_font,
)


class RefonteMouvementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QgsApplication([], True)
            cls.app.initQgis()

    def setUp(self):
        self.unhandled = []
        self.previous_hook = sys.excepthook
        sys.excepthook = lambda kind, value, tb: self.unhandled.append((kind, str(value)))
        self.system_motion = patch.object(interface_config, "windows_reduced_motion", return_value=False)
        self.system_motion.start()
        self.root = QWidget()
        self.root.resize(660, 500)
        self.root.interface_settings = interface_config.InterfaceSettings()
        layout = QVBoxLayout(self.root)
        self.button = FluentButton("Exécuter la recette", self.root, variant="primary", icon_name="play")
        self.status = StableStatus("Prêt", self.root)
        self.tabs = FluentTabWidget(self.root)
        for title in ("Règles", "Contrôle", "Exécutions"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addWidget(QLabel("Contenu de la page " + title))
            self.tabs.addTab(page, title)
        layout.addWidget(self.button)
        layout.addWidget(self.status)
        layout.addWidget(self.tabs)
        apply_fluent_style(self.root)
        self.root.show()
        self.app.processEvents()
        QTest.qWait(25)

    def tearDown(self):
        self.root.close()
        self.root.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.system_motion.stop()
        sys.excepthook = self.previous_hook
        self.assertEqual(self.unhandled, [])

    def stopped(self, animation):
        self.assertEqual(animation.state(), QAbstractAnimation.State.Stopped)

    def test_pointer_press_only_scales_painted_content_and_interrupts_cleanly(self):
        geometry = self.button.geometry()
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton)
        QTest.qWait(55)
        self.assertLess(self.button.contentScale, 1.)
        self.assertGreaterEqual(self.button.contentScale, .98)
        self.assertEqual(self.button.geometry(), geometry)
        self.assertFalse(self.button.grab().isNull())
        QTest.mouseRelease(self.button, Qt.MouseButton.LeftButton)
        QTest.qWait(35)
        before = self.button.contentScale
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton)
        self.assertAlmostEqual(self.button.contentScale, before, delta=.003)
        QTest.mouseRelease(self.button, Qt.MouseButton.LeftButton)
        QTest.qWait(210)
        self.assertEqual(self.button.geometry(), geometry)
        self.assertAlmostEqual(self.button.contentScale, 1.)
        self.stopped(self.button._press_animation)

    def test_keyboard_is_immediate_and_preserves_native_activation(self):
        calls = []
        self.button.clicked.connect(lambda: calls.append(True))
        self.button.setFocus()
        QTest.keyPress(self.button, Qt.Key.Key_Space)
        self.stopped(self.button._press_animation)
        QTest.keyRelease(self.button, Qt.Key.Key_Space)
        self.assertEqual(calls, [True])
        self.assertEqual(self.button.contentScale, 1.)
        self.assertFalse(self.button.grab().isNull())

    def test_reduced_motion_and_explicit_preference_settle_running_motion(self):
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton)
        QTest.qWait(30)
        self.root.setProperty("fluentReducedMotion", True)
        self.stopped(self.button._press_animation)
        QTest.mouseRelease(self.button, Qt.MouseButton.LeftButton)
        self.stopped(self.button._press_animation)
        self.root.setProperty("fluentReducedMotion", False)
        self.root.interface_settings.enable_animations = False
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton)
        self.stopped(self.button._press_animation)
        QTest.mouseRelease(self.button, Qt.MouseButton.LeftButton)
        with patch.object(interface_config, "windows_reduced_motion", return_value=True):
            self.root.interface_settings.enable_animations = True
            self.assertFalse(interface_config.animations_enabled(self.root.interface_settings))

    def test_hiding_or_resizing_releases_press_and_all_owned_animation_timers(self):
        QTest.mousePress(self.button, Qt.MouseButton.LeftButton)
        QTest.qWait(30)
        self.button.hide()
        self.assertFalse(self.button.isDown())
        self.assertEqual(self.button.contentScale, 1.)
        self.stopped(self.button._press_animation)
        self.button.show()
        self.button.setBusy(True)
        self.assertTrue(self.button.isBusy())
        self.assertFalse(self.button.isEnabled())
        self.assertTrue(self.button._busy_timer.isActive())
        hint = self.button.sizeHint()
        self.root.resize(710, 520)
        self.app.processEvents()
        self.assertTrue(self.button._busy_timer.isActive())
        self.assertEqual(self.button.sizeHint(), hint)
        self.root.hide()
        self.app.processEvents()
        self.assertFalse(self.button._busy_timer.isActive())
        self.root.show()
        self.app.processEvents()
        self.button.setBusy(False)
        self.assertTrue(self.button.isEnabled())
        self.button.setEnabled(False)
        self.button.setBusy(True)
        self.button.setBusy(False)
        self.assertFalse(self.button.isEnabled())

    def test_tabs_retarget_from_current_indicator_then_resize_and_keyboard_settle(self):
        bar = self.tabs.tabBar()
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
        QTest.qWait(50)
        current = bar._indicator
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(2).center())
        self.assertAlmostEqual(bar._indicator.x(), current.x(), delta=2)
        self.assertEqual(self.tabs.currentIndex(), 2)
        self.root.resize(740, 540)
        self.app.processEvents()
        self.stopped(bar._slide)
        self.assertEqual(bar._indicator, bar._target())
        bar.setFocus()
        QTest.keyClick(bar, Qt.Key.Key_Left)
        self.assertEqual(self.tabs.currentIndex(), 1)
        self.stopped(bar._slide)
        self.assertEqual(bar._indicator, bar._target())

    def test_status_keeps_its_rectangle_for_loading_success_and_error(self):
        hint, geometry = self.status.sizeHint(), self.status.geometry()
        button_geometry, tabs_geometry = self.button.geometry(), self.tabs.geometry()
        for text in ("Lecture en cours…", "Contrôle terminé : 50 objets lus.",
                     "Le contrôle a échoué. Corrigez le champ signalé puis relancez l’aperçu."):
            self.status.setText(text)
            self.app.processEvents()
            self.assertEqual(self.status.text(), text)
            self.assertEqual(self.status.sizeHint(), hint)
            self.assertEqual(self.status.geometry(), geometry)
            self.assertEqual(self.button.geometry(), button_geometry)
            self.assertEqual(self.tabs.geometry(), tabs_geometry)
        self.status.hide()
        self.stopped(self.status._fade)
        self.assertEqual(self.status._opacity, 1.)

    def test_native_surfaces_refresh_with_palette_and_keep_focus_and_role_fonts(self):
        before = self.root.grab()
        palette = QPalette(self.root.palette())
        palette.setColor(QPalette.ColorRole.Window, QColor("#19222a"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#29343c"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#eeeeee"))
        self.root.setPalette(palette)
        self.app.processEvents()
        after = self.root.grab()
        self.assertFalse(after.isNull())
        self.assertNotEqual(before.toImage(), after.toImage())
        self.assertGreater(role_font(self.root, "title").pointSizeF(), role_font(self.root).pointSizeF())
        self.button.setFocus()
        self.assertTrue(self.button.hasFocus())
        self.assertEqual(self.button.focusPolicy(), Qt.FocusPolicy.StrongFocus)

    def test_svg_optical_stroke_hidpi_and_live_palette_cache(self):
        path = str(Path(icons._SVG_DIR) / "device-floppy.svg")
        for size, stroke in ((16, "2.25"), (18, "2"), (20, "1.8"), (24, "1.5")):
            self.assertIn('stroke-width="' + stroke + '"', icons._read_svg_markup(path, "#123456", size))
        first = icons.icon("play")
        image = icon_pixmap(first, QSize(20, 20), 2.)
        self.assertEqual(image.width(), 40)
        self.assertEqual(image.devicePixelRatioF(), 2.)
        self.assertTrue(any(image.toImage().pixelColor(x, y).alpha() > 0
                            for y in range(image.height()) for x in range(image.width())))
        original = QPalette(self.app.palette())
        try:
            palette = QPalette(original)
            palette.setColor(QPalette.ColorRole.Highlight, QColor("#a62f64"))
            self.app.setPalette(palette)
            second = icons.icon("play")
            self.assertNotEqual(first.cacheKey(), second.cacheKey())
        finally:
            self.app.setPalette(original)
        for required_name in ("layers", "warning", "edit", "compare"):
            resolved = icons.icon(required_name)
            self.assertFalse(resolved.isNull(), required_name)
            disabled_px = icon_pixmap(resolved, QSize(20, 20), 2., icons.QIcon.Mode.Disabled)
            self.assertEqual(disabled_px.width(), 40)
        self.assertTrue(icons.icon("absent-icon").isNull())

    def test_animation_default_is_enabled_but_saved_false_still_wins(self):
        class Backend:
            def value(self, name, default=None):
                return "false" if name.endswith("/enable_animations") else default
        self.assertTrue(interface_config.InterfaceSettings().enable_animations)
        loaded = interface_config.InterfaceSettings().load(Backend())
        self.assertFalse(loaded.enable_animations)
        self.assertFalse(interface_config.animations_enabled(loaded))

    def test_checkable_button_keeps_selection_after_release_and_leave(self):
        self.root.setProperty("fluentReducedMotion", True)
        for variant in ("secondary", "primary"):
            for dark in (False, True):
                with self.subTest(variant=variant, dark=dark):
                    button = FluentButton("Options de nettoyage", self.root, variant=variant)
                    button.setCheckable(True)
                    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    button.resize(350, 42)
                    palette = QPalette(button.palette())
                    for role, color in ((QPalette.ColorRole.Button, "#29343c" if dark else "#f5f6f7"),
                                        (QPalette.ColorRole.Window, "#19222a" if dark else "#ffffff"),
                                        (QPalette.ColorRole.WindowText, "#eeeeee" if dark else "#17242d"),
                                        (QPalette.ColorRole.ButtonText, "#eeeeee" if dark else "#17242d"),
                                        (QPalette.ColorRole.Highlight, "#3189b0" if dark else "#09658d"),
                                        (QPalette.ColorRole.HighlightedText, "#ffffff")):
                        palette.setColor(role, QColor(color))
                    button.setPalette(palette)
                    button.show()
                    self.app.processEvents()
                    QCoreApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
                    before = button.grab().toImage()
                    geometry = button.geometry()
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                    QCoreApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
                    self.assertTrue(button.isChecked())
                    self.assertFalse(button.isDown())
                    selected = button.grab().toImage()
                    self.assertNotEqual(before.pixelColor(1, 21), selected.pixelColor(1, 21),
                                        "Le contour doit exprimer la sélection persistante")
                    if variant == "secondary":
                        self.assertNotEqual(before.pixelColor(330, 21), selected.pixelColor(330, 21))
                    button.setEnabled(False)
                    disabled = button.grab().toImage()
                    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                    self.assertTrue(button.isChecked())
                    self.assertNotEqual(selected, disabled)
                    self.assertEqual(button.geometry(), geometry)
                    button.hide()
                    button.deleteLater()


if __name__ == "__main__":
    unittest.main()
