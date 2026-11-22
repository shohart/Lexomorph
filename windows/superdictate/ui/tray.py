"""System tray icon.

This is the Windows counterpart of the macOS menu bar item, and it is
what keeps the app alive: closing every window leaves the tray icon, the
keyboard hook and the loaded model in place.

The context menu mirrors the macOS 1.0.3 menu bar redesign:
* Start / Stop dictation
* Dedicated Text Processing section (live toggles for Correction, Rewrite +
  conditional Rewrite Style submenu with custom color swatches, Punctuation)
* Direct Overview / Settings / History links
* About Lexomorph directly above Quit
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

from .. import i18n, paths
from ..app import AppState
from ..version import VERSION
from . import icons
from .theme import palette

# None means "no badge": the idle state should look like the plain logo.
_STATE_COLORS: dict[AppState, str | None] = {
    AppState.STARTING: "#8e8e93",
    AppState.DOWNLOADING: "#8e8e93",
    AppState.LOADING: "#8e8e93",
    AppState.READY: None,
    AppState.RECORDING: "#ff453a",
    AppState.TRANSCRIBING: "#0a84ff",
    AppState.CORRECTING: "#bf5af2",
    AppState.FAILED: "#ff9f0a",
}

_BUILTIN_STYLE_COLORS: dict[str, str] = {
    "polish": "#0a84ff",
    "structured_task": "#34c759",
    "official": "#ff9f0a",
}


@lru_cache(maxsize=8)
def _artwork(size: int) -> QPixmap:
    source = QPixmap(str(paths.resource_path("assets", "Lexomorph.png")))
    if source.isNull():
        return QPixmap()
    return source.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def build_icon(badge: str | None = None, size: int = 64) -> QIcon:
    """The product mark, optionally with a state dot in the corner."""
    art = _artwork(size)
    if art.isNull():
        return QIcon()
    if badge is None:
        return QIcon(art)

    pixmap = QPixmap(art)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    diameter = size * 0.34
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(badge))
    painter.drawEllipse(
        QRectF(size - diameter, size - diameter, diameter, diameter))
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(self, controller, *, on_panel, on_settings, on_history, on_quit) -> None:
        super().__init__()
        self._controller = controller
        self._on_panel = on_panel
        self._on_settings = on_settings
        self._on_history = on_history
        self._on_quit = on_quit
        self._palette = palette()
        self._menu = QMenu()
        self._menu.aboutToShow.connect(self._rebuild_menu)
        self._toggle_action: QAction | None = None
        self._rebuild_menu()

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        controller.state_changed.connect(self._on_state_changed)
        self._apply_state(controller.state)

    def _rebuild_menu(self) -> None:
        from ..llm import RewriteStyle

        menu = self._menu
        menu.clear()
        muted = self._palette.text_muted
        state = self._controller.state
        settings = self._controller.settings

        toggle = QAction(
            icons.icon("mic", muted, 16),
            i18n.tr("tray_stop") if state is AppState.RECORDING else i18n.tr("tray_start"),
            menu,
        )
        toggle.setEnabled(state in (AppState.READY, AppState.RECORDING))
        toggle.triggered.connect(self._toggle_dictation)
        menu.addAction(toggle)
        self._toggle_action = toggle

        # Dedicated Text Processing section (live toggles + conditional Rewrite Style submenu)
        menu.addSeparator()

        corr_action = QAction(i18n.tr("tray_correction"), menu)
        corr_action.setCheckable(True)
        corr_action.setChecked(bool(settings.correction_enabled))
        corr_action.triggered.connect(lambda _=False: self._controller.toggle_correction())
        menu.addAction(corr_action)

        rewrite_on = bool(settings.rewrite_enabled)
        rewrite_action = QAction(i18n.tr("tray_rewrite"), menu)
        rewrite_action.setCheckable(True)
        rewrite_action.setChecked(rewrite_on)
        rewrite_action.triggered.connect(lambda _=False: self._controller.toggle_rewrite())
        menu.addAction(rewrite_action)

        if rewrite_on:
            style_menu = QMenu(i18n.tr("tray_rewrite_style"), menu)
            style_menu.setIcon(icons.icon("sparkles", muted, 16))
            config = settings.rewrite_config()
            active_id = config.custom_style_id or config.style.value

            for builtin in RewriteStyle:
                act = QAction(
                    icons.swatch(_BUILTIN_STYLE_COLORS.get(builtin.value, "#0a84ff"), 12),
                    i18n.tr(f"rewrite_style_{builtin.value}"),
                    style_menu,
                )
                act.setCheckable(True)
                act.setChecked(active_id == builtin.value)
                act.triggered.connect(
                    lambda _=False, sid=builtin.value: self._controller.activate_rewrite_style(sid)
                )
                style_menu.addAction(act)

            custom_styles = self._controller.styles.all() if hasattr(self._controller, "styles") else []
            if custom_styles:
                style_menu.addSeparator()
                for style in custom_styles:
                    act = QAction(icons.swatch(style.color, 12), style.name, style_menu)
                    act.setCheckable(True)
                    act.setChecked(active_id == style.id)
                    act.triggered.connect(
                        lambda _=False, sid=style.id: self._controller.activate_rewrite_style(sid)
                    )
                    style_menu.addAction(act)

            menu.addMenu(style_menu)

        punct_action = QAction(i18n.tr("tray_punctuation"), menu)
        punct_action.setCheckable(True)
        punct_action.setChecked(bool(settings.punctuation_enabled))
        punct_action.triggered.connect(lambda _=False: self._controller.toggle_punctuation())
        menu.addAction(punct_action)

        menu.addSeparator()
        for icon_name, label_key, handler in (
            ("sliders", "tray_open_panel", self._on_panel),
            ("settings", "tray_settings", self._on_settings),
            ("history", "tray_history", self._on_history),
        ):
            action = QAction(icons.icon(icon_name, muted, 16), i18n.tr(label_key), menu)
            action.triggered.connect(lambda _=False, h=handler: h())
            menu.addAction(action)

        menu.addSeparator()
        about_action = QAction(icons.icon("info", muted, 16), i18n.tr("tray_about"), menu)
        about_action.triggered.connect(self._show_about)
        menu.addAction(about_action)

        quit_action = QAction(icons.icon("close", muted, 16), i18n.tr("tray_quit"), menu)
        quit_action.triggered.connect(lambda _=False: self._on_quit())
        menu.addAction(quit_action)

    def _show_about(self) -> None:
        QMessageBox.information(
            None,
            i18n.tr("tray_about"),
            i18n.tr("about_text", version=VERSION),
        )

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_panel()

    def _toggle_dictation(self) -> None:
        if self._controller.state is AppState.RECORDING:
            self._controller.finish_recording(
                self._controller.settings.primary_completion_behavior)
        else:
            self._controller.begin_recording()

    def _on_state_changed(self, value: str) -> None:
        self._apply_state(AppState(value))

    def _apply_state(self, state: AppState) -> None:
        self.setIcon(build_icon(_STATE_COLORS.get(state)))
        label = {
            AppState.STARTING: "status_starting",
            AppState.DOWNLOADING: "status_downloading",
            AppState.LOADING: "status_loading",
            AppState.READY: "status_ready",
            AppState.RECORDING: "status_recording",
            AppState.TRANSCRIBING: "status_transcribing",
            AppState.CORRECTING: "status_correcting",
            AppState.FAILED: "status_failed",
        }.get(state, "status_starting")
        self.setToolTip(f"{i18n.tr('app_name')}: {i18n.tr(label)}")
        if self._toggle_action is not None:
            self._toggle_action.setText(
                i18n.tr("tray_stop") if state is AppState.RECORDING
                else i18n.tr("tray_start")
            )
            self._toggle_action.setEnabled(state in (AppState.READY, AppState.RECORDING))
