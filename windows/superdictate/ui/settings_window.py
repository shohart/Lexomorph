"""The settings window.

macOS puts the shortcuts, completion behaviour, capsule size, colours and
background behind the gear button, and (importantly) keeps every change
as a *draft* until "Save and restart" applies them together. That draft
model is preserved here: widgets mutate a local dict, and only Save writes
it back to :class:`~superdictate.settings.Settings` and asks the
controller to re-apply.

Windows-only additions live on the Advanced tab: the compute device (there
is no Neural Engine to default to) and the weight set, since the ONNX
model ships in two sizes.

Layout-wise every tab is a stack of titled cards, each card a two-column
grid of label and control, so related settings read as a group instead of
one long undifferentiated form.
"""

from __future__ import annotations

import html
import threading
import time
from typing import Any, Optional

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .. import asr, asr_hotwords, audio, hardware, i18n, vocabulary_hygiene
from ..prompt_overrides import STYLES as PROMPT_STYLES, prompt_key, system_prompt_key
from ..vocabulary import DraftEntry
from ..hotkeys import HotkeyChoice, TriggerMode
from ..keynames import hotkey_name
from ..settings import (
    DICTATION_LANGUAGES,
    AccentColor,
    CONTRAST_COLOR,
    ColorSpec,
    CompletionBehavior,
    HUDBackgroundStyle,
    HUDDisplayMode, HUDSize,
    PasteSuffix,
    Settings,
    TextStyle,
)
from ..textproc import PRESET_FILLERS
from ..updater import PeriodicChecker
from . import icons
from .recorder import ShortcutRecorderDialog
from .stats import StatsPanel
from .style_editor import CustomStylesBlock
from .rows import (HINT_NONE, HINT_OFF, HINT_ON, HINT_ROLE, PRIMARY_ROLE, SECONDARY_ROLE,
                   CorrectionRowDelegate)
from .theme import Palette, palette, stylesheet

# Four across: the filler words are short, and three columns made the list
# thirteen rows tall, which is most of the dialog for one setting.
FILLER_COLUMNS = 4
DROP_BUTTON_SIZE = 18


class ColorField(QWidget):
    """A colour, or two of them for a gradient.

    The eight presets that used to fill a combo box are still one click
    away inside the picker's own palette, but "розовый" is now whichever
    pink the user actually means rather than the one shipped in the enum.
    """

    def __init__(self, spec: ColorSpec, on_change, palette: Palette,
                 parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        self._spec = spec
        self._on_change = on_change
        self._palette = palette

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._start_button = QPushButton()
        self._start_button.clicked.connect(lambda: self._pick(is_end=False))
        self._end_button = QPushButton()
        self._end_button.clicked.connect(lambda: self._pick(is_end=True))

        self._gradient = QCheckBox(i18n.tr("settings_color_gradient"))
        self._gradient.setChecked(spec.is_gradient)
        self._gradient.toggled.connect(self._toggle_gradient)
        # Black on a light capsule, white on a dark one (macOS "Contrast").
        self._contrast = QCheckBox(i18n.tr("settings_color_contrast"))
        self._contrast.setChecked(spec.is_contrast)
        self._contrast.toggled.connect(self._toggle_contrast)

        row.addWidget(self._start_button, 1)
        row.addWidget(self._contrast)
        row.addWidget(self._gradient)
        row.addWidget(self._end_button, 1)
        self._refresh()

    def _refresh(self) -> None:
        contrast = self._spec.is_contrast
        self._start_button.setEnabled(not contrast)
        self._gradient.setEnabled(not contrast)
        if contrast:
            self._start_button.setText(i18n.tr("settings_color_contrast"))
            self._start_button.setIcon(icons.swatch("#808080", 13))
        else:
            self._start_button.setText(self._spec.start.upper())
            self._start_button.setIcon(icons.swatch(self._spec.start, 13))
        gradient = self._spec.is_gradient and not contrast
        self._end_button.setVisible(gradient)
        if gradient:
            self._end_button.setText(str(self._spec.end).upper())
            self._end_button.setIcon(icons.swatch(str(self._spec.end), 13))
        self._on_change(self._spec.to_json())

    def _toggle_gradient(self, enabled: bool) -> None:
        if enabled:
            # A gradient needs somewhere to go, and a second stop equal to
            # the first would just look like a broken picker.
            self._spec = ColorSpec(self._spec.start,
                                   self._spec.end or _shifted(self._spec.start))
        else:
            self._spec = ColorSpec(self._spec.start)
        self._refresh()

    def _toggle_contrast(self, enabled: bool) -> None:
        if enabled:
            self._remembered = self._spec
            self._spec = ColorSpec(CONTRAST_COLOR)
            self._gradient.setChecked(False)
        else:
            previous = getattr(self, "_remembered", None)
            self._spec = (previous if previous is not None and not previous.is_contrast
                          else ColorSpec("#ffffff"))
            self._gradient.setChecked(self._spec.is_gradient)
        self._refresh()

    def _pick(self, *, is_end: bool) -> None:
        current = QColor(self._spec.end if is_end else self._spec.start)
        chosen = QColorDialog.getColor(current, self,
                                       i18n.tr("settings_color_pick"))
        if not chosen.isValid():
            return
        value = chosen.name()
        self._spec = (ColorSpec(self._spec.start, value) if is_end
                      else ColorSpec(value, self._spec.end))
        self._refresh()


def _shifted(color: str) -> str:
    """A second stop far enough from the first to read as a gradient."""
    hue = QColor(color)
    return QColor.fromHsv((hue.hue() + 60) % 360 if hue.hue() >= 0 else 300,
                          max(80, hue.saturation()),
                          min(255, hue.value() + 20)).name()


class HintIcon(QLabel):
    """A question mark that explains the setting next to it on hover.

    The explanations used to sit under their settings as permanent grey
    paragraphs. Six of them turned a tab of switches into a page of prose,
    and the longest one (the text styles) described three modes the user
    had not chosen. The words are unchanged; they are one hover away now.
    """

    SIZE = 15

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Hint")
        self.setPixmap(icons.pixmap("help", palette().text_faint, self.SIZE, 1.7))
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._tip = ""
        self.set_text(text)

    def set_text(self, text: str) -> None:
        # Rich text on purpose: Qt only word-wraps a tooltip it considers
        # rich, and a four-line explanation on one line spans the screen.
        self._tip = f"<p style='margin:0'>{html.escape(text)}</p>"
        self.setToolTip(self._tip)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Shown by hand rather than left to Qt, whose wake-up delay is most
        # of a second: an icon whose only job is to be hovered should not
        # keep the reader waiting to find out what it says.
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height() + 2)),
                          self._tip, self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        QToolTip.hideText()
        super().leaveEvent(event)


def _with_hint(widget: QWidget, hint: QWidget, *, stretch: bool) -> QWidget:
    """Pair a control with its hint icon inside one grid cell."""
    holder = QWidget()
    # Named, and transparent by name: an unnamed QWidget inside a card takes
    # the window background from the stylesheet and paints a darker slab
    # across the row.
    holder.setObjectName("Hint")
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(widget, 1 if stretch else 0)
    if not stretch:
        row.addStretch(1)
    row.addWidget(hint, 0, Qt.AlignmentFlag.AlignVCenter)
    return holder


class Section(QWidget):
    """A titled card holding a two-column grid of settings."""

    def __init__(self, title: str, hint: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 13, 16, 14)
        outer.setSpacing(10)

        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        if hint:
            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            header.setSpacing(7)
            header.addWidget(heading)
            header.addWidget(HintIcon(hint), 0, Qt.AlignmentFlag.AlignVCenter)
            header.addStretch(1)
            outer.addLayout(header)
        else:
            outer.addWidget(heading)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(10)
        self.grid.setColumnStretch(1, 1)
        outer.addLayout(self.grid)
        self._row = 0

    def add_row(self, label: Optional[str], widget: QWidget,
                hint: Optional[QWidget] = None, *, stretch: int = 0) -> None:
        if hint is not None:
            widget = _with_hint(widget, hint, stretch=bool(label))
        if label:
            key = QLabel(label)
            key.setObjectName("Key")
            self.grid.addWidget(key, self._row, 0)
            self.grid.addWidget(widget, self._row, 1)
        else:
            self.grid.addWidget(widget, self._row, 0, 1, 2)
        if stretch > 0:
            self.grid.setRowStretch(self._row, stretch)
        self._row += 1


def _page(*sections: QWidget, stretch_last: bool = False) -> QWidget:
    """Arrange sections vertically without a scroll area.

    Windows' redesigned settings pages fit within the minimum window size
    and stretch proportionally when resized, avoiding nested scrollbars.
    """
    inner = QWidget()
    inner.setObjectName("Plain")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.setSpacing(12)
    for idx, section in enumerate(sections):
        is_last = idx == len(sections) - 1
        layout.addWidget(section, 1 if (stretch_last and is_last) else 0)
    if not stretch_last:
        layout.addStretch(1)
    return inner


def _page_header(title_key: str, subtitle_key: str) -> QWidget:
    box = QWidget()
    box.setObjectName("Plain")
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 4)
    col.setSpacing(2)
    title = QLabel(i18n.tr(title_key))
    title.setObjectName("PageTitle")
    sub = QLabel(i18n.tr(subtitle_key))
    sub.setObjectName("PageSubtitle")
    sub.setWordWrap(True)
    sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    col.addWidget(title)
    col.addWidget(sub)
    return box


def _segmented_bar(items: list[tuple[str, str]],
                   on_select) -> tuple[QWidget, QButtonGroup]:
    bar = QWidget()
    bar.setObjectName("SegBar")
    bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    row = QHBoxLayout(bar)
    row.setContentsMargins(3, 3, 3, 3)
    row.setSpacing(3)
    group = QButtonGroup(bar)
    group.setExclusive(True)
    for idx, (key, label_key) in enumerate(items):
        btn = QPushButton(i18n.tr(label_key))
        btn.setObjectName("SegBtn")
        btn.setCheckable(True)
        btn.setChecked(idx == 0)
        btn.setProperty("seg_key", key)
        btn.clicked.connect(lambda _=False, i=idx: on_select(i))
        group.addButton(btn, idx)
        row.addWidget(btn)
    holder = QWidget()
    holder.setObjectName("Plain")
    h = QHBoxLayout(holder)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(bar)
    h.addStretch(1)
    return holder, group


class _TabCompatShim:
    """Maps legacy 7-tab indices (used by selftest_vocab) to the new stack."""

    _LEGACY_MAP = {
        0: "dictation",
        1: "dictation",
        2: "appearance",
        3: "text",
        4: "ai",
        5: "system",
        6: "statistics",
    }

    def __init__(self, window: "SettingsWindow") -> None:
        self._window = window

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        key = self._LEGACY_MAP.get(index, "dictation")
        self._window.select_section(key)


class _SubmitLineEdit(QLineEdit):
    """Return submits this field only. A plain QLineEdit also lets the key
    reach the dialog, whose default button saves the settings and restarts."""

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SettingsWindow(QDialog):
    # A sign-in / sync / sign-out finished on its worker thread:
    # (kind, detail), kind "ok" | "created" | "error".
    _sync_done = Signal(str, str)
    dirty_changed = Signal(bool)
    saved = Signal()

    _SECTION_ALIASES = {
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

    def __init__(self, settings: Settings, corrections, controller, parent=None,
                 initial_tab: str | None = None, *, embedded: bool = False) -> None:
        super().__init__(parent)
        self._embedded = embedded
        self._dirty = False
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        else:
            self.setWindowTitle(i18n.tr("settings_title"))
            self.setMinimumSize(920, 620)
            self.resize(980, 650)

        self._settings = settings
        self._corrections = corrections
        self._controller = controller
        self._draft: dict[str, Any] = settings.snapshot()
        # "auto" (never chosen) shows as the language actually in use.
        self._draft["interface_language"] = settings.interface_language
        # The prompt overrides are synced; only what the user changes here is
        # handed to PromptOverrides on save (see _save).
        self._prompt_baseline = {style: str(self._draft.get(prompt_key(style)) or "")
                                 for style in PROMPT_STYLES}
        self._correction_prompt_baseline = str(
            self._draft.get(system_prompt_key("correction")) or "")
        self._palette = palette()
        if not embedded:
            self.setStyleSheet(stylesheet(self._palette))

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._nav_group: Optional[QButtonGroup] = None
        self._nav_buttons: dict[str, QPushButton] = {}
        self._section_keys: list[str] = []
        self._tab_indices: dict[str, int] = {}

        sections = (
            ("dictation", "keyboard", "nav_dictation", self._build_dictation_page),
            ("text", "replace", "nav_text", self._build_text_page),
            ("ai", "sparkles", "nav_ai", self._build_ai_page),
            ("audio", "mic", "nav_audio", self._build_audio_page),
            ("appearance", "palette", "nav_appearance", self._build_appearance_page),
            ("system", "sliders", "nav_system", self._build_system_page),
            ("statistics", "chart", "nav_statistics", self._build_statistics_page),
        )

        if not embedded:
            sidebar = QWidget()
            sidebar.setObjectName("Sidebar")
            sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            sidebar.setFixedWidth(206)
            sb_layout = QVBoxLayout(sidebar)
            sb_layout.setContentsMargins(12, 16, 12, 14)
            sb_layout.setSpacing(4)
            title_lbl = QLabel(i18n.tr("settings_title"))
            title_lbl.setObjectName("PageTitle")
            title_lbl.setContentsMargins(8, 0, 8, 8)
            sb_layout.addWidget(title_lbl)

            self._nav_group = QButtonGroup(self)
            self._nav_group.setExclusive(True)
            for idx, (sec_key, icon_name, label_key, _) in enumerate(sections):
                btn = QPushButton(i18n.tr(label_key))
                btn.setObjectName("NavItem")
                btn.setCheckable(True)
                btn.setChecked(idx == 0)
                btn.setIcon(icons.icon(icon_name, self._palette.text_muted, 16))
                btn.setIconSize(icons.icon_size(16))
                btn.clicked.connect(lambda _=False, k=sec_key: self.select_section(k))
                self._nav_group.addButton(btn, idx)
                self._nav_buttons[sec_key] = btn
                sb_layout.addWidget(btn)
            sb_layout.addStretch(1)
            root.addWidget(sidebar)

        right = QWidget()
        right.setObjectName("Plain")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 14, 18, 14)
        right_layout.setSpacing(10)

        self._stack = QStackedWidget()
        for sec_key, _, _, builder in sections:
            idx = self._stack.addWidget(builder())
            self._tab_indices[sec_key] = idx
            self._section_keys.append(sec_key)
        right_layout.addWidget(self._stack, 1)

        if not embedded:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
            )
            save = buttons.button(QDialogButtonBox.StandardButton.Save)
            save.setText(i18n.tr("settings_save_restart"))
            save.setObjectName("Primary")
            save.setIcon(icons.icon("check", self._palette.accent_text, 16))
            save.setIconSize(icons.icon_size(16))
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
                i18n.tr("settings_cancel"))
            buttons.accepted.connect(self._save)
            buttons.rejected.connect(self.reject)
            right_layout.addWidget(buttons)

        root.addWidget(right, 1)
        self._tabs = _TabCompatShim(self)
        if initial_tab:
            self.select_section(initial_tab)

    def select_section(self, key: str) -> None:
        canonical = self._SECTION_ALIASES.get(key, key)
        idx = self._tab_indices.get(canonical)
        if idx is None:
            return
        self._stack.setCurrentIndex(idx)
        btn = self._nav_buttons.get(canonical)
        if btn is not None:
            btn.setChecked(True)

    def _set_dirty(self, dirty: bool = True) -> None:
        if self._dirty != dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    def _update_draft(self, **kwargs) -> None:
        self._draft.update(kwargs)
        self._set_dirty(True)

    def save_changes(self) -> None:
        self._save()

    # -- section pages ------------------------------------------------

    def _build_dictation_page(self) -> QWidget:
        # Card 1 (full width): 2x2 tile grid for shortcuts + trigger mode so
        # long key names ("Shift + Правый Ctrl") never clip.
        keys_card = QWidget()
        keys_card.setObjectName("Card")
        keys_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        keys_outer = QVBoxLayout(keys_card)
        keys_outer.setContentsMargins(16, 13, 16, 14)
        keys_outer.setSpacing(10)
        keys_title = QLabel(i18n.tr("settings_tab_hotkeys"))
        keys_title.setObjectName("CardTitle")
        keys_outer.addWidget(keys_title)

        keys_grid = QGridLayout()
        keys_grid.setHorizontalSpacing(16)
        keys_grid.setVerticalSpacing(10)
        keys_grid.setColumnStretch(0, 1)
        keys_grid.setColumnStretch(1, 1)

        def _hotkey_btn(draft_key: str) -> QPushButton:
            choice = HotkeyChoice.from_json(self._draft[draft_key],
                                            getattr(self._settings, draft_key))
            btn = QPushButton(hotkey_name(choice, i18n.language()))
            btn.setIcon(icons.icon("keyboard", self._palette.text_muted, 15))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda: self._record_shortcut(draft_key, btn))
            return btn

        def _tile(header_widget: QWidget, control: QWidget) -> QWidget:
            box = QWidget()
            box.setObjectName("Plain")
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(5)
            v.addWidget(header_widget)
            v.addWidget(control)
            return box

        # Tile (0,0): Primary hotkey
        p_lbl = QLabel(i18n.tr("settings_primary_hotkey"))
        p_lbl.setObjectName("Key")
        self._hotkey_button = _hotkey_btn("hotkey")
        keys_grid.addWidget(_tile(p_lbl, self._hotkey_button), 0, 0)

        # Tile (0,1): Alternate completion checkbox + hotkey
        self._alternate_enabled = QCheckBox(i18n.tr("settings_alternate_enabled"))
        self._alternate_enabled.setChecked(bool(self._draft.get("alternate_completion_enabled")))
        self._alternate_enabled.toggled.connect(
            lambda value: self._update_draft(alternate_completion_enabled=value))
        alt_head = _with_hint(self._alternate_enabled,
                              HintIcon(i18n.tr("settings_alternate_hint")),
                              stretch=False)
        self._enter_hotkey_button = _hotkey_btn("enter_hotkey")
        self._enter_hotkey_button.setEnabled(self._alternate_enabled.isChecked())
        self._alternate_enabled.toggled.connect(self._enter_hotkey_button.setEnabled)
        keys_grid.addWidget(_tile(alt_head, self._enter_hotkey_button), 0, 1)

        # Tile (1,0): History hotkey
        h_lbl = QLabel(i18n.tr("settings_history_hotkey"))
        h_lbl.setObjectName("Key")
        h_head = _with_hint(h_lbl, HintIcon(i18n.tr("settings_history_hotkey_hint")),
                            stretch=False)
        self._history_hotkey_button = _hotkey_btn("history_hotkey")
        keys_grid.addWidget(_tile(h_head, self._history_hotkey_button), 1, 0)

        # Tile (1,1): Trigger mode
        t_lbl = QLabel(i18n.tr("settings_trigger_mode"))
        t_lbl.setObjectName("Key")
        self._trigger = QComboBox()
        self._trigger.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._trigger.setMinimumContentsLength(10)
        self._trigger.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for val, lbl_key in (
            (TriggerMode.TOGGLE.value, "settings_trigger_toggle"),
            (TriggerMode.HOLD.value, "settings_trigger_hold"),
        ):
            self._trigger.addItem(i18n.tr(lbl_key), val)
        t_idx = self._trigger.findData(str(self._draft.get("trigger_mode", "")))
        self._trigger.setCurrentIndex(t_idx if t_idx >= 0 else 0)
        self._trigger.currentIndexChanged.connect(
            lambda _: self._update_draft(trigger_mode=self._trigger.currentData()))
        keys_grid.addWidget(_tile(t_lbl, self._trigger), 1, 1)

        keys_outer.addLayout(keys_grid)

        # Row 2: Two equal-height cards side by side (3 rows each)
        behaviour = Section(i18n.tr("settings_section_behaviour"))
        self._completion = self._combo(
            behaviour, "settings_completion", "primary_completion_behavior",
            [(CompletionBehavior.INSERT.value, i18n.tr("settings_completion_insert")),
             (CompletionBehavior.INSERT_AND_ENTER.value,
              i18n.tr("settings_completion_enter"))],
        )
        self._enter_delay = QSpinBox()
        self._enter_delay.setRange(0, 500)
        self._enter_delay.setSingleStep(10)
        self._enter_delay.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._enter_delay.setValue(int(self._draft["enter_delay_milliseconds"]))
        self._enter_delay.valueChanged.connect(
            lambda value: self._update_draft(enter_delay_milliseconds=value))
        behaviour.add_row(i18n.tr("settings_enter_delay"), self._enter_delay)
        limits = [("off", i18n.tr("settings_history_off"))]
        limits += [(value, i18n.tr("settings_history_last", n=value))
                   for value in ("1", "5", "10")]
        self._history_limit = self._combo(
            behaviour, "settings_history_limit", "recent_transcript_limit", limits)

        recognition = Section(i18n.tr("settings_section_recognition"))
        self._language = self._combo(
            recognition, "settings_language", "dictation_language",
            [(code, label) for code, label in DICTATION_LANGUAGES],
        )
        self._suffix = self._combo(
            recognition, "settings_paste_suffix", "paste_suffix",
            [(PasteSuffix.SPACE.value, i18n.tr("settings_suffix_space")),
             (PasteSuffix.NONE.value, i18n.tr("settings_suffix_none")),
             (PasteSuffix.NEWLINE.value, i18n.tr("settings_suffix_newline"))],
        )
        self._text_style_hint = HintIcon()
        self._text_style = QComboBox()
        self._text_style.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._text_style.setMinimumContentsLength(10)
        self._text_style.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for style in (TextStyle.FORMAL, TextStyle.STANDARD,
                      TextStyle.INFORMAL, TextStyle.CASUAL):
            self._text_style.addItem(
                i18n.tr(f"settings_text_style_{style.value}"), style.value)
        index = self._text_style.findData(str(self._draft.get("text_style", "")))
        self._text_style.setCurrentIndex(index if index >= 0 else 0)
        self._text_style.currentIndexChanged.connect(
            lambda _: self._text_style_changed(mark_dirty=True))
        recognition.add_row(i18n.tr("settings_text_style"), self._text_style,
                            self._text_style_hint)
        self._text_style_changed(mark_dirty=False)

        cols = QWidget()
        cols.setObjectName("Plain")
        grid = QHBoxLayout(cols)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        grid.addWidget(behaviour, 1)
        grid.addWidget(recognition, 1)

        return _page(_page_header("nav_dictation", "subtitle_dictation"),
                     keys_card, cols)

    def _build_audio_page(self) -> QWidget:
        capture = Section(i18n.tr("settings_section_capture"))
        devices = [("", i18n.tr("settings_device_default"))]
        devices += [(device.name, device.name) for device in audio.list_input_devices()]
        self._device = self._combo(
            capture, "settings_input_device", "input_device", devices)

        self._stop_on_silence = self._checkbox(
            capture, "settings_stop_on_silence", "stop_on_silence",
            i18n.tr("settings_stop_on_silence_hint"))
        self._silence_seconds = QDoubleSpinBox()
        self._silence_seconds.setRange(1.0, 10.0)
        self._silence_seconds.setSingleStep(0.5)
        self._silence_seconds.setDecimals(1)
        self._silence_seconds.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._silence_seconds.setValue(float(self._draft.get("silence_stop_seconds", 2.5)))
        self._silence_seconds.valueChanged.connect(
            lambda value: self._update_draft(silence_stop_seconds=value))
        self._silence_seconds.setEnabled(bool(self._draft.get("stop_on_silence")))
        self._stop_on_silence.toggled.connect(self._silence_seconds.setEnabled)
        capture.add_row(i18n.tr("settings_silence_seconds"), self._silence_seconds)

        self._instant_start = self._combo(
            capture, "settings_instant_start", "instant_start_mode",
            [("5sec", i18n.tr("settings_instant_start_5sec")),
             ("off", i18n.tr("settings_instant_start_off")),
             ("1min", i18n.tr("settings_instant_start_1min")),
             ("always", i18n.tr("settings_instant_start_always"))],
            hint=i18n.tr("settings_instant_start_hint"))

        sound = Section(i18n.tr("nav_audio"))
        self._mute = self._checkbox(sound, "settings_mute", "mute_while_recording")
        self._pause_media = self._checkbox(
            sound, "settings_pause_media", "pause_media_while_recording",
            hint=i18n.tr("settings_pause_media_hint"))
        self._sounds = self._checkbox(sound, "settings_sounds", "play_feedback_sounds")
        return _page(_page_header("nav_audio", "subtitle_audio"), capture, sound)

    def _build_appearance_page(self) -> QWidget:
        general = Section(i18n.tr("settings_tab_appearance"))
        self._interface_language = self._combo(
            general, "settings_interface_language", "interface_language",
            [("en", "English"), ("ru", "Русский")],
        )
        self._waveform = self._checkbox(
            general, "settings_waveform", "show_recording_waveform")
        self._live_preview = self._checkbox(
            general, "settings_live_preview", "live_preview",
            i18n.tr("settings_live_preview_hint"))

        hud = Section("HUD")
        self._hud_size = self._combo(
            hud, "settings_hud_size", "hud_size",
            [(HUDSize.COMPACT.value, i18n.tr("settings_hud_size_compact")),
             (HUDSize.STANDARD.value, i18n.tr("settings_hud_size_standard")),
             (HUDSize.LARGE.value, i18n.tr("settings_hud_size_large"))],
        )
        self._hud_display_mode = self._combo(
            hud, "settings_hud_display_mode", "hud_display_mode",
            [(HUDDisplayMode.LEVEL_BARS.value,
              i18n.tr("settings_hud_display_bars")),
             (HUDDisplayMode.TIMER_OUTLINE.value,
              i18n.tr("settings_hud_display_timer"))],
            hint=i18n.tr("settings_hud_display_hint"),
        )
        self._color_row(hud, "settings_hud_recording_color",
                        "hud_recording_color", AccentColor.RED,
                        hint=i18n.tr("settings_color_hint"))
        self._color_row(hud, "settings_hud_transcribing_color",
                        "hud_transcribing_color", AccentColor.BLUE,
                        hint=i18n.tr("settings_color_hint"))
        self._color_row(hud, "settings_hud_correcting_color",
                        "hud_correcting_color", AccentColor.PURPLE,
                        hint=i18n.tr("settings_hud_correcting_hint"))
        self._hud_background = self._combo(
            hud, "settings_hud_background", "hud_background_style",
            [(HUDBackgroundStyle.SYSTEM.value, i18n.tr("settings_hud_background_system")),
             (HUDBackgroundStyle.DARK.value, i18n.tr("settings_hud_background_dark")),
             (HUDBackgroundStyle.LIGHT.value, i18n.tr("settings_hud_background_light"))],
            hint=i18n.tr("settings_hud_background_hint"),
        )
        return _page(_page_header("nav_appearance", "subtitle_appearance"), general, hud)

    def _build_text_page(self) -> QWidget:
        sub_stack = QStackedWidget()
        seg_bar, _ = _segmented_bar(
            [
                ("vocab", "sub_corrections"),
                ("hotwords", "sub_hotwords"),
                ("cleanup", "sub_cleanup"),
            ],
            sub_stack.setCurrentIndex,
        )

        # Sub-tab 1: Vocabulary / Corrections
        section = Section(i18n.tr("settings_tab_corrections"),
                          i18n.tr("corrections_note"))
        self._auto_learn = self._checkbox(
            section, "settings_auto_learn_vocabulary", "auto_learn_vocabulary",
            i18n.tr("settings_auto_learn_vocabulary_hint"))

        column = QLabel(i18n.tr("corrections_hint_column"))
        column.setObjectName("Caption")
        column.setToolTip(i18n.tr("corrections_hint_tooltip"))
        column.setAlignment(Qt.AlignmentFlag.AlignRight)
        section.add_row(None, column)

        self._corrections_list = QListWidget()
        self._corrections_list.setItemDelegate(
            CorrectionRowDelegate(self._palette, self._corrections_list, hint_column=True,
                                  on_hint_clicked=self._toggle_asr_hint))
        self._corrections_list.setMouseTracking(True)
        self._corrections_list.setUniformItemSizes(True)
        self._corrections_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._corrections_list.setMinimumHeight(140)
        self._corrections_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._corrections_baseline = []
        self._load_corrections()
        section.add_row(None, self._corrections_list, stretch=1)

        editor = QWidget()
        editor.setObjectName("Plain")
        row = QHBoxLayout(editor)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._correction_source = _SubmitLineEdit()
        self._correction_source.setPlaceholderText(i18n.tr("corrections_source"))
        self._correction_replacement = _SubmitLineEdit()
        self._correction_replacement.setPlaceholderText(i18n.tr("corrections_replacement"))
        self._correction_replacement.returnPressed.connect(self._add_correction)
        add = QPushButton(i18n.tr("corrections_add"))
        add.setIcon(icons.icon("plus", self._palette.text_muted, 15))
        add.clicked.connect(self._add_correction)
        remove = QPushButton(i18n.tr("corrections_remove"))
        remove.setIcon(icons.icon("trash", self._palette.text_muted, 15))
        remove.clicked.connect(self._remove_correction)
        row.addWidget(self._correction_source, 2)
        row.addWidget(self._correction_replacement, 2)
        row.addWidget(add)
        row.addWidget(remove)
        section.add_row(None, editor)

        transfer = QWidget()
        transfer.setObjectName("Plain")
        transfer_row = QHBoxLayout(transfer)
        transfer_row.setContentsMargins(0, 0, 0, 0)
        transfer_row.setSpacing(8)
        export = QPushButton(i18n.tr("corrections_export"))
        export.clicked.connect(self._export_corrections)
        import_merge = QPushButton(i18n.tr("corrections_import"))
        import_merge.clicked.connect(self._import_corrections)
        cleanup = QPushButton(i18n.tr("corrections_cleanup"))
        cleanup.clicked.connect(self._cleanup_corrections)
        transfer_row.addWidget(export)
        transfer_row.addWidget(import_merge)
        transfer_row.addStretch(1)
        transfer_row.addWidget(cleanup)
        section.add_row(None, transfer)

        # Sub-tab 2: ASR Terms
        hotwords = Section(i18n.tr("settings_asr_hotwords"),
                           i18n.tr("settings_asr_hotwords_hint"))
        self._asr_hotwords = self._checkbox(
            hotwords, "settings_asr_hotwords_enabled", "asr_hotwords_enabled")
        self._asr_hotwords_strength = self._combo(
            hotwords, "settings_asr_hotwords_strength", "asr_hotwords_strength",
            [("normal", i18n.tr("settings_asr_hotwords_normal")),
             ("strong", i18n.tr("settings_asr_hotwords_strong"))])
        self._asr_hotwords_strength.setEnabled(self._asr_hotwords.isChecked())
        self._asr_hotwords.toggled.connect(self._asr_hotwords_strength.setEnabled)

        hotwords_page = QWidget()
        hotwords_page.setObjectName("Plain")
        hw_layout = QVBoxLayout(hotwords_page)
        hw_layout.setContentsMargins(0, 0, 0, 0)
        hw_layout.setSpacing(12)
        hw_layout.addWidget(hotwords)
        hw_layout.addWidget(self._custom_hotwords_section(), 1)

        # Sub-tab 3: Cleanup & Numbers
        cleanup_section = Section(i18n.tr("sub_cleanup"))
        self._digits = self._checkbox(
            cleanup_section, "settings_numbers_as_digits", "numbers_as_digits",
            i18n.tr("settings_numbers_as_digits_hint"))
        self._remove_final_period = self._checkbox(
            cleanup_section, "settings_remove_final_period", "remove_final_period",
            i18n.tr("settings_remove_final_period_hint"))
        self._fillers = self._filler_row(cleanup_section)
        if hasattr(self, "_filler_panel"):
            self._filler_panel.setVisible(True)
            self._update_filler_toggle()

        cleanup_page = QWidget()
        cleanup_page.setObjectName("Plain")
        cl_layout = QVBoxLayout(cleanup_page)
        cl_layout.setContentsMargins(0, 0, 0, 0)
        cl_layout.setSpacing(12)
        cl_layout.addWidget(cleanup_section)
        cl_layout.addStretch(1)

        sub_stack.addWidget(section)
        sub_stack.addWidget(hotwords_page)
        sub_stack.addWidget(cleanup_page)

        changed = getattr(self._controller, "vocabulary_changed", None)
        if changed is not None:
            changed.connect(self._on_vocabulary_changed)
        return _page(_page_header("nav_text", "subtitle_text"), seg_bar, sub_stack, stretch_last=True)

    # -- the user's recognition terms (user-hotword-vocabulary spec §7) ---

    def _custom_hotwords_section(self) -> Section:
        section = Section(i18n.tr("custom_hotwords"), i18n.tr("custom_hotwords_hint"))
        self._custom_hotwords_list = QListWidget()
        self._custom_hotwords_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._custom_hotwords_list.setMinimumHeight(120)
        self._custom_hotwords_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._custom_hotwords_list.setAccessibleName(i18n.tr("custom_hotwords"))
        self._custom_hotwords_list.itemChanged.connect(self._custom_hotword_toggled)
        self._load_custom_hotwords()
        section.add_row(None, self._custom_hotwords_list, stretch=1)

        editor = QWidget()
        editor.setObjectName("Plain")
        row = QHBoxLayout(editor)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._custom_hotword_field = _SubmitLineEdit()
        self._custom_hotword_field.setPlaceholderText(i18n.tr("custom_hotwords_new"))
        self._custom_hotword_field.returnPressed.connect(self._add_custom_hotword)
        add = QPushButton(i18n.tr("corrections_add"))
        add.setIcon(icons.icon("plus", self._palette.text_muted, 15))
        add.setAutoDefault(False)
        add.clicked.connect(self._add_custom_hotword)
        remove = QPushButton(i18n.tr("corrections_remove"))
        remove.setIcon(icons.icon("trash", self._palette.text_muted, 15))
        remove.setAutoDefault(False)
        remove.clicked.connect(self._remove_custom_hotword)
        import_file = QPushButton(i18n.tr("custom_hotwords_import"))
        import_file.setAutoDefault(False)
        import_file.clicked.connect(self._import_custom_hotwords)
        row.addWidget(self._custom_hotword_field, 1)
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(import_file)
        section.add_row(None, editor)
        return section

    def _load_custom_hotwords(self) -> None:
        listing = self._custom_hotwords_list
        selected = listing.currentItem().data(Qt.ItemDataRole.UserRole) if listing.currentItem() else None
        listing.blockSignals(True)
        listing.clear()
        for record in self._corrections.hotword_phrases():
            item = QListWidgetItem(record.phrase)
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if record.enabled else Qt.CheckState.Unchecked)
            listing.addItem(item)
            if record.id == selected:
                listing.setCurrentItem(item)
        listing.blockSignals(False)

    def _add_custom_hotword(self) -> None:
        from ..vocabulary import DuplicateHotwordPhrase, InvalidHotwordPhrase

        try:
            self._corrections.add_hotword_phrase(self._custom_hotword_field.text())
        except InvalidHotwordPhrase:
            self._warn(i18n.tr("custom_hotwords_invalid"))
            return
        except DuplicateHotwordPhrase:
            self._warn(i18n.tr("custom_hotwords_duplicate"))
            return
        self._custom_hotword_field.clear()
        self._load_custom_hotwords()

    def _remove_custom_hotword(self) -> None:
        item = self._custom_hotwords_list.currentItem()
        if item is not None:
            self._corrections.delete_hotword_phrase(item.data(Qt.ItemDataRole.UserRole))
            self._load_custom_hotwords()

    def _custom_hotword_toggled(self, item) -> None:
        self._corrections.set_hotword_phrase_enabled(
            item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked)

    def _import_custom_hotwords(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("custom_hotwords_import"), "", i18n.tr("custom_hotwords_import_filter"))
        if path:
            self._import_custom_hotwords_file(path)

    def _import_custom_hotwords_file(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8-sig") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            self._warn(i18n.tr("custom_hotwords_read_failed"))
            return
        added, invalid = self._corrections.import_hotword_phrases(text)
        self._load_custom_hotwords()
        self._warn(i18n.tr("custom_hotwords_imported", added=added, invalid=invalid))

    # -- the vocabulary list -------------------------------------------

    def _load_corrections(self) -> None:
        """(Re)fill the list from the store; the baseline the save diffs
        against (VocabularyStore.apply_edits)."""
        self._corrections_baseline = self._corrections.all()
        self._corrections_list.clear()
        for record in self._corrections_baseline:
            self._add_correction_item(DraftEntry(record.source, record.replacement,
                                                 record.asr_hint, record.origin))

    def _current_entries(self) -> list:
        return [self._corrections_list.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self._corrections_list.count())]

    def _corrections_dirty(self) -> bool:
        baseline = [(r.source, r.replacement, r.asr_hint) for r in self._corrections_baseline]
        current = [(e.source, e.replacement, e.asr_hint) for e in self._current_entries()]
        return baseline != current

    def _on_vocabulary_changed(self, _kind: str) -> None:
        """A learn or a sync changed the store: show it, unless the user is
        in the middle of editing the list (their save diffs against the
        baseline, so nothing of the sync's is lost either way)."""
        self._load_custom_hotwords()
        if not self._corrections_dirty():
            self._load_corrections()

    @staticmethod
    def _hint_state(entry: DraftEntry) -> int:
        origin = getattr(entry.origin, "value", entry.origin)
        if asr_hotwords.eligible_phrase(entry.source, entry.replacement) is None:
            return HINT_NONE
        return HINT_ON if asr_hotwords.is_effective(entry.source, entry.replacement, origin,
                                                    entry.asr_hint) else HINT_OFF

    def _toggle_asr_hint(self, row: int) -> None:
        item = self._corrections_list.item(row)
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        state = self._hint_state(entry)
        if state == HINT_NONE:
            return
        # A click sets the opposite of what is shown, explicitly.
        entry = DraftEntry(entry.source, entry.replacement, state != HINT_ON, entry.origin)
        item.setData(Qt.ItemDataRole.UserRole, entry)
        item.setData(HINT_ROLE, self._hint_state(entry))

    def _cleanup_corrections(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        if self._corrections_dirty():
            answer = QMessageBox.question(self, i18n.tr("corrections_cleanup_title"),
                                          i18n.tr("corrections_cleanup_save_first"))
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._corrections.apply_edits(self._corrections_baseline, self._current_entries())
            self._load_corrections()
        audit = vocabulary_hygiene.extended_audit(self._corrections.all())
        if audit.is_empty:
            self._warn(i18n.tr("corrections_cleanup_nothing"))
            return
        dialog = CleanupPreviewDialog(audit, self._palette, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        plan = vocabulary_hygiene.cleanup_plan_from_audit(audit, dialog.selected_ids)
        if plan.is_empty:
            return
        self._corrections.apply_cleanup(plan)
        self._load_corrections()
        self._warn(i18n.tr("corrections_cleanup_done", deleted=len(plan.deletions),
                           rewritten=len(plan.rewrites)))

    # -- account sync (hygiene spec §4.3) --------------------------------

    def _sync_section(self) -> Optional["Section"]:
        sync = getattr(self._controller, "vocabulary_sync", None)
        if sync is None:
            return None
        self._sync = sync
        section = Section(i18n.tr("sync_title"))

        self._sync_form = QWidget()
        self._sync_form.setObjectName("Plain")
        form = QGridLayout(self._sync_form)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)
        self._sync_email = QLineEdit(self._settings.vocabulary_sync_email)
        self._sync_email.setPlaceholderText("name@example.com")
        self._sync_password = QLineEdit()
        self._sync_password.setEchoMode(QLineEdit.EchoMode.Password)
        self._sync_password.returnPressed.connect(self._sync_sign_in)
        for row_index, (label_key, field) in enumerate(
                (("sync_email", self._sync_email), ("sync_password", self._sync_password))):
            key = QLabel(i18n.tr(label_key))
            key.setObjectName("Key")
            form.addWidget(key, row_index, 0)
            form.addWidget(field, row_index, 1)
        consent = QLabel(i18n.tr("sync_consent") + " " + i18n.tr("sync_new_account_note"))
        consent.setObjectName("Caption")
        consent.setWordWrap(True)
        form.addWidget(consent, 2, 0, 1, 2)
        self._sync_sign_in_button = QPushButton(i18n.tr("sync_sign_in"))
        self._sync_sign_in_button.setObjectName("Primary")
        self._sync_sign_in_button.clicked.connect(self._sync_sign_in)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._sync_sign_in_button)
        form.addLayout(buttons, 3, 0, 1, 2)
        section.add_row(None, self._sync_form)

        self._sync_account = QWidget()
        self._sync_account.setObjectName("Plain")
        account = QHBoxLayout(self._sync_account)
        account.setContentsMargins(0, 0, 0, 0)
        account.setSpacing(12)
        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        self._sync_account_label = QLabel()
        self._sync_account_label.setObjectName("Value")
        self._sync_account_label.setWordWrap(True)
        self._sync_state_label = QLabel()
        self._sync_state_label.setObjectName("Caption")
        self._sync_state_label.setWordWrap(True)
        info.addWidget(self._sync_account_label)
        info.addWidget(self._sync_state_label)
        account.addLayout(info, 1)
        self._sync_now_button = QPushButton(i18n.tr("sync_sync_now"))
        self._sync_now_button.setIcon(icons.icon("refresh", self._palette.text_muted, 14))
        self._sync_now_button.clicked.connect(self._sync_now)
        sign_out = QPushButton(i18n.tr("sync_sign_out"))
        sign_out.clicked.connect(self._sync_sign_out)
        account.addWidget(self._sync_now_button)
        account.addWidget(sign_out)
        section.add_row(None, self._sync_account)

        self._sync_error = QLabel()
        self._sync_error.setWordWrap(True)
        self._sync_error.setStyleSheet(f"color: {self._palette.danger}; background: transparent;")
        self._sync_error.setVisible(False)
        section.add_row(None, self._sync_error)

        self._sync_done.connect(self._on_sync_done)
        status_signal = getattr(self._controller, "vocabulary_sync_status", None)
        if status_signal is not None:
            status_signal.connect(self._show_sync_status)
        self._show_sync_status(sync.status)
        return section

    def _show_sync_status(self, status) -> None:
        signed_in = status.signed_in
        self._sync_form.setVisible(not signed_in)
        self._sync_account.setVisible(signed_in)
        self._sync_sign_in_button.setEnabled(True)
        self._sync_sign_in_button.setText(i18n.tr("sync_sign_in"))
        if signed_in:
            self._sync_account_label.setText(i18n.tr("sync_signed_in_as", email=status.email))
            when = (time.strftime("%d.%m.%Y %H:%M", time.localtime(status.last_synced_at))
                    if status.last_synced_at else i18n.tr("sync_never"))
            state = i18n.tr("sync_last", when=when)
            if status.state == "syncing":
                state = i18n.tr("sync_state_syncing")
            elif status.state == "ok":
                state = i18n.tr("sync_state_ok") + " · " + state
            self._sync_state_label.setText(state)
            self._sync_now_button.setEnabled(status.state != "syncing")
        elif status.email and not self._sync_email.text():
            self._sync_email.setText(status.email)
        error = status.error or ("unauthorized" if status.state == "reauth" else "")
        self._set_sync_error(error)

    def _set_sync_error(self, kind: str) -> None:
        self._sync_error.setText(i18n.tr(f"sync_error_{kind}") if kind else "")
        self._sync_error.setVisible(bool(kind))

    def _run_sync_job(self, job) -> None:
        def work() -> None:
            from ..vocabulary_sync import SyncError

            try:
                result = job()
                self._sync_done.emit("created" if result is True else "ok", "")
            except SyncError as exc:
                self._sync_done.emit("error", exc.kind)
            except Exception as exc:  # never let a worker die silently
                self._sync_done.emit("error", "server")

        threading.Thread(target=work, name="vocabulary-sync-ui", daemon=True).start()

    def _sync_sign_in(self) -> None:
        email = self._sync_email.text().strip()
        password = self._sync_password.text()
        if not email or not password:
            self._set_sync_error("invalid")
            return
        self._set_sync_error("")
        self._sync_sign_in_button.setEnabled(False)
        self._sync_sign_in_button.setText(i18n.tr("sync_signing_in"))
        self._run_sync_job(lambda: self._sync.sign_in(email, password))

    def _sync_now(self) -> None:
        self._sync_now_button.setEnabled(False)
        self._run_sync_job(self._sync.sync_now)

    def _sync_sign_out(self) -> None:
        self._run_sync_job(self._sync.sign_out)

    def _on_sync_done(self, kind: str, detail: str) -> None:
        self._sync_password.clear()
        self._show_sync_status(self._sync.status)
        if kind == "error":
            self._set_sync_error(detail)
        elif kind == "created":
            self._sync_state_label.setText(i18n.tr("sync_account_created"))

    def done(self, result: int) -> None:  # noqa: D401 (Qt override)
        """Detach from the app's long-lived signals: the dialog outlives
        its exec() as a child of the panel."""
        if getattr(self, "_detached", False):
            super().done(result)
            return
        self._detached = True
        for name, slot in (("vocabulary_sync_status", self._show_sync_status),
                           ("vocabulary_changed", self._on_vocabulary_changed)):
            signal = getattr(self._controller, name, None)
            if signal is None:
                continue
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().done(result)

    # -- import / export ----------------------------------------------

    def _export_corrections(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from .. import vocabulary_transfer as transfer

        path, _ = QFileDialog.getSaveFileName(
            self, i18n.tr("corrections_export"), "corrections.json",
            "JSON (*.json)")
        if not path:
            return
        # What is on screen, not what is in the database: the user may have
        # edited the list and not saved yet, and exporting the older state
        # underneath them would be a surprise.
        items = [self._corrections_list.item(index).data(Qt.ItemDataRole.UserRole)
                 for index in range(self._corrections_list.count())]
        pairs = [(item.source, item.replacement) for item in items]
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(transfer.encode(pairs))
        except OSError as exc:
            self._warn(i18n.tr("corrections_export_failed", error=str(exc)))

    def _import_corrections(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from .. import vocabulary_transfer as transfer

        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("corrections_import"), "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                document = transfer.decode(handle.read())
        except (OSError, transfer.TransferError) as exc:
            self._warn(i18n.tr("corrections_import_failed", error=str(exc)))
            return
        payload = [{"source": source, "replacement": replacement}
                   for source, replacement in document.corrections]

        existing = {}
        for index in range(self._corrections_list.count()):
            item = self._corrections_list.item(index).data(Qt.ItemDataRole.UserRole)
            existing[item.source.casefold()] = index

        added = 0
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            source = str(entry.get("source", "")).strip()
            replacement = str(entry.get("replacement", "")).strip()
            if not source or not replacement:
                continue
            index = existing.get(source.casefold())
            if index is not None:
                # One answer per word: an imported rule for a word already
                # in the list replaces it rather than sitting beside it.
                self._corrections_list.takeItem(index)
                existing = {k: (v - 1 if v > index else v)
                            for k, v in existing.items() if v != index}
            self._add_correction_item(DraftEntry(source, replacement))
            existing[source.casefold()] = self._corrections_list.count() - 1
            added += 1
        if document.skipped:
            self._warn(i18n.tr("corrections_imported_partial",
                               count=added, skipped=document.skipped))
        else:
            self._warn(i18n.tr("corrections_imported", count=added))

    def _warn(self, message: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(self, i18n.tr("app_name"), message)

    def _build_ai_page(self) -> QWidget:
        """Correction, rewrite, punctuation, and hardware/models in 4 sub-tabs."""
        from ..llm import RewriteStyle
        from ..llm.host import bundled_host_available
        from ..llm.models import CORRECTION_MODELS, PROFILES, REWRITE_MODELS

        bundled = bundled_host_available()
        hw = hardware.current()
        lang = i18n.language()
        engines = [("bundledLocal", i18n.tr("settings_llm_engine_bundled")),
                   ("customEndpoint", i18n.tr("settings_llm_engine_custom"))]

        sub_stack = QStackedWidget()
        seg_bar, _ = _segmented_bar(
            [
                ("correction", "sub_ai_correction"),
                ("rewrite", "sub_ai_rewrite"),
                ("punctuation", "sub_ai_punctuation"),
                ("hardware", "sub_ai_hardware"),
            ],
            sub_stack.setCurrentIndex,
        )

        # Sub-tab 1: Correction
        correction = Section(i18n.tr("settings_correction"),
                             i18n.tr("settings_correction_hint"))
        self._correction_mode = self._combo(
            correction, "settings_correction_mode", "text_postprocessing_mode_v1",
            [("off", i18n.tr("settings_correction_off")),
             ("correction", i18n.tr("settings_correction_on"))],
        )
        if bundled:
            corr_engine = self._combo(
                correction, "settings_llm_engine", "llm_engine_backend_v1", engines)
            self._correction_model = self._combo(
                correction, "settings_correction_model", "correction_bundled_model_v2",
                [(model.value, i18n.tr(f"llm_model_{model.value}"))
                 for model in CORRECTION_MODELS],
            )
            corr_compat_box = self._model_compat_banner_host(
                correction, self._correction_model, hw, lang)
            self._correction_model.currentIndexChanged.connect(corr_compat_box)
            corr_compat_box()
            corr_ep = self._endpoint_group(correction, "llm_custom")
            corr_ep.setVisible(corr_engine.currentData() == "customEndpoint")
            corr_engine.currentIndexChanged.connect(
                lambda _=0, c=corr_engine, g=corr_ep: g.setVisible(
                    c.currentData() == "customEndpoint"))
        else:
            self._endpoint_fields(correction, "llm_custom")
        self._correction_prompt = self._prompt_editor(
            correction, "settings_correction_prompt", "correction_system_prompt_v1",
            stretch=1)

        # Sub-tab 2: Rewrite (stacked vertically: settings + styles on top, full-width prompt below)
        rw_top = Section(i18n.tr("settings_rewrite"),
                         i18n.tr("settings_rewrite_hint"))
        self._rewrite_enabled = self._checkbox(
            rw_top, "settings_rewrite_enabled", "rewrite_enabled_v1")
        self._rewrite_style = QComboBox()
        self._rewrite_style.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._rewrite_style.setMinimumContentsLength(10)
        self._rewrite_style.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._reload_style_combo()
        self._rewrite_style.currentIndexChanged.connect(self._select_rewrite_style)
        rw_top.add_row(i18n.tr("settings_rewrite_style"), self._rewrite_style)
        if bundled:
            rw_engine = self._combo(
                rw_top, "settings_llm_engine", "rewrite_engine_backend_v1", engines)
            self._rewrite_model = self._combo(
                rw_top, "settings_rewrite_model", "rewrite_bundled_model_v2",
                [(model.value, i18n.tr(f"llm_model_{model.value}"))
                 for model in REWRITE_MODELS],
            )
            rw_compat_box = self._model_compat_banner_host(
                rw_top, self._rewrite_model, hw, lang)
            self._rewrite_model.currentIndexChanged.connect(rw_compat_box)
            rw_compat_box()
            rw_ep = self._endpoint_group(rw_top, "rewrite_custom")
            rw_ep.setVisible(rw_engine.currentData() == "customEndpoint")
            rw_engine.currentIndexChanged.connect(
                lambda _=0, c=rw_engine, g=rw_ep: g.setVisible(
                    c.currentData() == "customEndpoint"))
        else:
            self._endpoint_fields(rw_top, "rewrite_custom")
        self._custom_styles = CustomStylesBlock(
            self._controller.styles, self._settings, self._controller,
            self._palette, self._reload_style_combo)
        rw_top.add_row(None, self._custom_styles)
        self._controller.custom_styles_changed.connect(self._on_styles_changed)

        rw_prompt_card = Section(i18n.tr("settings_correction_prompt"))
        prompt_picker = QComboBox()
        prompt_picker.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        prompt_picker.setMinimumContentsLength(10)
        prompt_picker.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        prompt_stack = QStackedWidget()
        for style in RewriteStyle:
            prompt_picker.addItem(i18n.tr(f"rewrite_style_{style.value}"), style.value)
            ed = self._make_prompt_editor(f"rewrite_system_prompt_{style.value}_v1")
            prompt_stack.addWidget(ed)
        prompt_picker.currentIndexChanged.connect(prompt_stack.setCurrentIndex)
        rw_prompt_card.add_row(i18n.tr("settings_rewrite_style"), prompt_picker)
        rw_prompt_card.add_row(None, prompt_stack, stretch=1)

        rw_page = QWidget()
        rw_page.setObjectName("Plain")
        rw_stack_v = QVBoxLayout(rw_page)
        rw_stack_v.setContentsMargins(0, 0, 0, 0)
        rw_stack_v.setSpacing(12)
        rw_stack_v.addWidget(rw_top)
        rw_stack_v.addWidget(rw_prompt_card, 1)

        # Sub-tab 3: Punctuation
        punctuation = self._punctuation_section(hw)
        punct_page = QWidget()
        punct_page.setObjectName("Plain")
        punct_layout = QVBoxLayout(punct_page)
        punct_layout.setContentsMargins(0, 0, 0, 0)
        punct_layout.setSpacing(12)
        punct_layout.addWidget(punctuation)
        punct_layout.addStretch(1)

        # Sub-tab 4: Models, Hardware & AI Hotkeys (2-column layout)
        hw_page = QWidget()
        hw_page.setObjectName("Plain")
        hw_cols = QHBoxLayout(hw_page)
        hw_cols.setContentsMargins(0, 0, 0, 0)
        hw_cols.setSpacing(12)

        hw_left = QWidget()
        hw_left.setObjectName("Plain")
        hw_left_v = QVBoxLayout(hw_left)
        hw_left_v.setContentsMargins(0, 0, 0, 0)
        hw_left_v.setSpacing(12)

        processing_keys = Section(i18n.tr("settings_section_processing_keys"),
                                  i18n.tr("settings_section_processing_keys_hint"))
        self._correction_hotkey_button = self._shortcut_row(
            processing_keys, "settings_correction_hotkey", "correction_hotkey")
        self._rewrite_hotkey_button = self._shortcut_row(
            processing_keys, "settings_rewrite_hotkey", "rewrite_hotkey")
        self._rewrite_style_hotkey_button = self._shortcut_row(
            processing_keys, "settings_rewrite_style_hotkey", "rewrite_style_hotkey")
        hw_left_v.addWidget(processing_keys)

        network = Section(i18n.tr("settings_llm_network"),
                          i18n.tr("settings_llm_network_hint"))
        self._llm_proxy = self._checkbox(
            network, "settings_llm_use_system_proxy", "llm_use_system_proxy_v1",
            hint=i18n.tr("settings_llm_use_system_proxy_hint"))
        hw_left_v.addWidget(network)

        if bundled:
            device = Section(i18n.tr("settings_llm_device"),
                             i18n.tr("settings_llm_device_hint"))
            self._llm_backend = self._combo(
                device, "settings_llm_backend", "llm_compute_backend",
                [("cpu", i18n.tr("settings_llm_backend_cpu")),
                 ("gpu", i18n.tr("settings_llm_backend_gpu"))],
            )
            gpu_status = hw.vulkan_gpu_status(lang)
            if not gpu_status.available:
                gpu_idx = self._llm_backend.findData("gpu")
                if gpu_idx >= 0:
                    combo_model = self._llm_backend.model()
                    if isinstance(combo_model, QStandardItemModel):
                        item = combo_model.item(gpu_idx)
                        if item is not None:
                            item.setEnabled(False)
                if self._llm_backend.currentData() == "gpu":
                    cpu_idx = self._llm_backend.findData("cpu")
                    if cpu_idx >= 0:
                        self._llm_backend.setCurrentIndex(cpu_idx)
                device.add_row(None, self._compat_banner(
                    "warning", self._palette.warning,
                    i18n.tr("hw_banner_gpu_unavailable"), gpu_status.message))
            hw_left_v.addWidget(device)
        hw_left_v.addStretch(1)
        hw_cols.addWidget(hw_left, 1)

        if bundled:
            models = Section(i18n.tr("settings_llm_models"),
                             i18n.tr("settings_llm_models_hint"))
            self._model_rows = {}
            files = set()
            for model in dict.fromkeys(CORRECTION_MODELS + REWRITE_MODELS):
                pin = PROFILES[model].pin
                if pin.local_path in files:
                    continue
                files.add(pin.local_path)
                self._model_rows[model] = self._model_row(models, model, PROFILES[model], hw)
            hw_right = QWidget()
            hw_right.setObjectName("Plain")
            hw_right_v = QVBoxLayout(hw_right)
            hw_right_v.setContentsMargins(0, 0, 0, 0)
            hw_right_v.setSpacing(12)
            hw_right_v.addWidget(models)
            hw_right_v.addStretch(1)
            hw_cols.addWidget(hw_right, 1)

        sub_stack.addWidget(correction)
        sub_stack.addWidget(rw_page)
        sub_stack.addWidget(punct_page)
        sub_stack.addWidget(hw_page)

        return _page(_page_header("nav_ai", "subtitle_ai"), seg_bar, sub_stack, stretch_last=True)

    def _reload_style_combo(self) -> None:
        """Rebuild the mode list from the store, keeping the selection.

        A selected custom mode that is gone (deleted here, or on another
        machine) falls back to «Причесать», as the store does for the saved
        setting.
        """
        from ..llm import RewriteStyle

        combo = self._rewrite_style
        custom = self._controller.styles.all()
        wanted = (str(self._draft.get("rewrite_custom_style_id_v1") or "")
                  or str(self._draft.get("rewrite_style_v1") or ""))
        known = {style.id for style in custom} | {style.value for style in RewriteStyle}
        if wanted not in known:
            wanted = "polish"
        combo.blockSignals(True)
        combo.clear()
        for style in RewriteStyle:
            combo.addItem(i18n.tr(f"rewrite_style_{style.value}"), style.value)
        for style in custom:
            combo.addItem(style.name, style.id)
            combo.setItemIcon(combo.count() - 1, icons.swatch(style.color, 13))
        combo.setCurrentIndex(max(0, combo.findData(wanted)))
        combo.blockSignals(False)
        self._select_rewrite_style()

    def _select_rewrite_style(self, _index: int = 0) -> None:
        value = str(self._rewrite_style.currentData() or "polish")
        if value.startswith("c-"):
            self._draft["rewrite_custom_style_id_v1"] = value
        else:
            self._draft["rewrite_custom_style_id_v1"] = ""
            self._draft["rewrite_style_v1"] = value

    def _on_styles_changed(self, _kind: str = "") -> None:
        """The account sync changed the modes while this window is open."""
        self._reload_style_combo()
        self._custom_styles.reload()

    def _endpoint_group(self, section: "Section", prefix: str) -> QWidget:
        group = QWidget()
        group.setObjectName("Plain")
        grid = QGridLayout(group)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        for row_idx, (suffix, label_key, placeholder, secret) in enumerate((
                ("base_url_v1", "settings_endpoint_url", "http://127.0.0.1:1234", False),
                ("api_key_v1", "settings_endpoint_key", i18n.tr("settings_endpoint_key_placeholder"), True),
                ("model_name_v1", "settings_endpoint_model", "gpt-4o-mini", False))):
            key = f"{prefix}_{suffix}"
            lbl = QLabel(i18n.tr(label_key))
            lbl.setObjectName("Key")
            field = QLineEdit(str(self._draft.get(key, "") or ""))
            field.setPlaceholderText(placeholder)
            if secret:
                field.setEchoMode(QLineEdit.EchoMode.Password)
            field.textChanged.connect(
                lambda value, k=key: self._update_draft(**{k: value.strip()}))
            grid.addWidget(lbl, row_idx, 0)
            grid.addWidget(field, row_idx, 1)
        section.add_row(None, group)
        return group

    def _endpoint_fields(self, section: "Section", prefix: str) -> None:
        """Base URL, API key and model name of one stage's endpoint."""
        for suffix, label_key, placeholder, secret in (
                ("base_url_v1", "settings_endpoint_url", "http://127.0.0.1:1234", False),
                ("api_key_v1", "settings_endpoint_key", i18n.tr("settings_endpoint_key_placeholder"), True),
                ("model_name_v1", "settings_endpoint_model", "gpt-4o-mini", False)):
            key = f"{prefix}_{suffix}"
            field = QLineEdit(str(self._draft.get(key, "") or ""))
            field.setPlaceholderText(placeholder)
            if secret:
                field.setEchoMode(QLineEdit.EchoMode.Password)
            field.textChanged.connect(
                lambda value, k=key: self._update_draft(**{k: value.strip()}))
            section.add_row(i18n.tr(label_key), field)

    def _make_prompt_editor(self, draft_key: str) -> QWidget:
        from PySide6.QtWidgets import QPlainTextEdit

        editor = QPlainTextEdit()
        editor.setPlainText(str(self._draft.get(draft_key, "")))
        editor.setPlaceholderText(i18n.tr("settings_prompt_placeholder"))
        editor.setMinimumHeight(88)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        editor.textChanged.connect(
            lambda e=editor, k=draft_key: self._update_draft(
                **{k: e.toPlainText().strip()}))
        return editor

    def _prompt_editor(self, section: "Section", label_key: str,
                       draft_key: str, *, stretch: int = 0) -> QWidget:
        """A multi-line override for one built-in prompt."""
        editor = self._make_prompt_editor(draft_key)
        section.add_row(i18n.tr(label_key), editor, stretch=stretch)
        return editor

    def _compat_banner(self, icon_name: str, color: str, title: str, detail: str) -> QWidget:
        banner = QWidget()
        banner.setStyleSheet(
            f"QWidget {{ background: {self._palette.field}; "
            f"border: 1px solid {color}; border-radius: 8px; }}"
        )
        outer = QHBoxLayout(banner)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, color, 16))
        glyph.setStyleSheet("border: none; background: transparent;")
        outer.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        t_lbl = QLabel(title)
        t_lbl.setWordWrap(True)
        t_lbl.setStyleSheet(
            f"color: {color}; font-weight: 600; font-size: 12px; border: none; background: transparent;")
        d_lbl = QLabel(detail)
        d_lbl.setWordWrap(True)
        d_lbl.setStyleSheet(
            f"color: {self._palette.text_muted}; font-size: 11px; border: none; background: transparent;")
        col.addWidget(t_lbl)
        col.addWidget(d_lbl)
        outer.addLayout(col, 1)
        return banner

    def _model_compat_banner_host(self, section: "Section", combo: QComboBox,
                                  hw: hardware.HardwareProfile, lang: str):
        host = QWidget()
        host.setObjectName("Plain")
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        host.setVisible(False)
        section.add_row(None, host)

        def refresh(*_args) -> None:
            while box.count():
                item = box.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            model_id = str(combo.currentData() or "")
            if not model_id:
                host.setVisible(False)
                return
            compat = hw.model_compatibility(model_id, lang, combo.currentText())
            if compat.status == "unsupported":
                box.addWidget(self._compat_banner(
                    "warning", self._palette.warning,
                    i18n.tr("hw_banner_model_unsupported"), compat.reason))
                host.setVisible(True)
            elif compat.status == "cpu_only":
                box.addWidget(self._compat_banner(
                    "info", self._palette.busy,
                    i18n.tr("hw_banner_cpu_warning"), compat.reason))
                host.setVisible(True)
            else:
                host.setVisible(False)

        return refresh

    def _apply_model_badge(self, badge: QLabel, state: str, size_mb: int,
                           tooltip: str = "") -> None:
        unit = "МБ" if i18n.language() == "ru" else "MB"
        p = self._palette
        if state == "present":
            fg, bg, bd = p.ok, "rgba(48, 209, 88, 0.14)", "rgba(48, 209, 88, 0.38)"
            prefix = "✓"
            tip = i18n.tr("settings_model_present", size=size_mb)
        elif state == "unsupported":
            fg, bg, bd = p.warning, "rgba(255, 159, 10, 0.14)", "rgba(255, 159, 10, 0.38)"
            prefix = "!"
            tip = tooltip or i18n.tr("hw_status_limited")
        else:
            fg, bg, bd = p.danger, "rgba(255, 69, 58, 0.12)", "rgba(255, 69, 58, 0.35)"
            prefix = "●"
            tip = i18n.tr("settings_model_absent", size=size_mb)
        badge.setText(f"{prefix}  {size_mb} {unit}")
        badge.setToolTip(tooltip or tip)
        badge.setStyleSheet(
            f"color: {fg}; background: {bg}; border: 1px solid {bd}; "
            "border-radius: 6px; padding: 4px 10px; font-weight: 600; font-size: 12px;"
        )

    def _model_row(self, section: "Section", model, model_profile,
                   hw: Optional[hardware.HardwareProfile] = None) -> QWidget:
        """One model's presence, size and download button."""
        from PySide6.QtWidgets import QProgressBar

        from ..llm.download import is_present

        row = QWidget()
        row.setObjectName("Plain")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(10)

        status = QLabel()
        status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setVisible(False)
        progress.setMaximumWidth(140)
        button = QPushButton(i18n.tr("settings_model_download"))

        size_mb = model_profile.pin.size_bytes // (1 << 20)
        present = is_present(model_profile.pin)
        compat = (hw.model_compatibility(model.value, i18n.language(),
                                         i18n.tr(f"llm_model_{model.value}"))
                  if hw is not None else hardware.ModelCompatibility("recommended"))
        if present:
            self._apply_model_badge(status, "present", size_mb,
                                    compat.reason if compat.status == "cpu_only" else "")
            button.setVisible(False)
        elif compat.status == "unsupported":
            self._apply_model_badge(status, "unsupported", size_mb, compat.reason)
            button.setVisible(False)
        else:
            self._apply_model_badge(status, "absent", size_mb,
                                    compat.reason if compat.status == "cpu_only" else "")
            button.setVisible(True)
            button.setEnabled(True)
        button.clicked.connect(
            lambda _=False, m=model, p=model_profile.pin, st=status,
            pb=progress, bt=button: self._start_download(m, p, st, pb, bt))

        layout.addWidget(status)
        layout.addStretch(1)
        layout.addWidget(progress)
        layout.addWidget(button)
        section.add_row(i18n.tr(f"llm_model_{model.value}"), row)
        return row

    def _punctuation_section(self, hw: Optional[hardware.HardwareProfile] = None) -> "Section":
        """The last text stage: on/off, Small or Base, and its download."""
        from PySide6.QtWidgets import QProgressBar

        from .. import punctuation

        hw = hw or hardware.current()
        punct_status = hw.punctuation_status(i18n.language())

        section = Section(i18n.tr("settings_punctuation"),
                          i18n.tr("settings_punctuation_hint"))
        self._punctuation_enabled = self._checkbox(
            section, "settings_punctuation_enabled", "punctuation_restoration_enabled_v1")
        if not punct_status.available and not self._punctuation_enabled.isChecked():
            self._punctuation_enabled.setEnabled(False)
        if not punct_status.available:
            section.add_row(None, self._compat_banner(
                "warning", self._palette.warning,
                i18n.tr("hw_banner_punct_unavailable"), punct_status.message))
        self._punctuation_model = self._combo(
            section, "settings_punctuation_model", "punctuation_model_v1",
            [("base", i18n.tr("settings_punctuation_base")),
             ("small", i18n.tr("settings_punctuation_small"))],
            hint=i18n.tr("settings_punctuation_model_hint"))

        row = QWidget()
        row.setObjectName("Plain")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)
        status = QLabel()
        status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setVisible(False)
        progress.setMaximumWidth(160)
        button = QPushButton(i18n.tr("settings_model_download"))
        layout.addWidget(status)
        layout.addStretch(1)
        layout.addWidget(progress)
        layout.addWidget(button)
        section.add_row(i18n.tr("settings_punctuation_files"), row)

        def refresh(*_args) -> None:
            model = str(self._punctuation_model.currentData() or "base")
            size_mb = punctuation.download_bytes(model) // (1 << 20)
            present = punctuation.is_installed(model)
            if present:
                self._apply_model_badge(status, "present", size_mb)
                button.setVisible(False)
            elif not punct_status.available:
                self._apply_model_badge(status, "unsupported", size_mb, punct_status.message)
                button.setVisible(False)
            else:
                self._apply_model_badge(status, "absent", size_mb)
                button.setVisible(not progress.isVisible())
                button.setEnabled(True)

        self._punctuation_model.currentIndexChanged.connect(refresh)
        button.clicked.connect(lambda _=False: self._start_punctuation_download(
            str(self._punctuation_model.currentData() or "base"), status, progress, button, refresh))
        refresh()
        return section

    def _start_punctuation_download(self, model: str, status, progress, button, refresh) -> None:
        import threading

        from PySide6.QtCore import QTimer

        from .. import onnx_models, punctuation

        button.setEnabled(False)
        progress.setVisible(True)
        state = {"fraction": 0.0, "error": ""}

        def on_progress(done: int, total: int) -> None:
            state["fraction"] = done / total if total else 0.0

        def run() -> None:
            try:
                onnx_models.install(punctuation.model_id(model), on_progress)
            except Exception as exc:  # shown in the row
                state["error"] = str(exc)

        thread = threading.Thread(target=run, name=f"download-punct-{model}", daemon=True)
        thread.start()
        timer = QTimer(self)
        timer.setInterval(200)

        def tick() -> None:
            progress.setValue(int(state["fraction"] * 100))
            if thread.is_alive():
                return
            timer.stop()
            progress.setVisible(False)
            refresh()
            if state["error"]:
                button.setEnabled(True)
                status.setText(i18n.tr("settings_model_failed", error=state["error"]))

        timer.timeout.connect(tick)
        timer.start()

    def _start_download(self, model, pin, status, progress, button) -> None:
        """Fetch one model on a worker thread, reporting into this row."""
        import threading

        from PySide6.QtCore import QTimer

        from ..llm.download import DownloadState, download

        button.setEnabled(False)
        progress.setVisible(True)
        state = {"fraction": 0.0, "state": DownloadState.DOWNLOADING,
                 "message": ""}

        def on_progress(item) -> None:
            # Called on the worker thread: only touch the plain dict here,
            # never a widget. The timer below does the drawing.
            state["fraction"] = item.fraction
            state["state"] = item.state
            state["message"] = item.message

        def run() -> None:
            download(pin, on_progress=on_progress)

        thread = threading.Thread(target=run, name=f"download-{model.value}",
                                  daemon=True)
        thread.start()

        timer = QTimer(self)
        timer.setInterval(200)

        def tick() -> None:
            progress.setValue(int(state["fraction"] * 100))
            if thread.is_alive():
                return
            timer.stop()
            progress.setVisible(False)
            if state["state"] is DownloadState.READY:
                size_mb = pin.size_bytes // (1 << 20)
                self._apply_model_badge(status, "present", size_mb)
                button.setVisible(False)
                postprocessor = getattr(self._controller, "postprocessor", None)
                if postprocessor is not None:
                    postprocessor.forget_missing(model)
            else:
                button.setVisible(True)
                button.setEnabled(True)
                status.setText(i18n.tr("settings_model_failed",
                                       error=state["message"] or "?"))

        timer.timeout.connect(tick)
        timer.start()

    def _build_system_page(self) -> QWidget:
        # Card 1 (full width): System & Speech Engine in 2 clean columns
        sys_card = QWidget()
        sys_card.setObjectName("Card")
        sys_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sys_outer = QVBoxLayout(sys_card)
        sys_outer.setContentsMargins(16, 13, 16, 14)
        sys_outer.setSpacing(10)
        sys_title = QLabel(i18n.tr("settings_tab_advanced"))
        sys_title.setObjectName("CardTitle")
        sys_outer.addWidget(sys_title)

        sys_grid = QGridLayout()
        sys_grid.setHorizontalSpacing(24)
        sys_grid.setVerticalSpacing(8)
        sys_grid.setColumnStretch(0, 0)
        sys_grid.setColumnStretch(1, 1)

        # Left column of Card 1: autostart, updates, check button
        left_sys = QWidget()
        left_sys.setObjectName("Plain")
        left_sys.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        ls_v = QVBoxLayout(left_sys)
        ls_v.setContentsMargins(0, 0, 0, 0)
        ls_v.setSpacing(8)
        self._autostart = QCheckBox(i18n.tr("settings_autostart"))
        self._autostart.setChecked(bool(self._draft.get("start_at_login")))
        self._autostart.toggled.connect(
            lambda v: self._update_draft(start_at_login=v))
        self._updates = QCheckBox(i18n.tr("settings_check_updates"))
        self._updates.setChecked(bool(self._draft.get("check_for_updates")))
        self._updates.toggled.connect(
            lambda v: self._update_draft(check_for_updates=v))
        self._update_button = QPushButton(i18n.tr("panel_check_updates"))
        self._update_button.setIcon(icons.icon("download", self._palette.text_muted, 15))
        self._update_button.clicked.connect(self._check_updates)
        self._update_label = self._muted_label("")
        upd_row = QHBoxLayout()
        upd_row.setContentsMargins(0, 0, 0, 0)
        upd_row.setSpacing(10)
        upd_row.addWidget(self._update_button)
        upd_row.addWidget(self._update_label)
        ls_v.addWidget(self._autostart)
        ls_v.addWidget(self._updates)
        ls_v.addLayout(upd_row)

        # Right column of Card 1: speech model & compute backend
        right_sys = Section(i18n.tr("panel_model"))
        right_sys.setObjectName("Plain")
        right_sys.layout().setContentsMargins(0, 0, 0, 0)
        self._speech_model = self._combo(
            right_sys, "settings_speech_model", "speech_model_profile",
            [(asr.PROFILE_PARAKEET_ULTRA, i18n.tr("settings_model_parakeet_ultra")),
             (asr.PROFILE_GIGAAM_V3, i18n.tr("settings_model_gigaam_v3"))],
            hint=i18n.tr("settings_speech_model_hint"),
        )
        npu = asr.npu_info()
        if npu is not None or self._draft.get("speech_compute_backend") == asr.BACKEND_NPU:
            npu_label = i18n.tr("settings_speech_backend_npu",
                                name=(npu or {}).get("name") or "Intel NPU")
            self._speech_backend = self._combo(
                right_sys, "settings_speech_backend", "speech_compute_backend",
                [(asr.BACKEND_CPU, i18n.tr("settings_speech_backend_cpu")),
                 (asr.BACKEND_NPU, npu_label)],
                hint=i18n.tr("settings_speech_backend_hint"),
            )

        sys_grid.addWidget(left_sys, 0, 0, Qt.AlignmentFlag.AlignTop)
        sys_grid.addWidget(right_sys, 0, 1, Qt.AlignmentFlag.AlignTop)
        sys_outer.addLayout(sys_grid)

        # Card 2 (full width): Account & Sync (horizontal, zero dead vertical space)
        sync = self._sync_section()

        # Card 3 (full width): Hardware & Compatibility 2x2 tile card
        hw = hardware.current()
        lang = i18n.language()
        hw_card = QWidget()
        hw_card.setObjectName("Card")
        hw_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hw_outer = QVBoxLayout(hw_card)
        hw_outer.setContentsMargins(16, 13, 16, 14)
        hw_outer.setSpacing(10)
        hw_title = QLabel(i18n.tr("hw_card_title"))
        hw_title.setObjectName("CardTitle")
        hw_outer.addWidget(hw_title)

        hw_grid = QGridLayout()
        hw_grid.setHorizontalSpacing(18)
        hw_grid.setVerticalSpacing(10)
        hw_grid.setColumnStretch(0, 1)
        hw_grid.setColumnStretch(1, 1)

        def _hw_tile(title_key: str, text: str, color: str | None = None) -> QWidget:
            box = QWidget()
            box.setObjectName("Plain")
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            t = QLabel(i18n.tr(title_key))
            t.setObjectName("Caption")
            val = QLabel(text)
            val.setObjectName("Value")
            val.setWordWrap(True)
            if color:
                val.setStyleSheet(f"color: {color}; font-weight: 600; background: transparent;")
            v.addWidget(t)
            v.addWidget(val)
            return box

        ram_unit = "ГБ ОЗУ" if lang == "ru" else "GB RAM"
        cores_unit = "ядер" if lang == "ru" else "cores"
        hw_grid.addWidget(
            _hw_tile("hw_cpu_ram",
                     f"{hw.cpu_model} ({hw.cpu_cores} {cores_unit}) · {hw.ram_gb} {ram_unit}"),
            0, 0,
        )

        gpu_st = hw.vulkan_gpu_status(lang)
        hw_grid.addWidget(
            _hw_tile("hw_gpu_vulkan",
                     f"{i18n.tr('hw_status_available')} · {gpu_st.message}" if gpu_st.available
                     else f"{i18n.tr('hw_status_cpu_only')} — {gpu_st.message}",
                     self._palette.ok if gpu_st.available else self._palette.warning),
            0, 1,
        )

        ai_st = hw.local_llm_status(lang)
        hw_grid.addWidget(
            _hw_tile("hw_local_ai",
                     f"{i18n.tr('hw_status_compatible')} · {ai_st.message}" if ai_st.available
                     else f"{i18n.tr('hw_status_limited')} — {ai_st.message}",
                     self._palette.ok if ai_st.available else self._palette.warning),
            1, 0,
        )

        if hw.npu_name:
            hw_grid.addWidget(
                _hw_tile("hw_npu",
                         f"{i18n.tr('hw_status_available')} · {hw.npu_name}",
                         self._palette.ok),
                1, 1,
            )

        hw_outer.addLayout(hw_grid)
        cards = [sys_card]
        if sync is not None:
            cards.append(sync)
        cards.append(hw_card)
        return _page(_page_header("nav_system", "subtitle_system"), *cards)

    def _build_statistics_page(self) -> QWidget:
        usage = getattr(self._controller, "usage", None)
        if usage is None:
            empty = Section(i18n.tr("settings_tab_statistics"))
            empty.add_row(None, self._muted_label(i18n.tr("history_empty")))
            return _page(_page_header("nav_statistics", "subtitle_statistics"), empty)
        self._stats_panel = StatsPanel(
            usage,
            lambda: self._settings.vocabulary_sync_enabled,
        )
        return _page(_page_header("nav_statistics", "subtitle_statistics"),
                     self._stats_panel, stretch_last=True)

    def _text_style_changed(self, *, mark_dirty: bool = True) -> None:
        value = str(self._text_style.currentData())
        if mark_dirty:
            self._update_draft(text_style=value)
        else:
            self._draft.update(text_style=value)
        self._text_style_hint.set_text(
            i18n.tr(f"settings_text_style_{value}_hint"))

    # -- updates ------------------------------------------------------

    def _check_updates(self) -> None:
        self._update_label.setText(i18n.tr("update_checking"))
        self._update_button.setEnabled(False)
        # The check is a blocking HTTPS request; letting the label paint
        # first is the difference between "Проверка" and a frozen dialog.
        QTimer.singleShot(0, self._run_update_check)

    def _run_update_check(self) -> None:
        try:
            info = PeriodicChecker().maybe_check(force=True)
        finally:
            self._update_button.setEnabled(True)

        if info is None:
            self._update_label.setText(i18n.tr("update_failed"))
        elif not info.is_newer:
            self._update_label.setText(i18n.tr("update_none"))
        elif not info.has_windows_asset:
            # Nothing to install, so nothing to open: the page would only
            # offer a build for another platform.
            self._update_label.setText(
                f"{i18n.tr('update_available', version=info.version)}, "
                f"{i18n.tr('update_no_windows_build')}"
            )
        else:
            # The check was asked for by hand, and what follows a found
            # update is always the same page. Opening it here saves the
            # step; the label still says what was found, in case the
            # browser opens behind this window.
            opened = QDesktopServices.openUrl(QUrl(info.page_url))
            self._update_label.setText(i18n.tr(
                "update_opened" if opened else "update_available",
                version=info.version))

    # -- widget helpers -----------------------------------------------

    def _muted_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Caption")
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def _color_row(self, section: Section, label_key: str, draft_key: str,
                   fallback: AccentColor,
                   hint: Optional[str] = None) -> ColorField:
        spec = ColorSpec.parse(self._draft.get(draft_key), ColorSpec.of(fallback))
        field = ColorField(spec,
                           lambda value, k=draft_key: self._update_draft(**{k: value}),
                           self._palette)
        section.add_row(i18n.tr(label_key), field,
                        HintIcon(hint) if hint else None)
        return field

    def _shortcut_row(self, section: Section, label_key: str, draft_key: str,
                      hint: Optional[str] = None) -> QPushButton:
        choice = HotkeyChoice.from_json(self._draft[draft_key],
                                        getattr(self._settings, draft_key))
        button = QPushButton(hotkey_name(choice, i18n.language()))
        button.setIcon(icons.icon("keyboard", self._palette.text_muted, 15))
        button.clicked.connect(lambda: self._record_shortcut(draft_key, button))
        section.add_row(i18n.tr(label_key), button,
                        HintIcon(hint) if hint else None)
        return button

    def _record_shortcut(self, draft_key: str, button: QPushButton) -> None:
        current = HotkeyChoice.from_json(self._draft[draft_key],
                                         getattr(self._settings, draft_key))
        # Global dictation must not fire from keys typed into the recorder.
        self._controller.listener.paused = True
        try:
            dialog = ShortcutRecorderDialog(current, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected:
                self._update_draft(**{draft_key: dialog.selected.to_json()})
                button.setText(hotkey_name(dialog.selected, i18n.language()))
        finally:
            self._controller.listener.paused = False
            self._controller.listener.reset_state()

    def _combo(self, section: Section, label_key: str, draft_key: str,
               options: list[tuple[str, str]],
               hint: Optional[str] = None) -> QComboBox:
        combo = QComboBox()
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(10)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for value, label in options:
            combo.addItem(label, value)
        current = str(self._draft.get(draft_key, ""))
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _, c=combo, k=draft_key: self._update_draft(**{k: c.currentData()}))
        section.add_row(i18n.tr(label_key), combo,
                        HintIcon(hint) if hint else None)
        return combo

    def _checkbox(self, section: Section, label_key: str, draft_key: str,
                  hint: Optional[str] = None) -> QCheckBox:
        box = QCheckBox(i18n.tr(label_key))
        box.setChecked(bool(self._draft.get(draft_key)))
        box.toggled.connect(lambda value, k=draft_key: self._update_draft(**{k: value}))
        section.add_row(None, box, HintIcon(hint) if hint else None)
        return box

    # -- filler words -------------------------------------------------

    def _filler_row(self, section: Section) -> QCheckBox:
        """The switch, plus a list of words folded away behind an arrow.

        The old row named two English sounds in its label and offered
        nothing else: "Убирать слова-паразиты (um, uh)". What it actually
        removed was six English interjections, which is close to useless
        for dictation in Russian. The words are now a list you can see and
        change — but they stay folded, because thirty checkboxes unfolded
        by default would bury every setting under them.
        """
        master = QCheckBox(i18n.tr("settings_remove_fillers"))
        master.setChecked(bool(self._draft.get("remove_filler_words")))
        master.toggled.connect(
            lambda value: self._draft.update(remove_filler_words=value))

        self._filler_toggle = QPushButton(i18n.tr("settings_fillers_list"))
        self._filler_toggle.setObjectName("Link")
        self._filler_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filler_toggle.clicked.connect(self._toggle_filler_panel)

        header = QWidget()
        header.setObjectName("Plain")
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(master)
        row.addWidget(self._filler_toggle)
        row.addStretch(1)
        section.add_row(None, header)

        self._filler_panel = QWidget()
        self._filler_panel.setObjectName("Plain")
        panel = QVBoxLayout(self._filler_panel)
        panel.setContentsMargins(0, 2, 0, 4)
        panel.setSpacing(8)
        note = QLabel(i18n.tr("settings_fillers_note"))
        note.setObjectName("Caption")
        note.setWordWrap(True)
        panel.addWidget(note)

        self._filler_grid = QGridLayout()
        self._filler_grid.setHorizontalSpacing(12)
        self._filler_grid.setVerticalSpacing(4)
        # Equal shares, set once: without them the columns are as wide as
        # whatever happens to be in them, so one long word dragged the rest
        # of the grid sideways.
        for column in range(FILLER_COLUMNS):
            self._filler_grid.setColumnStretch(column, 1)
        panel.addLayout(self._filler_grid)

        adder = QHBoxLayout()
        adder.setContentsMargins(0, 0, 0, 0)
        adder.setSpacing(8)
        self._filler_input = QLineEdit()
        self._filler_input.setPlaceholderText(i18n.tr("settings_fillers_add"))
        self._filler_input.returnPressed.connect(self._add_filler_word)
        add = QPushButton(i18n.tr("corrections_add"))
        add.setIcon(icons.icon("plus", self._palette.text_muted, 15))
        add.clicked.connect(self._add_filler_word)
        adder.addWidget(self._filler_input, 1)
        adder.addWidget(add)
        panel.addLayout(adder)

        self._filler_panel.setVisible(False)
        section.add_row(None, self._filler_panel)

        stored = [str(word) for word in self._draft.get("filler_words") or []]
        self._filler_enabled = {word.lower() for word in stored}
        known = {word for word, _ in PRESET_FILLERS}
        stored_custom = [str(word) for word in self._draft.get("filler_custom_words_v1") or []
                         if str(word).strip()]
        seen_custom: set[str] = set()
        self._filler_custom: list[str] = []
        for word in stored_custom + [w for w in stored if w.lower() not in known]:
            low = word.lower()
            if low not in known and low not in seen_custom:
                self._filler_custom.append(word)
                seen_custom.add(low)
        self._filler_before_enabled = list(stored)
        self._filler_before_custom = list(self._filler_custom)
        self._rebuild_filler_grid()
        self._update_filler_toggle()

        master.toggled.connect(self._filler_panel.setEnabled)
        self._filler_panel.setEnabled(master.isChecked())
        return master

    def _toggle_filler_panel(self) -> None:
        # isHidden, not isVisible: a widget on a tab that is not the current
        # one is not visible either, and asking the wrong question there
        # makes the first click on the arrow do nothing.
        self._filler_panel.setVisible(self._filler_panel.isHidden())
        self._update_filler_toggle()
        # The dialog is fixed-height until something asks it not to be, so
        # unfolding into a scroll area needs the layout re-run.
        self._filler_panel.updateGeometry()

    def _update_filler_toggle(self) -> None:
        expanded = not self._filler_panel.isHidden()
        self._filler_toggle.setIcon(icons.icon(
            "chevron-down" if expanded else "chevron-right",
            self._palette.text_muted, 14))
        self._filler_toggle.setText(i18n.tr(
            "settings_fillers_list_count", count=len(self._filler_enabled)))

    def _rebuild_filler_grid(self) -> None:
        while self._filler_grid.count():
            item = self._filler_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        words = [word for word, _ in PRESET_FILLERS] + self._filler_custom
        custom = {word.lower() for word in self._filler_custom}
        for index, word in enumerate(words):
            box = QCheckBox(word)
            box.setChecked(word.lower() in self._filler_enabled)
            box.toggled.connect(
                lambda value, w=word: self._set_filler_enabled(w, value))

            # Every word gets the same cell, whether it can be deleted or
            # not, and the delete button occupies the same width whether it
            # is there or not. A cell that changed shape when a word was
            # added moved every word after it.
            cell = QWidget()
            cell.setObjectName("Plain")
            line = QHBoxLayout(cell)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(4)
            line.addWidget(box)
            line.addStretch(1)
            drop = QPushButton()
            drop.setObjectName("Link")
            drop.setFixedSize(DROP_BUTTON_SIZE, DROP_BUTTON_SIZE)
            if word.lower() in custom:
                drop.setIcon(icons.icon("close", self._palette.text_faint, 12))
                drop.setCursor(Qt.CursorShape.PointingHandCursor)
                drop.setToolTip(i18n.tr("corrections_remove"))
                drop.clicked.connect(lambda _=False, w=word: self._drop_filler_word(w))
            else:
                # A spacer wearing a button's clothes: keeps the columns
                # identical without pretending presets can be removed.
                drop.setEnabled(False)
                drop.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            line.addWidget(drop)

            self._filler_grid.addWidget(cell, index // FILLER_COLUMNS,
                                        index % FILLER_COLUMNS)

    def _set_filler_enabled(self, word: str, enabled: bool) -> None:
        if enabled:
            self._filler_enabled.add(word.lower())
        else:
            self._filler_enabled.discard(word.lower())
        self._store_filler_words()
        self._update_filler_toggle()

    def _add_filler_word(self) -> None:
        word = " ".join(self._filler_input.text().split()).lower()
        self._filler_input.clear()
        known = {w.lower() for w, _ in PRESET_FILLERS} | {
            w.lower() for w in self._filler_custom}
        if not word:
            return
        if word not in known:
            self._filler_custom.append(word)
        # A word typed in is a word wanted: adding it also ticks it, and
        # typing one that is already on the list ticks that one instead of
        # silently doing nothing.
        self._filler_enabled.add(word)
        self._store_filler_words()
        self._rebuild_filler_grid()
        self._update_filler_toggle()

    def _drop_filler_word(self, word: str) -> None:
        self._filler_custom = [w for w in self._filler_custom
                               if w.lower() != word.lower()]
        self._filler_enabled.discard(word.lower())
        self._store_filler_words()
        self._rebuild_filler_grid()
        self._update_filler_toggle()

    def _store_filler_words(self) -> None:
        """Saved in list order, presets first, so the file stays readable."""
        words = [word for word, _ in PRESET_FILLERS] + self._filler_custom
        self._draft.update(
            filler_words=[word for word in words if word.lower() in self._filler_enabled],
            filler_custom_words_v1=list(self._filler_custom),
        )

    def _add_correction_item(self, correction: DraftEntry) -> None:
        item = QListWidgetItem()
        item.setData(PRIMARY_ROLE, correction.source)
        item.setData(SECONDARY_ROLE, correction.replacement)
        item.setData(HINT_ROLE, self._hint_state(correction))
        item.setData(Qt.ItemDataRole.UserRole, correction)
        item.setToolTip(f"{correction.source} → {correction.replacement}")
        self._corrections_list.addItem(item)

    def _add_correction(self) -> None:
        source = self._correction_source.text().strip()
        replacement = self._correction_replacement.text().strip()
        if not source or not replacement:
            return
        # The manual editor applies hygiene rules 1 and 3 only (spec §2).
        verdict = vocabulary_hygiene.review_manual(source, replacement)
        if isinstance(verdict, vocabulary_hygiene.Reject):
            self._warn(i18n.tr("corrections_rejected_no_letters"))
            return
        source, replacement = verdict.source, verdict.replacement
        # One answer per word: a new rule for a listed word replaces it.
        key = " ".join(source.casefold().split())
        for index in range(self._corrections_list.count() - 1, -1, -1):
            entry = self._corrections_list.item(index).data(Qt.ItemDataRole.UserRole)
            if " ".join(entry.source.casefold().split()) == key:
                self._corrections_list.takeItem(index)
        self._add_correction_item(DraftEntry(source, replacement))
        self._correction_source.clear()
        self._correction_replacement.clear()

    def _remove_correction(self) -> None:
        for item in self._corrections_list.selectedItems():
            self._corrections_list.takeItem(self._corrections_list.row(item))

    # -- save ---------------------------------------------------------

    def _save(self) -> None:
        previous = self._settings.snapshot()
        self._settings.apply(self._draft)
        prompts = getattr(self._controller, "prompts", None)
        for style in PROMPT_STYLES:
            wanted = str(self._draft.get(prompt_key(style)) or "").strip()
            if wanted != self._prompt_baseline[style]:
                if prompts is not None:
                    prompts.set_local(style, wanted)
                else:
                    self._settings.update_runtime({prompt_key(style): wanted})

        corr_key = system_prompt_key("correction")
        wanted_corr = str(self._draft.get(corr_key) or "").strip()
        if wanted_corr != self._correction_prompt_baseline:
            if prompts is not None:
                prompts.set_local_system("correction", wanted_corr)
            else:
                self._settings.update_runtime({corr_key: wanted_corr})

        filler_sync = getattr(self._controller, "filler_sync", None)
        if hasattr(self, "_filler_before_enabled"):
            if filler_sync is not None:
                filler_sync.record_local_change(
                    self._filler_before_enabled,
                    self._draft.get("filler_words") or [],
                    self._filler_before_custom,
                    self._filler_custom,
                )
            else:
                self._settings.update_runtime({
                    "filler_custom_words_v1": list(self._filler_custom),
                })

        pref_sync = getattr(self._controller, "pref_sync", None)
        if pref_sync is not None:
            pref_sync.record_local_diff(previous, self._draft)

        # Only the difference from what the list was loaded from: a rule
        # the sync or a learn changed meanwhile is not rolled back.
        self._corrections.apply_edits(self._corrections_baseline, self._current_entries())

        self._controller.apply_settings()

        model_changed = any(previous.get(key) != self._draft.get(key)
                            for key in ("speech_model_profile", "speech_compute_backend"))
        if model_changed:
            self._controller.reload_model()
        self._prompt_baseline = {style: str(self._draft.get(prompt_key(style)) or "")
                                 for style in PROMPT_STYLES}
        self._correction_prompt_baseline = str(
            self._draft.get(system_prompt_key("correction")) or "")
        self._corrections_baseline = self._current_entries()
        self._set_dirty(False)
        self.saved.emit()
        if not self._embedded:
            self.accept()


class CleanupPreviewDialog(QDialog):
    """Interactive vocabulary cleanup preview with grouped checkboxes.

    Supports :class:`vocabulary_hygiene.ExtendedAudit` (definite deletions,
    fixes, and unchecked manual review items) as well as legacy
    :class:`vocabulary_hygiene.CleanupPlan` inputs.
    """

    def __init__(self, audit_or_plan, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("corrections_cleanup_title"))
        self.resize(660, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)
        intro = QLabel(i18n.tr("corrections_cleanup_intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        if isinstance(audit_or_plan, vocabulary_hygiene.ExtendedAudit):
            audit = audit_or_plan
        else:
            # Legacy CleanupPlan wrapper
            items = [
                vocabulary_hygiene.AuditItem(
                    record=d.record,
                    category=vocabulary_hygiene.AUDIT_DEFINITE_DELETE,
                    reason_key=d.reason,
                    default_selected=True,
                )
                for d in audit_or_plan.deletions
            ] + [
                vocabulary_hygiene.AuditItem(
                    record=r.record,
                    category=vocabulary_hygiene.AUDIT_DEFINITE_FIX,
                    reason_key=r.reasons[0] if r.reasons else vocabulary_hygiene.REWRITE_TRIM,
                    default_selected=True,
                    fixed_source=r.source,
                    fixed_replacement=r.replacement,
                    rewrite_reasons=r.reasons,
                )
                for r in audit_or_plan.rewrites
            ]
            audit = vocabulary_hygiene.ExtendedAudit(items=items)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        select_all_btn = QPushButton(i18n.tr("cleanup_select_all"))
        deselect_all_btn = QPushButton(i18n.tr("cleanup_deselect_all"))
        toolbar.addWidget(select_all_btn)
        toolbar.addWidget(deselect_all_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._listing = QListWidget()
        self._listing.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._check_items: list[QListWidgetItem] = []

        def add_header(text: str) -> None:
            hdr = QListWidgetItem(text)
            font = hdr.font()
            font.setBold(True)
            hdr.setFont(font)
            hdr.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._listing.addItem(hdr)

        def reason_text(key: str) -> str:
            return i18n.tr(f"cleanup_reason_{key}")

        def add_audit_item(audit_item: vocabulary_hygiene.AuditItem) -> None:
            rec = audit_item.record
            if audit_item.fixed_source is not None and audit_item.fixed_replacement is not None:
                reasons = ", ".join(reason_text(r) for r in (audit_item.rewrite_reasons or (audit_item.reason_key,)))
                label = (f"{rec.source} → {rec.replacement}   ⇒   "
                         f"{audit_item.fixed_source} → {audit_item.fixed_replacement}   — {reasons}")
            else:
                label = f"{rec.source} → {rec.replacement}   — {reason_text(audit_item.reason_key)}"
            row_item = QListWidgetItem(label)
            row_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            row_item.setCheckState(
                Qt.CheckState.Checked if audit_item.default_selected else Qt.CheckState.Unchecked
            )
            row_item.setData(Qt.ItemDataRole.UserRole, audit_item.record_id)
            self._listing.addItem(row_item)
            self._check_items.append(row_item)

        for cat, title_key in (
            (vocabulary_hygiene.AUDIT_DEFINITE_DELETE, "cleanup_group_delete"),
            (vocabulary_hygiene.AUDIT_DEFINITE_FIX, "cleanup_group_fix"),
            (vocabulary_hygiene.AUDIT_REVIEW, "cleanup_group_review"),
        ):
            group = audit.by_category(cat)
            if not group:
                continue
            add_header(i18n.tr(title_key, count=len(group)))
            for audit_item in group:
                add_audit_item(audit_item)

        layout.addWidget(self._listing, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.tr("settings_cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        deselect_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        self._listing.itemChanged.connect(lambda _item: self._update_apply_label())
        self._update_apply_label()
        self.setStyleSheet(stylesheet(palette))

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._listing.blockSignals(True)
        for item in self._check_items:
            item.setCheckState(state)
        self._listing.blockSignals(False)
        self._update_apply_label()

    def _update_apply_label(self) -> None:
        count = len(self.selected_ids)
        self._ok_button.setText(i18n.tr("cleanup_apply_selected", count=count))
        self._ok_button.setEnabled(count > 0)

    @property
    def selected_ids(self) -> set[int]:
        return {
            int(item.data(Qt.ItemDataRole.UserRole))
            for item in self._check_items
            if item.checkState() == Qt.CheckState.Checked
        }
