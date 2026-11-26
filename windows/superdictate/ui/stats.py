"""Usage statistics view — parity with macOS 1.0.3 StatisticsSectionView.

Features:
* Period selector (Today / 7 days / 30 days / All time) with exact date span
  and device count so all 4 top KPI cards share one unambiguous timeframe.
* 4 clear KPI tiles: Dictations, Volume (chars + approx words), Speech time
  (explicit h/min/sec units — never ambiguous H:MM), and Time saved (vs ~200
  chars/min typing + real speed multiplier).
* Dense, labeled 14-day bar chart with Chars / Dictations toggle, horizontal
  reference lines, value callouts above non-zero bars, and rich tooltips.
* Side-by-side bottom card: compact 15-week Activity Heatmap (left, with
  Mon/Wed/Fri weekday labels, 90th-percentile scale, legend) + structured
  Summary & Insights column (right: Today/All-time anchor, active days,
  streaks, peak day, avg dictation, and This PC vs Other Devices split bar).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from . import icons
from .theme import Palette, palette

WEEKS = 15
BAR_DAYS = 14
COMPACT_FROM = 1000
TYPING_CHARS_PER_MIN = 200.0
AVG_CHARS_PER_WORD = 6.5


def _card(parent: QWidget | None = None) -> QWidget:
    widget = QWidget(parent)
    widget.setObjectName("Card")
    return widget


def _blend(base: str, other: str, ratio: float) -> QColor:
    a, b = QColor(base), QColor(other)
    t = max(0.0, min(1.0, ratio))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def format_int(value: int) -> str:
    """Locale-spaced integer (e.g. '2 596' in RU, '2,596' in EN)."""
    n = max(0, int(value))
    if i18n.language() == "ru":
        return f"{n:,}".replace(",", " ")
    return f"{n:,}"


def readable_big_int(value: int) -> str:
    n = max(0, int(value))
    if n < 1_000_000:
        return format_int(n)
    scaled = n / 1_000_000.0
    text = f"{scaled:.2f}" if scaled < 10 else f"{scaled:.1f}"
    if i18n.language() == "ru":
        return text.replace(".", ",") + " млн"
    return text + " M"


def readable_duration(seconds: float) -> str:
    total = max(0, round(float(seconds)))
    ru = i18n.language() == "ru"
    h, m, s = ("ч", "мин", "сек") if ru else ("h", "min", "sec")
    if total >= 3600:
        hours, rem = divmod(total, 3600)
        mins = rem // 60
        return f"{hours} {h} {mins} {m}" if mins else f"{hours} {h}"
    if total >= 60:
        mins, secs = divmod(total, 60)
        if mins >= 10 or secs == 0:
            return f"{mins} {m}"
        return f"{mins} {m} {secs} {s}"
    return f"{total} {s}"


def readable_approx_words(chars: int, exact_words: int = 0) -> str:
    words = exact_words if exact_words > 0 else round(max(0, chars) / AVG_CHARS_PER_WORD)
    ru = i18n.language() == "ru"
    if words <= 0:
        return "0 слов" if ru else "0 words"
    prefix = "" if exact_words > 0 else "≈ "
    if words >= 10_000:
        k = round(words / 1000.0)
        return f"{prefix}{format_int(k)} тыс. слов" if ru else f"{prefix}{format_int(k)}k words"
    return f"{prefix}{format_int(words)} слов" if ru else f"{prefix}{format_int(words)} words"


def _short_date(d: date) -> str:
    return f"{d.day} {i18n.month_abbr(d.month)}"


@dataclass
class _PeriodAggregate:
    dictations: int
    characters: int
    words: int
    audio_seconds: float
    active_days: int
    span_days: int
    start_date: date
    end_date: date
    peak_day: Optional[object]

    @property
    def avg_dicts_per_active_day(self) -> float:
        return self.dictations / self.active_days if self.active_days else 0.0

    @property
    def avg_chars_per_dict(self) -> int:
        return round(self.characters / self.dictations) if self.dictations else 0

    @property
    def avg_secs_per_dict(self) -> float:
        return self.audio_seconds / self.dictations if self.dictations else 0.0

    @property
    def chars_per_min(self) -> int:
        if self.audio_seconds < 1.0:
            return 0
        return round(self.characters / (self.audio_seconds / 60.0))

    @property
    def speed_multiplier(self) -> float:
        return self.chars_per_min / TYPING_CHARS_PER_MIN if self.chars_per_min else 0.0

    @property
    def saved_seconds(self) -> float:
        typing_secs = (self.characters / TYPING_CHARS_PER_MIN) * 60.0
        return max(0.0, typing_secs - self.audio_seconds)


def _compute_period(period: str, by_day: dict, today: date) -> _PeriodAggregate:
    if period == "today":
        start = today
        span = 1
        row = by_day.get(today.isoformat())
        rows = [row] if row else []
    elif period == "7d":
        start = today - timedelta(days=6)
        span = 7
        rows = [by_day[(today - timedelta(days=i)).isoformat()]
                for i in range(7)
                if (today - timedelta(days=i)).isoformat() in by_day]
    elif period == "30d":
        start = today - timedelta(days=29)
        span = 30
        rows = [by_day[(today - timedelta(days=i)).isoformat()]
                for i in range(30)
                if (today - timedelta(days=i)).isoformat() in by_day]
    else:
        rows = [r for r in by_day.values() if r.dictations > 0 or r.characters > 0]
        if rows:
            first_str = min(r.day for r in rows)
            try:
                start = min(date.fromisoformat(first_str), today)
            except ValueError:
                start = today
            span = max(1, (today - start).days + 1)
        else:
            start = today
            span = 1

    dicts = chars = words = active = 0
    audio = 0.0
    peak = None
    for row in rows:
        if row.dictations <= 0 and row.characters <= 0:
            continue
        dicts += row.dictations
        chars += row.characters
        words += row.words
        audio += row.audio_seconds
        active += 1
        if peak is None or (row.characters, row.dictations) > (peak.characters, peak.dictations):
            peak = row

    return _PeriodAggregate(
        dictations=dicts, characters=chars, words=words,
        audio_seconds=audio, active_days=active, span_days=span,
        start_date=start, end_date=today, peak_day=peak,
    )


def _compute_streaks(by_day: dict, today: date) -> tuple[int, int]:
    active_keys = {k for k, r in by_day.items() if r.dictations > 0}
    if not active_keys:
        return 0, 0

    cursor = today
    if cursor.isoformat() not in active_keys:
        yesterday = today - timedelta(days=1)
        if yesterday.isoformat() in active_keys:
            cursor = yesterday
    current = 0
    while cursor.isoformat() in active_keys:
        current += 1
        cursor -= timedelta(days=1)

    parsed = sorted(date.fromisoformat(k) for k in active_keys)
    longest = run = 0
    prev = None
    for d in parsed:
        if prev is not None and d == prev + timedelta(days=1):
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        prev = d
    return current, longest


class MetricTile(QWidget):
    """One KPI tile with icon, caption, tabular bold value, and context unit."""

    def __init__(self, icon_name: str, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._palette = palette()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(5)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, self._palette.text_faint, 13))
        glyph.setStyleSheet("background: transparent;")
        self._caption = QLabel(caption)
        self._caption.setObjectName("CardTitle")
        head.addWidget(glyph)
        head.addWidget(self._caption)
        head.addStretch(1)
        layout.addLayout(head)

        self._value = QLabel("0")
        self._value.setObjectName("Metric")
        self._value.setStyleSheet("font-size: 19px; font-weight: 700; background: transparent;")
        layout.addWidget(self._value)

        self._unit = QLabel("")
        self._unit.setObjectName("MetricUnit")
        layout.addWidget(self._unit)

    def set_value(self, value: str, unit: str = "", tooltip: str = "") -> None:
        self._value.setText(value)
        self._unit.setText(unit)
        self.setToolTip(tooltip)


class BarChart(QWidget):
    """14-day labeled bar chart with horizontal gridlines and hover tooltips."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._palette = palette()
        self._entries: list[tuple[date, int, int, float]] = []
        self._metric = "chars"
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def set_data(self, by_day: dict, metric: str = "chars") -> None:
        self._metric = metric
        today = date.today()
        self._entries = []
        for offset in range(BAR_DAYS - 1, -1, -1):
            d = today - timedelta(days=offset)
            row = by_day.get(d.isoformat())
            self._entries.append((
                d,
                row.dictations if row else 0,
                row.characters if row else 0,
                row.audio_seconds if row else 0.0,
            ))
        self.update()

    def _val(self, entry: tuple[date, int, int, float]) -> int:
        return entry[2] if self._metric == "chars" else entry[1]

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._entries:
            return
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        axis_w = 36.0
        plot_w = max(20.0, self.width() - axis_w)
        top_pad = 17.0
        bottom_h = 18.0
        usable = max(16.0, self.height() - top_pad - bottom_h)
        baseline_y = top_pad + usable

        peak = max((self._val(e) for e in self._entries), default=0)
        count = len(self._entries)
        slot = plot_w / count
        bar_w = min(26.0, max(10.0, slot * 0.68))

        small_font = QFont(self.font())
        small_font.setPointSizeF(7.5)
        painter.setFont(small_font)

        # Horizontal reference gridlines (0%, 50%, 100%)
        grid_color = QColor(p.card_border)
        levels = [(0.0, 0), (0.5, round(peak / 2)), (1.0, peak)] if peak else [(0.0, 0)]
        for frac, lval in levels:
            y = round(baseline_y - usable * frac) + 0.5
            pen = QPen(grid_color, 1.0)
            if frac > 0:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(0, int(y), int(plot_w - 2), int(y))
            if frac > 0:
                painter.setPen(QColor(p.text_faint))
                painter.drawText(
                    QRectF(plot_w + 4, y - 7, axis_w - 4, 14),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    compact(lval),
                )

        # Bars + value callouts + X dates
        for idx, entry in enumerate(self._entries):
            d = entry[0]
            val = self._val(entry)
            cx = slot * (idx + 0.5)
            h = max(5.0, (val / peak) * usable) if (val and peak) else 3.0
            rect = QRectF(cx - bar_w / 2, baseline_y - h, bar_w, h)
            path = QPainterPath()
            path.addRoundedRect(rect, 4, 4)
            if val and peak:
                ratio = val / peak
                painter.fillPath(path, _blend(p.grid_empty, p.busy, 0.40 + 0.60 * ratio))
            else:
                painter.fillPath(path, QColor(p.grid_empty))

            if val:
                painter.setPen(QColor(p.text_muted))
                painter.drawText(
                    QRectF(cx - slot / 2 - 2, max(0.0, rect.top() - 14), slot + 4, 13),
                    Qt.AlignmentFlag.AlignCenter,
                    compact(val),
                )

            is_today = idx == count - 1
            if is_today or (idx % 2 == 1 and idx < count - 1):
                painter.setPen(QColor(p.text_muted if is_today else p.text_faint))
                painter.drawText(
                    QRectF(cx - slot / 2, baseline_y + 3, slot, bottom_h - 3),
                    Qt.AlignmentFlag.AlignCenter,
                    d.strftime("%d.%m"),
                )
        painter.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        axis_w = 36.0
        plot_w = max(1.0, self.width() - axis_w)
        x = event.position().x()
        if not self._entries or x < 0 or x > plot_w:
            self.setToolTip("")
            return
        idx = int(x // (plot_w / len(self._entries)))
        if 0 <= idx < len(self._entries):
            d, dicts, chars, secs = self._entries[idx]
            ru = i18n.language() == "ru"
            if dicts > 0:
                self.setToolTip(
                    f"{d.strftime('%d.%m.%Y')}: {dicts} {'дикт.' if ru else 'dict.'} · "
                    f"{format_int(chars)} {'симв.' if ru else 'chars'} · {readable_duration(secs)}"
                )
            else:
                self.setToolTip(f"{d.strftime('%d.%m.%Y')}: {'нет диктовок' if ru else 'no dictations'}")
            return
        self.setToolTip("")


class ActivityGrid(QWidget):
    """Compact 15-week heatmap with Mon/Wed/Fri weekday labels & 90th-pct scale."""

    CELL = 13
    GAP = 3
    MONTH_ROW = 16
    WEEKDAY_COL = 24

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._palette = palette()
        self._by_day: dict = {}
        w = self.WEEKDAY_COL + WEEKS * (self.CELL + self.GAP) - self.GAP
        h = self.MONTH_ROW + 7 * (self.CELL + self.GAP) - self.GAP
        self.setFixedSize(w, h)
        self.setMouseTracking(True)

    def set_days(self, by_day: dict) -> None:
        self._by_day = by_day
        self.update()

    def _grid_start(self) -> date:
        today = date.today()
        start = today - timedelta(days=(WEEKS - 1) * 7)
        return start - timedelta(days=start.weekday())

    def active_days_in_window(self) -> int:
        start = self._grid_start()
        today = date.today()
        count = 0
        for week in range(WEEKS):
            for wd in range(7):
                d = start + timedelta(days=week * 7 + wd)
                if d <= today:
                    row = self._by_day.get(d.isoformat())
                    if row and row.dictations > 0:
                        count += 1
        return count

    def paintEvent(self, event) -> None:  # noqa: N802
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        positive = sorted(r.characters for r in self._by_day.values() if r.characters > 0)
        scale_peak = positive[min(len(positive) - 1, int((len(positive) - 1) * 0.90))] if positive else 0

        start = self._grid_start()
        today = date.today()
        step = self.CELL + self.GAP

        font = QFont(self.font())
        font.setPointSizeF(7.5)
        painter.setFont(font)

        day_labels = ((0, "Пн"), (2, "Ср"), (4, "Пт")) if i18n.language() == "ru" else ((0, "Mo"), (2, "We"), (4, "Fr"))
        painter.setPen(QColor(p.text_faint))
        for wd, text in day_labels:
            painter.drawText(
                QRectF(0, self.MONTH_ROW + wd * step, self.WEEKDAY_COL - 3, self.CELL),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
        painter.setPen(Qt.PenStyle.NoPen)

        last_month = ""
        last_label_week = -3
        for week in range(WEEKS):
            for wd in range(7):
                d = start + timedelta(days=week * 7 + wd)
                if d > today:
                    continue
                rect = QRectF(self.WEEKDAY_COL + week * step, self.MONTH_ROW + wd * step,
                              self.CELL, self.CELL)
                path = QPainterPath()
                path.addRoundedRect(rect, 3, 3)
                row = self._by_day.get(d.isoformat())
                chars = row.characters if row else 0
                if chars and scale_peak:
                    ratio = min(1.0, chars / scale_peak)
                    colour = _blend(p.grid_empty, p.busy, 0.28 + 0.72 * ratio)
                else:
                    colour = QColor(p.grid_empty)
                painter.fillPath(path, colour)

            month = i18n.month_abbr((start + timedelta(days=week * 7)).month)
            if month != last_month:
                last_month = month
                if week - last_label_week >= 3:
                    painter.setPen(QColor(p.text_faint))
                    painter.drawText(
                        QRectF(self.WEEKDAY_COL + week * step, 0, step * 3, self.MONTH_ROW - 2),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        month,
                    )
                    painter.setPen(Qt.PenStyle.NoPen)
                    last_label_week = week
        painter.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        step = self.CELL + self.GAP
        week = int((event.position().x() - self.WEEKDAY_COL) // step)
        wd = int((event.position().y() - self.MONTH_ROW) // step)
        if 0 <= week < WEEKS and 0 <= wd < 7:
            d = self._grid_start() + timedelta(days=week * 7 + wd)
            if d <= date.today():
                row = self._by_day.get(d.isoformat())
                ru = i18n.language() == "ru"
                if row and row.dictations > 0:
                    self.setToolTip(
                        f"{d.strftime('%d.%m.%Y')}: {row.dictations} {'дикт.' if ru else 'dict.'} · "
                        f"{format_int(row.characters)} {'симв.' if ru else 'chars'} · "
                        f"{readable_duration(row.audio_seconds)}"
                    )
                else:
                    self.setToolTip(f"{d.strftime('%d.%m.%Y')}: {'нет диктовок' if ru else 'no dictations'}")
                return
        self.setToolTip("")


class _DeviceSplitBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fraction = 1.0
        self._palette = palette()
        self.setFixedHeight(5)

    def set_fraction(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QPainterPath()
        bg.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 2.5, 2.5)
        painter.fillPath(bg, QColor("#a855f7"))
        local_w = self.width() * self._fraction
        if local_w > 0.5:
            fg = QPainterPath()
            fg.addRoundedRect(QRectF(0, 0, local_w, self.height()), 2.5, 2.5)
            painter.fillPath(fg, QColor(self._palette.busy))
        painter.end()


class StatsPanel(QWidget):
    """Full Statistics view: period selector, 4 KPI tiles, 14-day chart,
    and side-by-side 15-week heatmap + Summary & Insights panel."""

    def __init__(self, usage, all_devices=None, parent=None) -> None:
        super().__init__(parent)
        self._usage = usage
        self._all_devices = all_devices or (lambda: False)
        self._palette: Palette = palette()
        self._period = "all"
        self._chart_metric = "chars"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Header row: date span subtitle + period selector
        header = QHBoxLayout()
        header.setSpacing(8)
        self._span_label = QLabel("")
        self._span_label.setObjectName("Caption")
        header.addWidget(self._span_label)
        self._scope = QLabel(i18n.tr("stats_all_devices"))
        self._scope.setObjectName("Caption")
        self._scope.setVisible(False)
        header.addWidget(self._scope)
        header.addStretch(1)

        self._period_group = QButtonGroup(self)
        self._period_group.setExclusive(True)
        for key, tr_key in (
            ("today", "stats_period_today"),
            ("7d", "stats_period_7d"),
            ("30d", "stats_period_30d"),
            ("all", "stats_period_all"),
        ):
            btn = QPushButton(i18n.tr(tr_key))
            btn.setCheckable(True)
            btn.setChecked(key == self._period)
            btn.clicked.connect(lambda _=False, k=key: self._set_period(k))
            self._period_group.addButton(btn)
            header.addWidget(btn)
        layout.addLayout(header)

        # 1. Four period-consistent KPI tiles
        tiles = QGridLayout()
        tiles.setSpacing(10)
        self._tiles = {
            "dicts": MetricTile("mic", i18n.tr("stats_metric_dictations")),
            "volume": MetricTile("words", i18n.tr("stats_metric_volume")),
            "speech": MetricTile("clock", i18n.tr("stats_metric_speech")),
            "saved": MetricTile("sparkles", i18n.tr("stats_metric_saved")),
        }
        for col, key in enumerate(("dicts", "volume", "speech", "saved")):
            tiles.addWidget(self._tiles[key], 0, col)
            tiles.setColumnStretch(col, 1)
        layout.addLayout(tiles)

        # 2. 14-day Bar Chart card with metric switcher + 14-day summary
        bars_card = _card()
        bars_layout = QVBoxLayout(bars_card)
        bars_layout.setContentsMargins(14, 12, 14, 10)
        bars_layout.setSpacing(8)
        bars_head = QHBoxLayout()
        bars_head.setSpacing(8)
        bars_title = QLabel(i18n.tr("stats_last_14_days"))
        bars_title.setObjectName("CardTitle")
        bars_head.addWidget(bars_title)
        bars_head.addStretch(1)
        self._fourteen_summary = QLabel("")
        self._fourteen_summary.setObjectName("Caption")
        bars_head.addWidget(self._fourteen_summary)
        self._metric_group = QButtonGroup(self)
        self._metric_group.setExclusive(True)
        for mkey, tr_key in (("chars", "stats_chart_chars"), ("dicts", "stats_chart_dicts")):
            btn = QPushButton(i18n.tr(tr_key))
            btn.setCheckable(True)
            btn.setChecked(mkey == self._chart_metric)
            btn.clicked.connect(lambda _=False, k=mkey: self._set_chart_metric(k))
            self._metric_group.addButton(btn)
            bars_head.addWidget(btn)
        bars_layout.addLayout(bars_head)
        self._bars = BarChart()
        bars_layout.addWidget(self._bars, 1)
        layout.addWidget(bars_card, 1)

        # 3. Side-by-side bottom card: 15-week Heatmap (left) + Summary & Insights (right)
        bottom_card = _card()
        bottom_outer = QVBoxLayout(bottom_card)
        bottom_outer.setContentsMargins(14, 12, 14, 12)
        bottom_outer.setSpacing(8)
        bottom_title = QLabel(i18n.tr("stats_activity_summary"))
        bottom_title.setObjectName("CardTitle")
        bottom_outer.addWidget(bottom_title)

        split = QHBoxLayout()
        split.setSpacing(14)

        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        self._grid = ActivityGrid()
        left_col.addWidget(self._grid)
        legend_row = QHBoxLayout()
        legend_row.setSpacing(4)
        self._active_window_label = QLabel("")
        self._active_window_label.setObjectName("Caption")
        legend_row.addWidget(self._active_window_label)
        legend_row.addStretch(1)
        less = QLabel(i18n.tr("stats_less"))
        less.setObjectName("Caption")
        legend_row.addWidget(less)
        for level in (0.0, 0.30, 0.55, 0.78, 1.0):
            sw = QWidget()
            sw.setFixedSize(9, 9)
            col_hex = (self._palette.grid_empty if level == 0.0
                       else _blend(self._palette.grid_empty, self._palette.busy, level).name())
            sw.setStyleSheet(f"background: {col_hex}; border-radius: 2px;")
            legend_row.addWidget(sw)
        more = QLabel(i18n.tr("stats_more"))
        more.setObjectName("Caption")
        legend_row.addWidget(more)
        left_col.addLayout(legend_row)
        split.addLayout(left_col)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {self._palette.card_border};")
        split.addWidget(divider)

        right_col = QVBoxLayout()
        right_col.setSpacing(6)
        self._insight_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key in ("anchor", "active_days", "streak", "peak_day", "avg_dict"):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)
            k_lbl = QLabel("")
            k_lbl.setObjectName("Key")
            v_lbl = QLabel("—")
            v_lbl.setObjectName("Value")
            v_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(k_lbl)
            row_layout.addStretch(1)
            row_layout.addWidget(v_lbl)
            right_col.addLayout(row_layout)
            self._insight_rows[key] = (k_lbl, v_lbl)

        self._split_widget = QWidget()
        self._split_widget.setObjectName("Plain")
        split_v = QVBoxLayout(self._split_widget)
        split_v.setContentsMargins(0, 6, 0, 0)
        split_v.setSpacing(4)
        self._split_bar = _DeviceSplitBar()
        split_v.addWidget(self._split_bar)
        self._split_caption = QLabel("")
        self._split_caption.setObjectName("Caption")
        split_v.addWidget(self._split_caption)
        right_col.addWidget(self._split_widget)
        right_col.addStretch(1)

        split.addLayout(right_col, 1)
        bottom_outer.addLayout(split)
        layout.addWidget(bottom_card)

        self.refresh()

    def _set_period(self, period: str) -> None:
        if period != self._period:
            self._period = period
            self.refresh()

    def _set_chart_metric(self, metric: str) -> None:
        if metric != self._chart_metric:
            self._chart_metric = metric
            self.refresh()

    def refresh(self) -> None:
        today = date.today()
        all_days = self._usage.all_days()
        by_day = {d.day: d for d in all_days}

        agg = _compute_period(self._period, by_day, today)
        all_agg = _compute_period("all", by_day, today)
        today_row = by_day.get(today.isoformat())
        today_dicts = today_row.dictations if today_row else 0
        today_chars = today_row.characters if today_row else 0
        cur_streak, best_streak = _compute_streaks(by_day, today)

        ru = i18n.language() == "ru"
        all_devices_on = bool(self._all_devices())
        self._scope.setVisible(all_devices_on)
        remote_devs = self._usage.remote_device_count() if hasattr(self._usage, "remote_device_count") else 0
        synced_multi = all_devices_on and remote_devs > 0

        if self._period == "today":
            span = f"{i18n.tr('stats_period_today')} · {_short_date(today)}"
        elif self._period == "7d":
            span = f"{i18n.tr('stats_period_7d')} · {_short_date(agg.start_date)} – {_short_date(agg.end_date)}"
        elif self._period == "30d":
            span = f"{i18n.tr('stats_period_30d')} · {_short_date(agg.start_date)} – {_short_date(agg.end_date)}"
        else:
            span = (f"{i18n.tr('stats_period_all')} · {_short_date(agg.start_date)} – {_short_date(agg.end_date)}"
                    if agg.dictations > 0
                    else ("За всё время · данных пока нет" if ru else "All time · no data yet"))
        scope = (f" · {1 + remote_devs} {'устр.' if ru else 'devices'}"
                 if synced_multi else f" · {i18n.tr('stats_this_pc')}")
        self._span_label.setText(span + scope)

        # KPI 1: Dictations
        if agg.dictations == 0:
            dicts_sub = "нет записей" if ru else "no records"
        elif self._period == "today":
            dicts_sub = "за сегодня" if ru else "today"
        else:
            avg_d = max(1, round(agg.avg_dicts_per_active_day))
            dicts_sub = f"~{format_int(avg_d)} / {'активн. день' if ru else 'active day'}"
        self._tiles["dicts"].set_value(format_int(agg.dictations), dicts_sub)

        # KPI 2: Volume (chars + words)
        vol_sub = (f"{'симв.' if ru else 'chars'} · {readable_approx_words(agg.characters, agg.words)}"
                   if agg.characters > 0 else ("символов" if ru else "characters"))
        self._tiles["volume"].set_value(
            readable_big_int(agg.characters),
            vol_sub,
            f"{format_int(agg.characters)} {'симв.' if ru else 'chars'}",
        )

        # KPI 3: Speech time
        speech_val = readable_duration(agg.audio_seconds) if agg.audio_seconds > 0 else ("0 сек" if ru else "0 sec")
        speech_sub = (f"~{readable_duration(agg.avg_secs_per_dict)} / {'дикт.' if ru else 'dict.'}"
                      if agg.dictations > 0 else ("время речи" if ru else "speech time"))
        self._tiles["speech"].set_value(speech_val, speech_sub)

        # KPI 4: Time saved
        saved_val = (f"~{readable_duration(agg.saved_seconds)}" if agg.saved_seconds >= 30
                     else ("< 1 мин" if (agg.characters > 0 and ru) else ("< 1 min" if agg.characters > 0 else "—")))
        if agg.chars_per_min > 0:
            mult = f"{agg.speed_multiplier:.1f}".replace(".", ",") if ru else f"{agg.speed_multiplier:.1f}"
            saved_sub = f"{format_int(agg.chars_per_min)} {'симв./мин' if ru else 'ch/min'} · {mult}×"
        else:
            saved_sub = "vs ~200 симв./мин" if ru else "vs ~200 ch/min"
        self._tiles["saved"].set_value(
            saved_val,
            saved_sub,
            "Оценка относительно ручного набора ~200 симв./мин." if ru
            else "Estimated time saved vs typing at ~200 chars/min.",
        )

        # 14-day bar chart
        f_dicts = f_chars = 0
        for offset in range(BAR_DAYS):
            row = by_day.get((today - timedelta(days=offset)).isoformat())
            if row:
                f_dicts += row.dictations
                f_chars += row.characters
        self._fourteen_summary.setText(
            f"{format_int(f_dicts)} {'дикт.' if ru else 'dict.'} · {format_int(f_chars)} {'симв.' if ru else 'chars'}"
        )
        self._bars.set_data(by_day, self._chart_metric)

        # 15-week heatmap + legend
        self._grid.set_days(by_day)
        active_win = self._grid.active_days_in_window()
        self._active_window_label.setText(
            f"{active_win} активн. дн. за {WEEKS} нед." if ru else f"{active_win} active days in {WEEKS} wks"
        )

        # Right-hand Summary & Insights rows
        k, v = self._insight_rows["anchor"]
        if self._period == "today":
            k.setText(i18n.tr("stats_period_all"))
            v.setText(f"{format_int(all_agg.dictations)} {'дикт.' if ru else 'dict.'} · {compact(all_agg.characters)}")
        else:
            k.setText(i18n.tr("stats_period_today"))
            v.setText(f"{format_int(today_dicts)} {'дикт.' if ru else 'dict.'} · {format_int(today_chars)} {'симв.' if ru else 'ch'}")

        k, v = self._insight_rows["active_days"]
        k.setText(i18n.tr("stats_active_days"))
        if self._period == "today":
            v.setText(("Активен" if agg.active_days else "Нет записей") if ru else ("Active" if agg.active_days else "Inactive"))
        else:
            v.setText(f"{agg.active_days} {'из' if ru else 'of'} {agg.span_days}")

        k, v = self._insight_rows["streak"]
        k.setText(i18n.tr("stats_streak"))
        if best_streak == 0:
            v.setText("—")
        elif cur_streak > 0:
            v.setText(f"{cur_streak} дн. (рекорд {best_streak})" if ru else f"{cur_streak}d (best {best_streak}d)")
        else:
            v.setText(f"рекорд {best_streak} дн." if ru else f"best {best_streak}d")

        k, v = self._insight_rows["peak_day"]
        k.setText(i18n.tr("stats_peak_day"))
        if agg.peak_day is not None:
            try:
                pd = date.fromisoformat(agg.peak_day.day)
                v.setText(f"{_short_date(pd)} · {format_int(agg.peak_day.characters)} {'симв.' if ru else 'ch'}")
            except ValueError:
                v.setText("—")
        else:
            v.setText("—")

        k, v = self._insight_rows["avg_dict"]
        k.setText(i18n.tr("stats_avg_dictation"))
        if agg.dictations > 0:
            v.setText(f"{format_int(agg.avg_chars_per_dict)} {'симв.' if ru else 'ch'} · {readable_duration(agg.avg_secs_per_dict)}")
        else:
            v.setText("—")

        # Device split bar (when synced with other devices)
        local_chars = sum(d.characters for d in (self._usage.local_days() if hasattr(self._usage, "local_days") else []))
        remote_chars = self._usage.remote_totals().characters if hasattr(self._usage, "remote_totals") else 0
        total_chars = local_chars + remote_chars
        if synced_multi and total_chars > 0:
            share = local_chars / total_chars
            local_pct = round(share * 100)
            remote_pct = max(0, 100 - local_pct)
            self._split_bar.set_fraction(share)
            self._split_caption.setText(
                f"{i18n.tr('stats_this_pc')}: {local_pct}%  ·  "
                f"{i18n.tr('stats_other_devices', count=remote_devs)}: {remote_pct}%"
            )
            self._split_widget.setVisible(True)
        else:
            self._split_widget.setVisible(False)


def compact(value: int) -> str:
    """1000 and up as '1К' / '1,5К' / '125К' / '2,4М' (kept for chart labels and tests)."""
    if value < COMPACT_FROM:
        return str(value)
    for limit, key in ((1_000_000_000, "stats_short_billion"),
                       (1_000_000, "stats_short_million"),
                       (COMPACT_FROM, "stats_short_thousand")):
        if value < limit:
            continue
        scaled = value / limit
        if scaled < 10:
            number = f"{math.floor(scaled * 10) / 10:.1f}".removesuffix(".0")
        else:
            number = str(math.floor(scaled))
        if i18n.language() == "ru":
            number = number.replace(".", ",")
        return number + i18n.tr(key)
    return str(value)


def _format_duration(seconds: float) -> tuple[str, str]:
    """Legacy clock helper retained for compatibility with existing unit tests."""
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}", i18n.tr("stats_unit_hours")
    return f"{minutes}:{secs:02d}", i18n.tr("stats_unit_minutes")
