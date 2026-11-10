"""Custom rewrite modes: the list under «Режим» and the editor dialog.

The Windows counterpart of ``customRewriteStylesBlock`` /
``presentCustomStyleEditor`` in the macOS ``ControlPanel.swift``. A row per
mode (colour, name, hotkey, Edit, Delete) plus «＋ Новый режим»; the dialog
asks for the name (up to 40), the colour (the macOS palette, or any colour
from the system picker), the instruction (the prompt, up to 4000) and the
mode's own hotkey.

Unlike the other settings these are written at once through
:class:`~superdictate.rewrite_styles.StyleStore`, not held in the window's
draft until «Сохранить»: the list is shared with the account sync, and a
draft snapshot taken when the window opened would roll back whatever the
sync brought in meanwhile.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..hotkeys import HotkeyChoice
from ..keynames import hotkey_name
from ..rewrite_styles import (DEFAULT_COLOR, MAX_INSTRUCTION, MAX_NAME, PALETTE,
                              CustomStyle, StyleStore, normalize_color, validate)
from . import icons

SWATCH = 26

#: The settings that already own a shortcut, for the clash check. The
#: primary dictation key is in the list because a custom mode on it would
#: never be reachable.
_BUILTIN_HOTKEYS = (
    ("hotkey", "settings_primary_hotkey"),
    ("history_hotkey", "settings_history_hotkey"),
    ("enter_hotkey", "settings_enter_hotkey"),
    ("correction_hotkey", "settings_correction_hotkey"),
    ("rewrite_hotkey", "settings_rewrite_hotkey"),
    ("rewrite_style_hotkey", "settings_rewrite_style_hotkey"),
)


def hotkey_owner(settings, store: StyleStore, choice: HotkeyChoice,
                 except_id: str = "") -> Optional[str]:
    """What already uses ``choice``: a setting's label or a mode's name."""
    for attribute, label_key in _BUILTIN_HOTKEYS:
        if getattr(settings, attribute, None) == choice:
            return i18n.tr(label_key)
    other = store.hotkey_taken(choice, except_id=except_id)
    return other.name if other is not None else None


class StyleEditorDialog(QDialog):
    """Create (``existing=None``) or edit one custom mode."""

    def __init__(self, store: StyleStore, settings, controller,
                 existing: Optional[CustomStyle] = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings
        self._controller = controller
        self._existing = existing
        self._color = normalize_color(existing.color if existing else DEFAULT_COLOR)
        self._hotkey: Optional[HotkeyChoice] = existing.hotkey if existing else None
        #: The saved result, once accepted.
        self.result_style: Optional[CustomStyle] = None

        self.setWindowTitle(i18n.tr("style_dialog_edit" if existing else "style_dialog_new"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(self._caption("style_name"))
        self._name = QLineEdit(existing.name if existing else "")
        self._name.setMaxLength(MAX_NAME)
        self._name.setPlaceholderText(i18n.tr("style_name_placeholder"))
        layout.addWidget(self._name)

        layout.addWidget(self._caption("style_instruction"))
        self._instruction = QPlainTextEdit()
        self._instruction.setPlainText(existing.instruction if existing else "")
        self._instruction.setMinimumHeight(120)
        layout.addWidget(self._instruction)
        self._counter = QLabel()
        self._counter.setObjectName("Caption")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._counter)
        self._instruction.textChanged.connect(self._update_counter)
        self._update_counter()

        layout.addWidget(self._caption("style_color"))
        self._swatches = QHBoxLayout()
        self._swatches.setSpacing(6)
        self._swatch_buttons: list[QPushButton] = []
        layout.addLayout(self._swatches)
        self._build_swatches()

        layout.addWidget(self._caption("style_hotkey"))
        row = QHBoxLayout()
        self._hotkey_button = QPushButton()
        self._hotkey_button.setIcon(icons.icon("keyboard", "#8e8e93", 15))
        self._hotkey_button.clicked.connect(self._record_hotkey)
        clear = QPushButton(i18n.tr("style_hotkey_clear"))
        clear.clicked.connect(self._clear_hotkey)
        row.addWidget(self._hotkey_button)
        row.addWidget(clear)
        row.addStretch(1)
        layout.addLayout(row)
        self._refresh_hotkey()

        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color: #ff453a;")
        self._error.hide()
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(i18n.tr("style_save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(i18n.tr("settings_cancel"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # -- pieces -----------------------------------------------------------

    @staticmethod
    def _caption(key: str) -> QLabel:
        label = QLabel(i18n.tr(key))
        label.setObjectName("Key")
        return label

    def _update_counter(self) -> None:
        self._counter.setText(f"{len(self._instruction.toPlainText().strip())} / {MAX_INSTRUCTION}")

    def _build_swatches(self) -> None:
        while self._swatches.count():
            item = self._swatches.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._swatch_buttons = []
        colors = list(PALETTE)
        if self._color not in colors:
            colors.append(self._color)  # a colour from the picker
        for color in colors:
            button = QPushButton()
            button.setFixedSize(SWATCH, SWATCH)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            selected = color == self._color
            button.setStyleSheet(
                f"QPushButton {{ background: {color}; border-radius: 6px;"
                f" border: {'3px solid #ffffff' if selected else '1px solid rgba(0,0,0,70)'}; }}")
            button.setToolTip(color)
            button.clicked.connect(lambda _=False, c=color: self._pick(c))
            self._swatches.addWidget(button)
            self._swatch_buttons.append(button)
        other = QPushButton(i18n.tr("style_color_other"))
        other.clicked.connect(self._pick_other)
        self._swatches.addWidget(other)
        self._swatches.addStretch(1)

    def _pick(self, color: str) -> None:
        self._color = normalize_color(color)
        self._build_swatches()

    def _pick_other(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, i18n.tr("settings_color_pick"))
        if chosen.isValid():
            self._pick(chosen.name())

    def _refresh_hotkey(self) -> None:
        self._hotkey_button.setText(
            hotkey_name(self._hotkey, i18n.language()) if self._hotkey
            else i18n.tr("settings_style_hotkey_none"))

    def _clear_hotkey(self) -> None:
        self._hotkey = None
        self._refresh_hotkey()

    def _record_hotkey(self) -> None:
        # Imported here: the recorder talks to user32, so a checkout without
        # Windows can still load this module for the pure tests.
        from .recorder import ShortcutRecorderDialog

        current = self._hotkey or HotkeyChoice(0x41, 0)
        # Global shortcuts must not fire from the keys typed into the recorder.
        self._controller.listener.paused = True
        try:
            dialog = ShortcutRecorderDialog(current, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected:
                self._hotkey = dialog.selected
                self._refresh_hotkey()
        finally:
            self._controller.listener.paused = False
            self._controller.listener.reset_state()

    def _fail(self, key: str, **kwargs) -> None:
        self._error.setText(i18n.tr(key, **kwargs))
        self._error.show()

    # -- save -----------------------------------------------------------------

    def _accept(self) -> None:
        try:
            name, instruction = validate(self._name.text(), self._instruction.toPlainText())
        except ValueError as exc:
            if str(exc) == "name":
                self._fail("style_error_name", limit=MAX_NAME)
            else:
                self._fail("style_error_instruction", limit=MAX_INSTRUCTION)
            return
        if self._hotkey is not None:
            owner = hotkey_owner(self._settings, self._store, self._hotkey,
                                 self._existing.id if self._existing else "")
            if owner:
                self._fail("style_error_hotkey_taken", owner=owner)
                return
        if self._existing is None:
            self.result_style = self._store.create(name, instruction, self._color, self._hotkey)
        else:
            self.result_style = self._store.update(
                self._existing.id, name, instruction, self._color, self._hotkey)
        self.accept()


class CustomStylesBlock(QWidget):
    """The rows plus «＋ Новый режим». Rebuilt by :meth:`reload`."""

    def __init__(self, store: StyleStore, settings, controller, palette,
                 on_changed: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        self._store = store
        self._settings = settings
        self._controller = controller
        self._palette = palette
        self._on_changed = on_changed

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.reload()

    def reload(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._drop_layout(item.layout())

        header = QHBoxLayout()
        title = QLabel(i18n.tr("settings_rewrite_custom"))
        title.setObjectName("Key")
        header.addWidget(title)
        header.addStretch(1)
        add = QPushButton(i18n.tr("settings_style_new"))
        add.setToolTip(i18n.tr("settings_rewrite_custom_hint"))
        add.clicked.connect(self._new)
        header.addWidget(add)
        self._layout.addLayout(header)

        styles = self._store.all()
        if not styles:
            empty = QLabel(i18n.tr("settings_rewrite_custom_empty"))
            empty.setObjectName("Caption")
            self._layout.addWidget(empty)
        for style in styles:
            self._layout.addLayout(self._row(style))

    @staticmethod
    def _drop_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
                item.widget().deleteLater()
        layout.deleteLater()

    def _row(self, style: CustomStyle) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        chip = QLabel()
        chip.setPixmap(icons.swatch(style.color, 14).pixmap(14, 14))
        row.addWidget(chip)
        name = QLabel(style.name)
        row.addWidget(name)
        hotkey = QLabel(hotkey_name(style.hotkey, i18n.language()) if style.hotkey
                        else i18n.tr("settings_style_hotkey_none"))
        hotkey.setObjectName("Caption")
        row.addWidget(hotkey)
        row.addStretch(1)
        edit = QPushButton(i18n.tr("settings_style_edit"))
        edit.clicked.connect(lambda _=False, s=style: self._edit(s))
        delete = QPushButton(i18n.tr("settings_style_delete"))
        delete.clicked.connect(lambda _=False, s=style: self._delete(s))
        row.addWidget(edit)
        row.addWidget(delete)
        return row

    # -- actions ----------------------------------------------------------

    def _new(self) -> None:
        dialog = StyleEditorDialog(self._store, self._settings, self._controller, None, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload()
            self._on_changed()

    def _edit(self, style: CustomStyle) -> None:
        dialog = StyleEditorDialog(self._store, self._settings, self._controller, style, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload()
            self._on_changed()

    def _delete(self, style: CustomStyle) -> None:
        answer = QMessageBox.question(
            self, i18n.tr("settings_rewrite_custom"),
            i18n.tr("settings_style_delete_confirm", name=style.name))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._store.delete(style.id)
        self.reload()
        self._on_changed()
