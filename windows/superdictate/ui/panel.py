"""The control panel (Overview).

Mirrors the macOS 1.0.3 Overview:
* Service status strip (ready/recording/loading + Restart + download progress)
* Runtime summary card (speech model, compute device, active microphone)
* Quick Modes card (live toggles for Correction, Rewrite + Style picker with
  color swatches, and Punctuation)
* Account & Sync card (signed-in status, Sync Now, Sign In/Settings shortcut,
  and full sync scope summary)
* Shortcuts card
* Compact Mini-Statistics card (Today + 7 days) with a button jumping straight
  to the full Statistics tab in Settings.

Closing this window leaves the tray icon and keyboard hook running.
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import asr, i18n
from ..app import AppState
from ..keynames import hotkey_name
from ..version import VERSION
from . import icons
from .stats import format_int
from .theme import palette, stylesheet

_STATE_LABELS = {
    AppState.STARTING: "status_starting",
    AppState.DOWNLOADING: "status_downloading",
    AppState.LOADING: "status_loading",
    AppState.READY: "status_ready",
    AppState.RECORDING: "status_recording",
    AppState.TRANSCRIBING: "status_transcribing",
    AppState.CORRECTING: "status_correcting",
    AppState.FAILED: "status_failed",
}

_BUILTIN_STYLE_COLORS: dict[str, str] = {
    "polish": "#0a84ff",
    "structured_task": "#34c759",
    "official": "#ff9f0a",
}


class StatusDot(QWidget):
    """A painted dot; the old text bullet inherited the label's font."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._color = QColor("#8e8e93")
        self._end: QColor | None = None
        self.setFixedSize(14, 14)

    def set_color(self, color: str, end: str | None = None) -> None:
        self._color = QColor(color)
        self._end = QColor(end) if end else None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        halo = QColor(self._color)
        halo.setAlpha(60)
        painter.setBrush(halo)
        painter.drawEllipse(0, 0, 14, 14)
        if self._end is not None:
            fill = QLinearGradient(QPointF(4, 4), QPointF(10, 10))
            fill.setColorAt(0.0, self._color)
            fill.setColorAt(1.0, self._end)
            painter.setBrush(fill)
        else:
            painter.setBrush(self._color)
        painter.drawEllipse(4, 4, 6, 6)
        painter.end()


def _card() -> QWidget:
    widget = QWidget()
    widget.setObjectName("Card")
    return widget


def _card_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("CardTitle")
    return label


class ControlPanel(QMainWindow):
    def __init__(self, controller, open_settings, open_history) -> None:
        super().__init__()
        self._controller = controller
        self._open_settings = open_settings
        self._open_history = open_history
        self._palette = palette()
        self._syncing_modes = False

        self.setWindowTitle(f"{i18n.tr('app_name')} {VERSION}")
        self.setMinimumSize(540, 560)
        self.resize(580, 700)
        self.setStyleSheet(stylesheet(self._palette))

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root_layout.addWidget(scroll, 1)

        central = QWidget()
        scroll.setWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_status_card())
        layout.addWidget(self._build_service_card())
        layout.addWidget(_card_title(i18n.tr("panel_quick_modes")))
        layout.addWidget(self._build_quick_modes_card())

        self._account_card = self._build_account_card()
        if self._account_card is not None:
            layout.addWidget(_card_title(i18n.tr("panel_account_sync")))
            layout.addWidget(self._account_card)

        layout.addWidget(_card_title(i18n.tr("panel_shortcuts")))
        layout.addWidget(self._build_shortcuts_card())
        layout.addWidget(_card_title(i18n.tr("panel_statistics")))
        layout.addWidget(self._build_mini_stats_card())
        layout.addStretch(1)

        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 10, 18, 14)
        footer_layout.setSpacing(6)
        footer_layout.addLayout(self._build_actions())
        root_layout.addWidget(footer)

        controller.state_changed.connect(lambda _: self.refresh())
        controller.progress_changed.connect(self._on_progress)
        controller.settings_applied.connect(self.refresh)
        if hasattr(controller, "custom_styles_changed"):
            controller.custom_styles_changed.connect(lambda _: self._refresh_modes())
        if hasattr(controller, "vocabulary_sync_status"):
            controller.vocabulary_sync_status.connect(self._on_sync_status)
        controller.device_changed.connect(self.refresh)
        controller.transcript_ready.connect(lambda _: self._refresh_mini_stats())

        self._usage_timer = QTimer(self)
        self._usage_timer.setInterval(15_000)
        self._usage_timer.timeout.connect(self._refresh_mini_stats)
        self._usage_timer.start()

        self.refresh()

    # -- helpers ------------------------------------------------------

    def _open_settings_tab(self, tab: str | None = None) -> None:
        if tab is None:
            self._open_settings()
            return
        try:
            self._open_settings(tab)
        except TypeError:
            self._open_settings()

    # -- layout -------------------------------------------------------

    def _build_status_card(self) -> QWidget:
        card = _card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        self._status_dot = StatusDot()
        self._status_text = QLabel(i18n.tr("status_starting"))
        self._status_text.setStyleSheet(
            "font-size: 15px; font-weight: 600; background: transparent;")
        restart = QPushButton(i18n.tr("panel_restart"))
        restart.setIcon(icons.icon("refresh", self._palette.text_muted, 16))
        restart.setIconSize(icons.icon_size(16))
        restart.clicked.connect(self._controller.reload_model)
        head.addWidget(self._status_dot)
        head.addWidget(self._status_text)
        head.addStretch(1)
        head.addWidget(restart)
        outer.addLayout(head)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        outer.addWidget(self._progress)
        return card

    def _build_service_card(self) -> QWidget:
        card = _card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(2, 1)
        rows = (
            ("sparkles", "panel_model", "_model_label"),
            ("cpu", "panel_compute", "_compute_label"),
            ("mic", "panel_microphone", "_microphone_label"),
        )
        for row, (icon_name, label_key, attribute) in enumerate(rows):
            glyph = QLabel()
            glyph.setPixmap(icons.pixmap(icon_name, self._palette.text_faint, 16))
            glyph.setStyleSheet("background: transparent;")
            key = QLabel(i18n.tr(label_key))
            key.setObjectName("Key")
            value = QLabel("-")
            value.setObjectName("Value")
            value.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
            value.setWordWrap(True)
            grid.addWidget(glyph, row, 0)
            grid.addWidget(key, row, 1)
            grid.addWidget(value, row, 2)
            setattr(self, attribute, value)
        outer.addLayout(grid)
        return card

    def _build_quick_modes_card(self) -> QWidget:
        card = _card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        self._mode_correction = QCheckBox(i18n.tr("tray_correction"))
        self._mode_correction.toggled.connect(self._on_correction_toggled)
        outer.addWidget(self._mode_correction)

        rewrite_row = QHBoxLayout()
        rewrite_row.setContentsMargins(0, 0, 0, 0)
        rewrite_row.setSpacing(10)
        self._mode_rewrite = QCheckBox(i18n.tr("tray_rewrite"))
        self._mode_rewrite.toggled.connect(self._on_rewrite_toggled)
        rewrite_row.addWidget(self._mode_rewrite)
        rewrite_row.addStretch(1)
        self._mode_style_combo = QComboBox()
        self._mode_style_combo.setMinimumWidth(180)
        self._mode_style_combo.currentIndexChanged.connect(self._on_style_selected)
        rewrite_row.addWidget(self._mode_style_combo)
        outer.addLayout(rewrite_row)

        self._mode_punctuation = QCheckBox(i18n.tr("tray_punctuation"))
        self._mode_punctuation.toggled.connect(self._on_punctuation_toggled)
        outer.addWidget(self._mode_punctuation)
        return card

    def _build_account_card(self) -> QWidget | None:
        sync = getattr(self._controller, "vocabulary_sync", None)
        if sync is None:
            return None
        card = _card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._sync_dot = StatusDot()
        top.addWidget(self._sync_dot)
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        self._sync_heading = QLabel("")
        self._sync_heading.setObjectName("Value")
        self._sync_detail = QLabel("")
        self._sync_detail.setObjectName("Caption")
        self._sync_detail.setWordWrap(True)
        info.addWidget(self._sync_heading)
        info.addWidget(self._sync_detail)
        top.addLayout(info, 1)

        self._sync_now_btn = QPushButton(i18n.tr("sync_sync_now"))
        self._sync_now_btn.setIcon(icons.icon("refresh", self._palette.text_muted, 15))
        self._sync_now_btn.clicked.connect(self._trigger_sync_now)
        top.addWidget(self._sync_now_btn)

        self._sync_manage_btn = QPushButton(i18n.tr("sync_sign_in"))
        self._sync_manage_btn.clicked.connect(lambda: self._open_settings_tab("corrections"))
        top.addWidget(self._sync_manage_btn)
        outer.addLayout(top)

        scope = QLabel(i18n.tr("panel_sync_scope"))
        scope.setObjectName("Caption")
        scope.setWordWrap(True)
        outer.addWidget(scope)
        return card

    def _build_shortcuts_card(self) -> QWidget:
        card = _card()
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(2, 1)

        self._shortcut_labels: dict[str, QLabel] = {}
        self._shortcut_keys: dict[str, QLabel] = {}
        rows = (
            ("mic", "panel_hotkey", "hotkey"),
            ("keyboard", "panel_hotkey_enter", "enter_hotkey"),
            ("clock", "panel_hotkey_history", "history_hotkey"),
        )
        for row, (icon_name, label_key, attribute) in enumerate(rows):
            glyph = QLabel()
            glyph.setPixmap(icons.pixmap(icon_name, self._palette.text_faint, 16))
            glyph.setStyleSheet("background: transparent;")
            key = QLabel(i18n.tr(label_key))
            key.setObjectName("Key")
            value = QLabel("-")
            value.setObjectName("Shortcut")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(glyph, row, 0)
            grid.addWidget(key, row, 1)
            grid.addWidget(value, row, 2, Qt.AlignmentFlag.AlignRight)
            self._shortcut_labels[attribute] = value
            self._shortcut_keys[attribute] = key
        return card

    def _build_mini_stats_card(self) -> QWidget:
        card = _card()
        outer = QHBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        self._today_stats_label = QLabel("")
        self._today_stats_label.setObjectName("Value")
        self._week_stats_label = QLabel("")
        self._week_stats_label.setObjectName("Caption")
        col.addWidget(self._today_stats_label)
        col.addWidget(self._week_stats_label)
        outer.addLayout(col, 1)

        open_stats = QPushButton(i18n.tr("panel_open_stats"))
        open_stats.setIcon(icons.icon("chart", self._palette.text_muted, 15))
        open_stats.clicked.connect(lambda: self._open_settings_tab("statistics"))
        outer.addWidget(open_stats)
        return card

    def _build_actions(self) -> QHBoxLayout:
        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self._settings_button = QPushButton(i18n.tr("tray_settings"))
        self._settings_button.setObjectName("Primary")
        self._settings_button.setIcon(
            icons.icon("settings", self._palette.accent_text, 16))
        self._settings_button.setIconSize(icons.icon_size(16))
        self._settings_button.clicked.connect(lambda: self._open_settings_tab(None))

        self._history_button = QPushButton(i18n.tr("tray_history"))
        self._history_button.setIcon(
            icons.icon("history", self._palette.text_muted, 16))
        self._history_button.setIconSize(icons.icon_size(16))
        self._history_button.clicked.connect(lambda: self._open_history())

        buttons.addWidget(self._settings_button)
        buttons.addWidget(self._history_button)
        buttons.addStretch(1)
        return buttons

    # -- quick mode actions -------------------------------------------

    def _on_correction_toggled(self, checked: bool) -> None:
        if self._syncing_modes:
            return
        if bool(self._controller.settings.correction_enabled) != checked:
            self._controller.toggle_correction()

    def _on_rewrite_toggled(self, checked: bool) -> None:
        if self._syncing_modes:
            return
        if bool(self._controller.settings.rewrite_enabled) != checked:
            self._controller.toggle_rewrite()
        self._mode_style_combo.setVisible(checked)

    def _on_style_selected(self, _index: int) -> None:
        if self._syncing_modes:
            return
        sid = str(self._mode_style_combo.currentData() or "")
        if sid:
            self._controller.activate_rewrite_style(sid)

    def _on_punctuation_toggled(self, checked: bool) -> None:
        if self._syncing_modes:
            return
        if bool(self._controller.settings.punctuation_enabled) != checked:
            self._controller.toggle_punctuation()

    def _trigger_sync_now(self) -> None:
        sync = getattr(self._controller, "vocabulary_sync", None)
        if sync is None:
            return
        self._sync_now_btn.setEnabled(False)
        threading.Thread(target=sync.sync_now, name="panel-sync-now", daemon=True).start()

    # -- refresh ------------------------------------------------------

    def _refresh_modes(self) -> None:
        from ..llm import RewriteStyle

        settings = self._controller.settings
        self._syncing_modes = True
        try:
            self._mode_correction.setChecked(bool(settings.correction_enabled))
            rewrite_on = bool(settings.rewrite_enabled)
            self._mode_rewrite.setChecked(rewrite_on)
            self._mode_punctuation.setChecked(bool(settings.punctuation_enabled))

            combo = self._mode_style_combo
            combo.blockSignals(True)
            combo.clear()
            for style in RewriteStyle:
                combo.addItem(
                    icons.swatch(_BUILTIN_STYLE_COLORS.get(style.value, "#0a84ff"), 12),
                    i18n.tr(f"rewrite_style_{style.value}"),
                    style.value,
                )
            if hasattr(self._controller, "styles"):
                for custom in self._controller.styles.all():
                    combo.addItem(icons.swatch(custom.color, 12), custom.name, custom.id)
            config = settings.rewrite_config()
            active = config.custom_style_id or config.style.value
            idx = combo.findData(active)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)
            combo.setVisible(rewrite_on)
        finally:
            self._syncing_modes = False

    def _on_sync_status(self, status) -> None:
        self._refresh_sync(status)
        self._refresh_mini_stats()

    def _refresh_sync(self, status=None) -> None:
        if self._account_card is None:
            return
        sync = getattr(self._controller, "vocabulary_sync", None)
        if sync is None:
            return
        st = status if status is not None else sync.status
        p = self._palette
        if st.signed_in:
            self._sync_heading.setText(i18n.tr("sync_signed_in_as", email=st.email))
            when = (time.strftime("%d.%m.%Y %H:%M", time.localtime(st.last_synced_at))
                    if st.last_synced_at else i18n.tr("sync_never"))
            if st.state == "syncing":
                detail = i18n.tr("sync_state_syncing")
                self._sync_dot.set_color(p.busy)
            elif st.error or st.state == "reauth":
                err = st.error or "unauthorized"
                detail = i18n.tr(f"sync_error_{err}")
                self._sync_dot.set_color(p.warning)
            else:
                detail = i18n.tr("sync_state_ok") + " · " + i18n.tr("sync_last", when=when)
                self._sync_dot.set_color(p.ok)
            self._sync_detail.setText(detail)
            self._sync_now_btn.setVisible(True)
            self._sync_now_btn.setEnabled(st.state != "syncing")
            self._sync_manage_btn.setText(i18n.tr("tray_settings"))
        else:
            self._sync_dot.set_color(p.text_faint)
            self._sync_heading.setText(i18n.tr("sync_title"))
            self._sync_detail.setText(i18n.tr("sync_new_account_note"))
            self._sync_now_btn.setVisible(False)
            self._sync_manage_btn.setText(i18n.tr("sync_sign_in"))

    def _refresh_mini_stats(self) -> None:
        usage = getattr(self._controller, "usage", None)
        if usage is None:
            return
        today = date.today()
        by_day = {d.day: d for d in usage.all_days()}
        today_row = by_day.get(today.isoformat())
        today_d = today_row.dictations if today_row else 0
        today_c = today_row.characters if today_row else 0
        week_d = week_c = 0
        for offset in range(7):
            row = by_day.get((today - timedelta(days=offset)).isoformat())
            if row:
                week_d += row.dictations
                week_c += row.characters
        self._today_stats_label.setText(
            i18n.tr("panel_today_summary", dicts=format_int(today_d), chars=format_int(today_c))
        )
        self._week_stats_label.setText(
            i18n.tr("panel_week_summary", dicts=format_int(week_d), chars=format_int(week_c))
        )

    def refresh(self) -> None:
        state = self._controller.state
        settings = self._controller.settings
        self._status_text.setText(i18n.tr(_STATE_LABELS.get(state, "status_starting")))
        self._status_dot.set_color(self._state_color(state))

        for attribute, label in self._shortcut_labels.items():
            label.setText(hotkey_name(getattr(settings, attribute), i18n.language()))
        alternate = settings.primary_completion_behavior.opposite
        self._shortcut_keys["enter_hotkey"].setText(i18n.tr(
            "panel_hotkey_enter" if alternate.presses_enter else "panel_hotkey_insert"))
        if not settings.alternate_completion_enabled:
            self._shortcut_labels["enter_hotkey"].setText("-")

        self._model_label.setText(i18n.tr(
            "settings_model_gigaam_v3"
            if settings.speech_model_profile == asr.PROFILE_GIGAAM_V3
            else "settings_model_parakeet_ultra"))
        model = getattr(self._controller, "_model", None)
        if (state is AppState.LOADING and model is not None
                and model.backend == asr.BACKEND_NPU):
            self._status_text.setText(i18n.tr("status_loading_npu"))
        if model is not None and model.active_providers:
            providers = ", ".join(model.active_providers).upper()
            self._compute_label.setText(
                providers if providers == "NPU" else f"{providers} · {model.threads}")
            self._compute_label.setToolTip(model.fallback_reason)
        else:
            self._compute_label.setText("-")
            self._compute_label.setToolTip("")
        self._microphone_label.setText(
            settings.input_device or i18n.tr("settings_device_default"))

        self._refresh_modes()
        self._refresh_sync()
        self._refresh_mini_stats()

    def _state_color(self, state: AppState) -> str:
        p = self._palette
        return {
            AppState.READY: p.ok,
            AppState.RECORDING: p.danger,
            AppState.TRANSCRIBING: p.busy,
            AppState.CORRECTING: "#bf5af2",
            AppState.FAILED: p.danger,
        }.get(state, p.text_faint)

    def _on_progress(self, progress) -> None:
        if progress.state is asr.State.DOWNLOADING and progress.total_bytes:
            self._progress.setVisible(True)
            self._progress.setRange(0, 100)
            self._progress.setValue(int(progress.fraction * 100))
            self._progress.setFormat(
                f"%p%  ({progress.downloaded_bytes // (1024 * 1024)} / "
                f"{progress.total_bytes // (1024 * 1024)} MB)"
            )
        elif progress.state is asr.State.LOADING:
            self._progress.setVisible(True)
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, 100)
            self._progress.setVisible(False)

    # -- window behaviour ---------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        event.ignore()
        self.hide()
