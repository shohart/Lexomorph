"""Unified Control Panel & Settings window (Lexomorph 1.0.3 Windows overhaul).

Mirrors the macOS 1.0.3 unified sidebar window:
* Left sidebar with brand header, 8 navigation sections (Overview, Dictation,
  Text & Dictionary, AI Processing, Audio & Input, Appearance, System &
  Account, Statistics), live status pill, quick RU/EN toggle, and History.
* Right pane with zero scrollbars on all working pages: Overview uses a
  responsive 2-column grid, and every settings/statistics page adapts its
  lists, editors, and charts to the actual window size.
* Contextual staged footer bar appears only when settings have unsaved edits.

Closing this window leaves the tray icon and keyboard hook running.
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from typing import Optional

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import asr, i18n, paths
from ..app import AppState
from ..keynames import hotkey_name
from ..version import VERSION
from . import icons
from .settings_window import SettingsWindow, _page_header
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

_NAV_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("overview", "home", "nav_overview"),
    ("dictation", "keyboard", "nav_dictation"),
    ("text", "replace", "nav_text"),
    ("ai", "sparkles", "nav_ai"),
    ("audio", "mic", "nav_audio"),
    ("appearance", "palette", "nav_appearance"),
    ("system", "sliders", "nav_system"),
    ("statistics", "chart", "nav_statistics"),
)

_SECTION_ALIASES: dict[str, str] = {
    "overview": "overview",
    "hotkeys": "dictation",
    "dictation": "dictation",
    "corrections": "text",
    "text": "text",
    "postprocessing": "ai",
    "ai": "ai",
    "audio": "audio",
    "appearance": "appearance",
    "advanced": "system",
    "system": "system",
    "statistics": "statistics",
}


class StatusDot(QWidget):
    """A painted status dot with a subtle halo."""

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
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    return widget


def _card_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("CardTitle")
    return label


class ControlPanel(QMainWindow):
    def __init__(self, controller, open_settings=None, open_history=None) -> None:
        super().__init__()
        self._controller = controller
        self._open_settings = open_settings
        self._open_history = open_history
        self._palette = palette()
        self._syncing_modes = False
        self._current_section = "overview"
        self._settings_host: Optional[SettingsWindow] = None

        self.setWindowTitle(f"{i18n.tr('app_name')} {VERSION}")
        self.setMinimumSize(920, 620)
        self.resize(980, 650)
        self.setStyleSheet(stylesheet(self._palette))

        self._build_ui()

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

    # -- UI construction ----------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Plain")
        self.setCentralWidget(root)
        split = QHBoxLayout(root)
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)

        split.addWidget(self._build_sidebar())

        right = QWidget()
        right.setObjectName("Plain")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._outer_stack = QStackedWidget()
        self._outer_stack.addWidget(self._build_overview_page())
        self._settings_container = QWidget()
        self._settings_container.setObjectName("Plain")
        sc_layout = QVBoxLayout(self._settings_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(0)
        self._mount_settings_host()
        self._outer_stack.addWidget(self._settings_container)
        right_layout.addWidget(self._outer_stack, 1)

        right_layout.addWidget(self._build_staged_footer())
        split.addWidget(right, 1)

    def _mount_settings_host(self) -> None:
        layout = self._settings_container.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        host = SettingsWindow(
            self._controller.settings,
            self._controller.corrections,
            self._controller,
            self,
            embedded=True,
        )
        host.dirty_changed.connect(self._on_settings_dirty)
        host.saved.connect(self._on_settings_saved)
        layout.addWidget(host)
        self._settings_host = host

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setFixedWidth(206)

        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(12, 16, 12, 12)
        sb.setSpacing(4)

        # Brand header
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 2, 6, 10)
        brand.setSpacing(9)
        logo = QLabel()
        logo.setObjectName("Plain")
        art = QPixmap(str(paths.resource_path("assets", "Lexomorph.png")))
        if not art.isNull():
            logo.setPixmap(art.scaled(
                26, 26,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(0)
        name_lbl = QLabel(i18n.tr("app_name"))
        name_lbl.setStyleSheet("font-size: 14px; font-weight: 700; background: transparent;")
        ver_lbl = QLabel(f"v{VERSION}")
        ver_lbl.setObjectName("Caption")
        brand_text.addWidget(name_lbl)
        brand_text.addWidget(ver_lbl)
        brand.addWidget(logo)
        brand.addLayout(brand_text, 1)
        sb.addLayout(brand)

        # Navigation buttons
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}
        for idx, (sec_key, icon_name, label_key) in enumerate(_NAV_SECTIONS):
            btn = QPushButton(i18n.tr(label_key))
            btn.setObjectName("NavItem")
            btn.setCheckable(True)
            btn.setChecked(sec_key == self._current_section)
            btn.setIcon(icons.icon(icon_name, self._palette.text_muted, 16))
            btn.setIconSize(icons.icon_size(16))
            btn.clicked.connect(lambda _=False, k=sec_key: self.show_section(k))
            self._nav_group.addButton(btn, idx)
            self._nav_buttons[sec_key] = btn
            sb.addWidget(btn)

        sb.addStretch(1)

        divider = QFrame()
        divider.setObjectName("SidebarDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        sb.addWidget(divider)

        # Sidebar footer: live status + RU/EN toggle + History
        status_row = QHBoxLayout()
        status_row.setContentsMargins(6, 6, 6, 2)
        status_row.setSpacing(6)
        self._sidebar_dot = StatusDot()
        self._sidebar_status = QLabel(i18n.tr("status_starting"))
        self._sidebar_status.setObjectName("Caption")
        status_row.addWidget(self._sidebar_dot)
        status_row.addWidget(self._sidebar_status, 1)
        sb.addLayout(status_row)

        footer_actions = QHBoxLayout()
        footer_actions.setContentsMargins(4, 2, 4, 0)
        footer_actions.setSpacing(6)

        lang_bar = QWidget()
        lang_bar.setObjectName("SegBar")
        lang_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lang_row = QHBoxLayout(lang_bar)
        lang_row.setContentsMargins(2, 2, 2, 2)
        lang_row.setSpacing(2)
        cur_lang = i18n.language()
        for code, title in (("ru", "RU"), ("en", "EN")):
            lbtn = QPushButton(title)
            lbtn.setObjectName("SegBtn")
            lbtn.setCheckable(True)
            lbtn.setChecked(cur_lang == code)
            lbtn.setStyleSheet("padding: 3px 8px; font-size: 11px;")
            lbtn.clicked.connect(lambda _=False, c=code: self._switch_language(c))
            lang_row.addWidget(lbtn)
        footer_actions.addWidget(lang_bar)

        history_btn = QPushButton(i18n.tr("panel_history_short"))
        history_btn.setIcon(icons.icon("history", self._palette.text_muted, 14))
        history_btn.setIconSize(icons.icon_size(14))
        history_btn.setStyleSheet("padding: 5px 8px; font-size: 12px;")
        history_btn.clicked.connect(lambda: self._open_history() if self._open_history else None)
        footer_actions.addWidget(history_btn, 1)
        sb.addLayout(footer_actions)
        return sidebar

    def _build_staged_footer(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("FooterBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(18, 10, 18, 10)
        row.setSpacing(10)

        lbl = QLabel(i18n.tr("staged_unsaved"))
        lbl.setObjectName("Key")
        row.addWidget(lbl)
        row.addStretch(1)

        discard = QPushButton(i18n.tr("staged_discard"))
        discard.clicked.connect(self._discard_settings)
        row.addWidget(discard)

        apply_btn = QPushButton(i18n.tr("staged_apply"))
        apply_btn.setObjectName("Primary")
        apply_btn.setIcon(icons.icon("check", self._palette.accent_text, 15))
        apply_btn.setIconSize(icons.icon_size(15))
        apply_btn.clicked.connect(self._apply_staged_settings)
        row.addWidget(apply_btn)

        bar.setVisible(False)
        self._staged_footer = bar
        return bar

    # -- Overview page (no scrollbars, responsive 2-column grid) ------

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Plain")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        layout.addWidget(_page_header("nav_overview", "subtitle_overview"))
        layout.addWidget(self._build_hero_service_card())

        mid = QHBoxLayout()
        mid.setSpacing(12)
        mid.addWidget(self._build_quick_modes_card(), 1)
        mid.addWidget(self._build_shortcuts_card(), 1)
        layout.addLayout(mid, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self._account_card = self._build_account_card()
        if self._account_card is not None:
            bottom.addWidget(self._account_card, 1)
        bottom.addWidget(self._build_mini_stats_card(), 1)
        layout.addLayout(bottom, 1)
        return page

    def _build_hero_service_card(self) -> QWidget:
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
        restart.setIcon(icons.icon("refresh", self._palette.text_muted, 15))
        restart.setIconSize(icons.icon_size(15))
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

        meta = QHBoxLayout()
        meta.setSpacing(14)
        for icon_name, label_key, attr in (
            ("sparkles", "panel_model", "_model_label"),
            ("cpu", "panel_compute", "_compute_label"),
            ("mic", "panel_microphone", "_microphone_label"),
        ):
            tile = QVBoxLayout()
            tile.setContentsMargins(0, 2, 0, 0)
            tile.setSpacing(3)
            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.setSpacing(5)
            glyph = QLabel()
            glyph.setPixmap(icons.pixmap(icon_name, self._palette.text_faint, 13))
            glyph.setStyleSheet("background: transparent;")
            key = QLabel(i18n.tr(label_key))
            key.setObjectName("CardTitle")
            top.addWidget(glyph)
            top.addWidget(key)
            top.addStretch(1)
            val = QLabel("-")
            val.setObjectName("Value")
            val.setWordWrap(True)
            val.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            tile.addLayout(top)
            tile.addWidget(val)
            meta.addLayout(tile, 1)
            setattr(self, attr, val)
        outer.addLayout(meta)
        return card

    def _build_quick_modes_card(self) -> QWidget:
        card = _card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        outer.addWidget(_card_title(i18n.tr("panel_quick_modes")))

        self._mode_correction = QCheckBox(i18n.tr("tray_correction"))
        self._mode_correction.toggled.connect(self._on_correction_toggled)
        outer.addWidget(self._mode_correction)

        rewrite_row = QHBoxLayout()
        rewrite_row.setContentsMargins(0, 0, 0, 0)
        rewrite_row.setSpacing(8)
        self._mode_rewrite = QCheckBox(i18n.tr("tray_rewrite"))
        self._mode_rewrite.toggled.connect(self._on_rewrite_toggled)
        rewrite_row.addWidget(self._mode_rewrite)
        rewrite_row.addStretch(1)
        self._mode_style_combo = QComboBox()
        self._mode_style_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._mode_style_combo.setMinimumContentsLength(8)
        self._mode_style_combo.setMinimumWidth(110)
        self._mode_style_combo.currentIndexChanged.connect(self._on_style_selected)
        rewrite_row.addWidget(self._mode_style_combo)
        outer.addLayout(rewrite_row)

        self._mode_punctuation = QCheckBox(i18n.tr("tray_punctuation"))
        self._mode_punctuation.toggled.connect(self._on_punctuation_toggled)
        outer.addWidget(self._mode_punctuation)
        outer.addStretch(1)
        return card

    def _build_shortcuts_card(self) -> QWidget:
        card = _card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        outer.addWidget(_card_title(i18n.tr("panel_shortcuts")))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
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
            glyph.setPixmap(icons.pixmap(icon_name, self._palette.text_faint, 15))
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
        outer.addLayout(grid)
        outer.addStretch(1)
        return card

    def _build_account_card(self) -> QWidget | None:
        sync = getattr(self._controller, "vocabulary_sync", None)
        if sync is None:
            return None
        card = _card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        outer.addWidget(_card_title(i18n.tr("panel_account_sync")))

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
        outer.addLayout(top)

        scope = QLabel(i18n.tr("panel_sync_scope"))
        scope.setObjectName("Caption")
        scope.setWordWrap(True)
        outer.addWidget(scope)
        outer.addStretch(1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._sync_now_btn = QPushButton(i18n.tr("sync_sync_now"))
        self._sync_now_btn.setIcon(icons.icon("refresh", self._palette.text_muted, 14))
        self._sync_now_btn.clicked.connect(self._trigger_sync_now)
        self._sync_manage_btn = QPushButton(i18n.tr("sync_sign_in"))
        self._sync_manage_btn.clicked.connect(lambda: self.show_section("system"))
        btns.addWidget(self._sync_now_btn)
        btns.addWidget(self._sync_manage_btn)
        btns.addStretch(1)
        outer.addLayout(btns)
        return card

    def _build_mini_stats_card(self) -> QWidget:
        card = _card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        outer.addWidget(_card_title(i18n.tr("panel_statistics")))

        self._today_stats_label = QLabel("")
        self._today_stats_label.setObjectName("Value")
        self._week_stats_label = QLabel("")
        self._week_stats_label.setObjectName("Caption")
        outer.addWidget(self._today_stats_label)
        outer.addWidget(self._week_stats_label)
        outer.addStretch(1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        open_stats = QPushButton(i18n.tr("panel_open_stats"))
        open_stats.setIcon(icons.icon("chart", self._palette.text_muted, 14))
        open_stats.clicked.connect(lambda: self.show_section("statistics"))
        btns.addWidget(open_stats)
        btns.addStretch(1)
        outer.addLayout(btns)
        return card

    # -- navigation & staged footer -----------------------------------

    def show_section(self, section: str | None) -> None:
        key = _SECTION_ALIASES.get(section or "overview", "overview")
        self._current_section = key
        btn = self._nav_buttons.get(key)
        if btn is not None:
            btn.setChecked(True)
        if key == "overview":
            self._outer_stack.setCurrentIndex(0)
        else:
            self._outer_stack.setCurrentIndex(1)
            if self._settings_host is not None:
                self._settings_host.select_section(key)

    def _on_settings_dirty(self, dirty: bool) -> None:
        self._staged_footer.setVisible(dirty)

    def _on_settings_saved(self) -> None:
        self._staged_footer.setVisible(False)
        self.refresh()

    def _discard_settings(self) -> None:
        self._staged_footer.setVisible(False)
        self._mount_settings_host()
        if self._current_section != "overview" and self._settings_host is not None:
            self._settings_host.select_section(self._current_section)

    def _apply_staged_settings(self) -> None:
        if self._settings_host is not None:
            self._settings_host.save_changes()

    def _switch_language(self, code: str) -> None:
        if code == i18n.language():
            return
        self._controller.settings.update_runtime({"interface_language": code})
        i18n.set_language(code)
        self._controller.apply_settings()
        target = self._current_section
        self._build_ui()
        self.show_section(target)
        self.refresh()

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
        status_label = i18n.tr(_STATE_LABELS.get(state, "status_starting"))
        model = getattr(self._controller, "_model", None)
        if (state is AppState.LOADING and model is not None
                and model.backend == asr.BACKEND_NPU):
            status_label = i18n.tr("status_loading_npu")
        color = self._state_color(state)

        self._status_text.setText(status_label)
        self._status_dot.set_color(color)
        self._sidebar_status.setText(status_label)
        self._sidebar_dot.set_color(color)

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
