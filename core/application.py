"""Own mascot lifetimes, shared menus, and saved defaults; engines remain independent."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog, QMessageBox, QSystemTrayIcon

from config.characters import available_characters
from config.settings import StartupSettings, save_settings
from core.mascot import Mascot
from core.screen import DesktopLayout
from platforms.window_surfaces import WindowSurfaces
from platforms.windows import is_startup_enabled as _is_startup_enabled
from platforms.windows import set_startup_enabled as _set_startup_enabled
from behaviors.fall import FallBehavior
from ui.launcher import Launcher
from ui.tray import MascotTray


class MascotApplication(QObject):
    def __init__(self, app, root: Path, settings: StartupSettings, update_interval_ms: int = 16):
        super().__init__(app)
        self.app = app
        self.root = root
        self.settings_path = root / "config/settings.json"
        self.characters = available_characters(root / "characters")
        self.settings = settings
        self.update_interval_ms = update_interval_ms
        self.mascots = []
        self.hidden = False
        self._quitting = False
        self._settings_dialog = None
        self.desktop = DesktopLayout(self)
        self.window_surfaces = WindowSurfaces(self.desktop)
        app.setQuitOnLastWindowClosed(False)
        self.tray = MascotTray(self)
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self.tray_available:
            self.tray.show()
        app.aboutToQuit.connect(self.shutdown)

    def save_defaults(self, settings):
        self.settings = settings
        try:
            save_settings(self.settings_path, settings)
        except OSError as error:
            QMessageBox.warning(None, "Settings not saved", f"Settings work for this session, but could not be saved:\n{error}")

    def spawn(self, character=None, settings=None):
        startup = settings or self.settings
        if character is not None:
            startup = replace(startup, character=character)
        if startup.character not in self.characters:
            QMessageBox.warning(None, "Character unavailable", "Choose an available character in Settings.")
            return None
        try:
            mascot = Mascot(self.root / "characters" / startup.character, self.update_interval_ms,
                            startup_settings=startup, manager=self)
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(None, "Mascot could not start", str(error))
            return None
        self.mascots.append(mascot)
        mascot.closed.connect(self._forget)
        if self.hidden:
            mascot.pause()
        else:
            mascot.show()
        return mascot

    def spawn_another(self, mascot):
        settings = replace(mascot.startup_settings,
                           autonomous=mascot.behaviors.settings.get("autonomous", True),
                           start_position="random")
        return self.spawn(settings=settings)

    def remove(self, mascot):
        if mascot in self.mascots:
            mascot.close()

    def _forget(self, mascot):
        if mascot in self.mascots:
            self.mascots.remove(mascot)
        mascot.deleteLater()
        if not self.mascots and not self.tray_available and not self._quitting:
            self.app.quit()

    def change_character(self, mascot, character):
        if character == mascot.character_dir.name:
            return
        settings = replace(mascot.startup_settings, character=character,
                           autonomous=mascot.behaviors.settings.get("autonomous", True))
        replacement = self.spawn(settings=settings)
        if replacement is None:
            return
        replacement.physics.x, replacement.physics.y = mascot.physics.x, mascot.physics.y
        replacement.physics.vx, replacement.physics.vy = mascot.physics.vx, mascot.physics.vy
        replacement.direction = mascot.direction
        replacement.display = mascot.display
        replacement.screen_area = mascot.display.available
        replacement.resolve_collisions()
        replacement.behaviors._starting = False
        if replacement.grounded:
            replacement.behaviors.idle()
        else:
            replacement.behaviors.set(FallBehavior())
        replacement.move(round(replacement.physics.x), round(replacement.physics.y))
        replacement.render_frame()
        self.remove(mascot)

    def toggle_visibility(self):
        self.hidden = not self.hidden
        for mascot in self.mascots:
            mascot.pause() if self.hidden else mascot.resume()
        self.tray.visibility_action.setText("Show mascots" if self.hidden else "Hide mascots")

    def open_settings(self):
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = Launcher(self.root / "characters", initial_settings=self.settings, editing=True)
        self._settings_dialog = dialog
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.save_defaults(dialog.settings())
        finally:
            self._settings_dialog = None
            dialog.deleteLater()

    def is_startup_enabled(self) -> bool:
        return _is_startup_enabled()

    def set_startup_enabled(self, enabled: bool) -> None:
        try:
            _set_startup_enabled(enabled)
        except OSError as error:
            QMessageBox.warning(None, "Startup setting failed", str(error))

    def shutdown(self):
        self._quitting = True
        self.tray.hide()
        if self._settings_dialog is not None:
            self._settings_dialog.reject()
        for mascot in list(self.mascots):
            mascot.close()

    def quit(self):
        self.shutdown()
        self.app.quit()
