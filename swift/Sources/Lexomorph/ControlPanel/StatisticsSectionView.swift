// Lexomorph — dedicated Statistics ("Статистика") section.
//
// Features:
//  - Period selector (Сегодня / 7 дней / 30 дней / Всё время) keeping all 4 KPI
//    cards strictly scoped to the selected timeframe with unambiguous units.
//  - Dense, labeled 14-day bar chart with Characters / Dictations toggle,
//    horizontal gridlines, value callouts, and rich tooltips.
//  - Side-by-side bottom card: compact 15-week Activity Heatmap on the left +
//    structured Summary & Insights panel (streaks, peak day, averages, device
//    split, ASR speed) filling the freed horizontal space on the right.

import AppKit
import Foundation

// MARK: - Formatting & Computation Helpers

private let estimatedTypingCharsPerMinute: Double = 200.0
private let averageCharsPerWord: Double = 6.5

private func parseDayKey(_ key: String, calendar: Calendar) -> Date? {
    let parts = key.split(separator: "-")
    guard parts.count == 3,
          let year = Int(parts[0]),
          let month = Int(parts[1]),
          let day = Int(parts[2]) else { return nil }
    return calendar.date(from: DateComponents(year: year, month: month, day: day))
}

private func shortDayMonth(_ date: Date, language: InterfaceLanguage) -> String {
    let formatter = DateFormatter()
    formatter.locale = usageLocale(language)
    formatter.dateFormat = "d MMM"
    return formatter.string(from: date).replacingOccurrences(of: ".", with: "")
}

private func compactChartNumber(_ value: Int, language: InterfaceLanguage) -> String {
    guard value >= 1_000 else { return String(max(0, value)) }
    if value >= 1_000_000 {
        let scaled = Double(value) / 1_000_000.0
        let str = String(format: scaled < 10 ? "%.1f" : "%.0f", scaled)
        let cleaned = str.hasSuffix(".0") ? String(str.dropLast(2)) : str
        return (language == .russian ? cleaned.replacingOccurrences(of: ".", with: ",") + "М" : cleaned + "M")
    }
    let scaled = Double(value) / 1_000.0
    let str = String(format: scaled < 10 ? "%.1f" : "%.0f", scaled)
    let cleaned = str.hasSuffix(".0") ? String(str.dropLast(2)) : str
    return (language == .russian ? cleaned.replacingOccurrences(of: ".", with: ",") + "К" : cleaned + "K")
}

private func readableBigInteger(_ value: Int, language: InterfaceLanguage) -> String {
    guard value >= 1_000_000 else {
        return formattedUsageInteger(value, language: language)
    }
    let scaled = Double(value) / 1_000_000.0
    let formatted = String(format: scaled < 10 ? "%.2f" : "%.1f", scaled)
    let normalized = language == .russian ? formatted.replacingOccurrences(of: ".", with: ",") : formatted
    return "\(normalized) \(localizedText("млн", "M", language: language))"
}

private func readableApproxWords(characters: Int, language: InterfaceLanguage) -> String {
    let words = max(0, Int((Double(characters) / averageCharsPerWord).rounded()))
    guard words > 0 else {
        return localizedText("0 слов", "0 words", language: language)
    }
    if words >= 10_000 {
        let k = Int((Double(words) / 1_000.0).rounded())
        return localizedText("≈ \(formattedUsageInteger(k, language: language)) тыс. слов",
                             "≈ \(formattedUsageInteger(k, language: language))k words",
                             language: language)
    }
    return localizedText("≈ \(formattedUsageInteger(words, language: language)) слов",
                         "≈ \(formattedUsageInteger(words, language: language)) words",
                         language: language)
}

private func readableDurationShort(_ seconds: Double, language: InterfaceLanguage) -> String {
    let total = max(0, Int(seconds.rounded()))
    let h = localizedText("ч", "h", language: language)
    let m = localizedText("мин", "min", language: language)
    let s = localizedText("сек", "sec", language: language)
    if total >= 3_600 {
        let hours = total / 3_600
        let minutes = (total % 3_600) / 60
        return minutes > 0 ? "\(hours) \(h) \(minutes) \(m)" : "\(hours) \(h)"
    }
    if total >= 60 {
        let minutes = total / 60
        let secs = total % 60
        if minutes >= 10 || secs == 0 {
            return "\(minutes) \(m)"
        }
        return "\(minutes) \(m) \(secs) \(s)"
    }
    return "\(total) \(s)"
}

private func blendedColor(_ base: NSColor, toward accent: NSColor, ratio: CGFloat) -> NSColor {
    let a = base.usingColorSpace(.sRGB) ?? base
    let b = accent.usingColorSpace(.sRGB) ?? accent
    let t = max(0, min(1, ratio))
    return NSColor(
        srgbRed: a.redComponent + (b.redComponent - a.redComponent) * t,
        green: a.greenComponent + (b.greenComponent - a.greenComponent) * t,
        blue: a.blueComponent + (b.blueComponent - a.blueComponent) * t,
        alpha: a.alphaComponent + (b.alphaComponent - a.alphaComponent) * t
    )
}

private func statsMonthAbbreviation(_ month: Int, language: InterfaceLanguage) -> String {
    let ru = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
    let en = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    guard (1...12).contains(month) else { return "" }
    return language == .russian ? ru[month - 1] : en[month - 1]
}

private struct PeriodAggregate {
    let dictations: Int
    let characters: Int
    let audioSeconds: Double
    let activeDays: Int
    let totalDaysInSpan: Int
    let startDate: Date
    let endDate: Date
    let peakDay: DailyDictationUsage?

    var averageDictationsPerActiveDay: Double {
        activeDays > 0 ? Double(dictations) / Double(activeDays) : 0
    }

    var averageCharsPerDictation: Int {
        dictations > 0 ? Int((Double(characters) / Double(dictations)).rounded()) : 0
    }

    var averageSecondsPerDictation: Double {
        dictations > 0 ? audioSeconds / Double(dictations) : 0
    }

    var charsPerMinute: Int {
        guard audioSeconds >= 1 else { return 0 }
        return Int((Double(characters) / (audioSeconds / 60.0)).rounded())
    }

    var typingSpeedMultiplier: Double {
        guard charsPerMinute > 0 else { return 0 }
        return Double(charsPerMinute) / estimatedTypingCharsPerMinute
    }

    var estimatedSavedSeconds: Double {
        let manualTypingSeconds = (Double(characters) / estimatedTypingCharsPerMinute) * 60.0
        return max(0, manualTypingSeconds - audioSeconds)
    }
}

private func computePeriodAggregate(period: StatisticsPeriod,
                                    allDays: [DailyDictationUsage],
                                    byDay: [String: DailyDictationUsage],
                                    today: Date,
                                    calendar: Calendar) -> PeriodAggregate {
    let startDate: Date
    let totalSpanDays: Int
    let matchingDays: [DailyDictationUsage]

    switch period {
    case .today:
        startDate = today
        totalSpanDays = 1
        let key = dictationUsageDayKey(for: today, calendar: calendar)
        matchingDays = byDay[key].map { [$0] } ?? []
    case .last7Days:
        startDate = calendar.date(byAdding: .day, value: -6, to: today) ?? today
        totalSpanDays = 7
        matchingDays = (0..<7).compactMap { offset -> DailyDictationUsage? in
            guard let d = calendar.date(byAdding: .day, value: -offset, to: today) else { return nil }
            return byDay[dictationUsageDayKey(for: d, calendar: calendar)]
        }
    case .last30Days:
        startDate = calendar.date(byAdding: .day, value: -29, to: today) ?? today
        totalSpanDays = 30
        matchingDays = (0..<30).compactMap { offset -> DailyDictationUsage? in
            guard let d = calendar.date(byAdding: .day, value: -offset, to: today) else { return nil }
            return byDay[dictationUsageDayKey(for: d, calendar: calendar)]
        }
    case .allTime:
        let nonEmpty = allDays.filter { $0.dictationCount > 0 || $0.characterCount > 0 }
        if let firstKey = nonEmpty.map(\.day).min(),
           let parsed = parseDayKey(firstKey, calendar: calendar) {
            startDate = min(parsed, today)
            let diff = calendar.dateComponents([.day], from: startDate, to: today).day ?? 0
            totalSpanDays = max(1, diff + 1)
        } else {
            startDate = today
            totalSpanDays = 1
        }
        matchingDays = nonEmpty
    }

    var dictations = 0
    var characters = 0
    var audio = 0.0
    var activeDays = 0
    var peakDay: DailyDictationUsage?

    for row in matchingDays where row.dictationCount > 0 || row.characterCount > 0 {
        dictations += row.dictationCount
        characters += row.characterCount
        audio += row.audioSeconds
        activeDays += 1
        if let currentPeak = peakDay {
            if row.characterCount > currentPeak.characterCount
                || (row.characterCount == currentPeak.characterCount && row.dictationCount > currentPeak.dictationCount) {
                peakDay = row
            }
        } else {
            peakDay = row
        }
    }

    return PeriodAggregate(
        dictations: dictations,
        characters: characters,
        audioSeconds: audio,
        activeDays: activeDays,
        totalDaysInSpan: totalSpanDays,
        startDate: startDate,
        endDate: today,
        peakDay: peakDay
    )
}

private func computeStreaks(byDay: [String: DailyDictationUsage],
                            today: Date,
                            calendar: Calendar) -> (current: Int, longest: Int) {
    let activeKeys = Set(byDay.values.filter { $0.dictationCount > 0 }.map(\.day))
    guard !activeKeys.isEmpty else { return (0, 0) }

    // Current streak: consecutive days ending today (or yesterday if not dictated yet today).
    var current = 0
    var cursor = today
    if !activeKeys.contains(dictationUsageDayKey(for: cursor, calendar: calendar)),
       let yesterday = calendar.date(byAdding: .day, value: -1, to: today),
       activeKeys.contains(dictationUsageDayKey(for: yesterday, calendar: calendar)) {
        cursor = yesterday
    }
    while activeKeys.contains(dictationUsageDayKey(for: cursor, calendar: calendar)) {
        current += 1
        guard let prev = calendar.date(byAdding: .day, value: -1, to: cursor) else { break }
        cursor = prev
    }

    // Longest streak across all recorded history.
    let sortedDates = activeKeys.compactMap { parseDayKey($0, calendar: calendar) }.sorted()
    var longest = 0
    var run = 0
    var prevDate: Date?
    for date in sortedDates {
        if let prev = prevDate,
           let expectedNext = calendar.date(byAdding: .day, value: 1, to: prev),
           calendar.isDate(date, inSameDayAs: expectedNext) {
            run += 1
        } else {
            run = 1
        }
        longest = max(longest, run)
        prevDate = date
    }

    return (current, longest)
}

// MARK: - 14-day Bar Chart (Dense, Labeled, Gridlined)

private final class StatsBarChartView: NSView {
    private static let barDays = 14
    private struct DayEntry {
        let key: String
        let date: Date
        let dictations: Int
        let characters: Int
        let audioSeconds: Double
    }

    private let entries: [DayEntry]
    private let metric: StatisticsChartMetric
    private let language: InterfaceLanguage
    private var trackingArea: NSTrackingArea?

    override var isFlipped: Bool { true }

    init(byDay: [String: DailyDictationUsage],
         metric: StatisticsChartMetric,
         language: InterfaceLanguage) {
        self.metric = metric
        self.language = language
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date())
        var list: [DayEntry] = []
        for offset in stride(from: Self.barDays - 1, through: 0, by: -1) {
            if let date = calendar.date(byAdding: .day, value: -offset, to: today) {
                let key = dictationUsageDayKey(for: date, calendar: calendar)
                let usage = byDay[key]
                list.append(DayEntry(
                    key: key,
                    date: date,
                    dictations: usage?.dictationCount ?? 0,
                    characters: usage?.characterCount ?? 0,
                    audioSeconds: usage?.audioSeconds ?? 0
                ))
            }
        }
        self.entries = list
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        heightAnchor.constraint(equalToConstant: 124).isActive = true
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { nil }

    private func value(for entry: DayEntry) -> Int {
        switch metric {
        case .characters: return entry.characters
        case .dictations: return entry.dictations
        }
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea { removeTrackingArea(trackingArea) }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingArea = area
    }

    override func mouseMoved(with event: NSEvent) {
        let axisWidth: CGFloat = 34
        let plotWidth = max(1, bounds.width - axisWidth)
        guard !entries.isEmpty else { toolTip = nil; return }
        let point = convert(event.locationInWindow, from: nil)
        guard point.x >= 0, point.x <= plotWidth else { toolTip = nil; return }
        let slot = plotWidth / CGFloat(entries.count)
        let index = Int(floor(point.x / slot))
        guard entries.indices.contains(index) else { toolTip = nil; return }
        let entry = entries[index]
        let formatter = DateFormatter()
        formatter.dateFormat = "dd.MM.yyyy"
        let dictWord = localizedText("дикт.", "dict.", language: language)
        let charWord = localizedText("симв.", "chars", language: language)
        let charsFmt = formattedUsageInteger(entry.characters, language: language)
        if entry.dictations > 0 {
            let dur = readableDurationShort(entry.audioSeconds, language: language)
            toolTip = "\(formatter.string(from: entry.date)): \(entry.dictations) \(dictWord) · \(charsFmt) \(charWord) · \(dur)"
        } else {
            toolTip = "\(formatter.string(from: entry.date)): \(localizedText("нет диктовок", "no dictations", language: language))"
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        guard !entries.isEmpty, bounds.width > 40, bounds.height > 20 else { return }

        let axisWidth: CGFloat = 34
        let plotWidth = bounds.width - axisWidth
        let topPadding: CGFloat = 17
        let bottomLabelHeight: CGFloat = 18
        let usable = max(16, bounds.height - topPadding - bottomLabelHeight)
        let baselineY = topPadding + usable

        let peak = entries.map(value(for:)).max() ?? 0
        let count = entries.count
        let slot = plotWidth / CGFloat(count)
        let barWidth = min(26.0, max(10.0, slot * 0.68))

        let gridColor = NSColor.separatorColor.withAlphaComponent(0.24)
        let emptyColor = NSColor.labelColor.withAlphaComponent(0.075)
        let accentColor = NSColor.controlAccentColor

        let axisAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 9, weight: .regular),
            .foregroundColor: NSColor.tertiaryLabelColor,
        ]
        let dateAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 9.5, weight: .regular),
            .foregroundColor: NSColor.tertiaryLabelColor,
        ]
        let todayDateAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 9.5, weight: .semibold),
            .foregroundColor: NSColor.secondaryLabelColor,
        ]
        let barValueAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 8.5, weight: .medium),
            .foregroundColor: NSColor.secondaryLabelColor,
        ]

        // Horizontal reference lines (0%, 50%, 100%)
        let levels: [(CGFloat, Int)] = peak > 0
            ? [(0.0, 0), (0.5, Int((Double(peak) / 2.0).rounded())), (1.0, peak)]
            : [(0.0, 0)]
        for (fraction, labelVal) in levels {
            let y = round(baselineY - usable * fraction) + 0.5
            let line = NSBezierPath()
            line.move(to: NSPoint(x: 0, y: y))
            line.line(to: NSPoint(x: plotWidth - 2, y: y))
            gridColor.setStroke()
            line.lineWidth = 1
            if fraction > 0 {
                line.setLineDash([2, 3], count: 2, phase: 0)
            }
            line.stroke()

            if fraction > 0 {
                let text = compactChartNumber(labelVal, language: language) as NSString
                let size = text.size(withAttributes: axisAttrs)
                text.draw(at: NSPoint(x: plotWidth + 5, y: y - size.height / 2), withAttributes: axisAttrs)
            }
        }

        // Bars + value labels + X-axis dates
        for (index, entry) in entries.enumerated() {
            let centerX = slot * (CGFloat(index) + 0.5)
            let val = value(for: entry)
            let height: CGFloat
            if val > 0 && peak > 0 {
                height = max(5.0, (CGFloat(val) / CGFloat(peak)) * usable)
            } else {
                height = 3.0
            }

            let rect = NSRect(
                x: centerX - barWidth / 2,
                y: baselineY - height,
                width: barWidth,
                height: height
            )
            let path = NSBezierPath(roundedRect: rect, xRadius: 4, yRadius: 4)
            if val > 0 && peak > 0 {
                let ratio = CGFloat(val) / CGFloat(peak)
                blendedColor(emptyColor, toward: accentColor, ratio: 0.40 + 0.60 * ratio).setFill()
            } else {
                emptyColor.setFill()
            }
            path.fill()

            // Value callout above non-zero bar
            if val > 0 {
                let label = compactChartNumber(val, language: language) as NSString
                let size = label.size(withAttributes: barValueAttrs)
                if size.width <= slot + 4 {
                    label.draw(
                        at: NSPoint(x: centerX - size.width / 2, y: max(0, rect.minY - size.height - 2)),
                        withAttributes: barValueAttrs
                    )
                }
            }

            // Date label every 2 days + always show today
            let isToday = index == count - 1
            if isToday || (index % 2 == 1 && index < count - 1) {
                let comps = entry.key.split(separator: "-")
                if comps.count == 3 {
                    let text = "\(comps[2]).\(comps[1])" as NSString
                    let attrs = isToday ? todayDateAttrs : dateAttrs
                    let size = text.size(withAttributes: attrs)
                    text.draw(
                        at: NSPoint(x: centerX - size.width / 2, y: baselineY + 4),
                        withAttributes: attrs
                    )
                }
            }
        }
    }
}

// MARK: - Compact 15-Week Activity Heatmap (Left Column)

private final class StatsActivityGridView: NSView {
    static let weeks = 15
    private static let cell: CGFloat = 13
    private static let gap: CGFloat = 3
    private static let monthRow: CGFloat = 16
    private static let weekdayCol: CGFloat = 22

    static var fixedWidth: CGFloat {
        weekdayCol + CGFloat(weeks) * (cell + gap) - gap
    }

    static var fixedHeight: CGFloat {
        monthRow + CGFloat(7) * (cell + gap) - gap
    }

    private let byDay: [String: DailyDictationUsage]
    private let language: InterfaceLanguage
    private let gridStart: Date
    private let today: Date
    private var trackingArea: NSTrackingArea?

    override var isFlipped: Bool { true }

    init(byDay: [String: DailyDictationUsage], language: InterfaceLanguage) {
        self.byDay = byDay
        self.language = language
        let calendar = Calendar.current
        let todayStart = calendar.startOfDay(for: Date())
        self.today = todayStart

        let rawStart = calendar.date(byAdding: .day, value: -(Self.weeks - 1) * 7, to: todayStart) ?? todayStart
        let weekday = calendar.component(.weekday, from: rawStart) // 1 = Sun, 2 = Mon ... 7 = Sat
        let daysSinceMonday = (weekday + 5) % 7
        self.gridStart = calendar.date(byAdding: .day, value: -daysSinceMonday, to: rawStart) ?? rawStart

        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: Self.fixedWidth),
            heightAnchor.constraint(equalToConstant: Self.fixedHeight),
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { nil }

    var activeDaysInWindow: Int {
        let calendar = Calendar.current
        var count = 0
        for week in 0..<Self.weeks {
            for weekday in 0..<7 {
                guard let day = calendar.date(byAdding: .day, value: week * 7 + weekday, to: gridStart),
                      day <= today else { continue }
                let key = dictationUsageDayKey(for: day, calendar: calendar)
                if (byDay[key]?.dictationCount ?? 0) > 0 {
                    count += 1
                }
            }
        }
        return count
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea { removeTrackingArea(trackingArea) }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.mouseMoved, .mouseEnteredAndExited, .activeInKeyWindow, .inVisibleRect],
            owner: self,
            userInfo: nil
        )
        addTrackingArea(area)
        trackingArea = area
    }

    override func mouseMoved(with event: NSEvent) {
        let step = Self.cell + Self.gap
        let point = convert(event.locationInWindow, from: nil)
        let week = Int(floor((point.x - Self.weekdayCol) / step))
        let weekday = Int(floor((point.y - Self.monthRow) / step))
        guard (0..<Self.weeks).contains(week), (0..<7).contains(weekday) else {
            toolTip = nil
            return
        }
        let calendar = Calendar.current
        guard let day = calendar.date(byAdding: .day, value: week * 7 + weekday, to: gridStart),
              day <= today else {
            toolTip = nil
            return
        }
        let key = dictationUsageDayKey(for: day, calendar: calendar)
        let formatter = DateFormatter()
        formatter.dateFormat = "dd.MM.yyyy"
        if let usage = byDay[key], usage.dictationCount > 0 {
            let dictWord = localizedText("дикт.", "dict.", language: language)
            let charWord = localizedText("симв.", "chars", language: language)
            let charsFmt = formattedUsageInteger(usage.characterCount, language: language)
            let dur = readableDurationShort(usage.audioSeconds, language: language)
            toolTip = "\(formatter.string(from: day)): \(usage.dictationCount) \(dictWord) · \(charsFmt) \(charWord) · \(dur)"
        } else {
            toolTip = "\(formatter.string(from: day)): \(localizedText("нет диктовок", "no dictations", language: language))"
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        let calendar = Calendar.current
        // Use 90th-percentile cap so one extreme outlier day doesn't wash out the whole heatmap.
        let positiveChars = byDay.values.map(\.characterCount).filter { $0 > 0 }.sorted()
        let scalePeak: Int
        if positiveChars.isEmpty {
            scalePeak = 0
        } else {
            let p90Index = min(positiveChars.count - 1, Int(Double(positiveChars.count - 1) * 0.90))
            scalePeak = max(1, positiveChars[p90Index])
        }

        let step = Self.cell + Self.gap
        let emptyColor = NSColor.labelColor.withAlphaComponent(0.08)
        let accentColor = NSColor.controlAccentColor
        let labelAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 9, weight: .regular),
            .foregroundColor: NSColor.tertiaryLabelColor,
        ]

        // Weekday labels on the left (Mon / Wed / Fri)
        let dayLabels: [(Int, String)] = language == .russian
            ? [(0, "Пн"), (2, "Ср"), (4, "Пт")]
            : [(0, "Mo"), (2, "We"), (4, "Fr")]
        for (rowIdx, label) in dayLabels {
            let str = label as NSString
            let size = str.size(withAttributes: labelAttrs)
            let y = Self.monthRow + CGFloat(rowIdx) * step + (Self.cell - size.height) / 2
            str.draw(at: NSPoint(x: 0, y: y), withAttributes: labelAttrs)
        }

        var lastMonth = -1
        var lastLabelWeek = -3

        for week in 0..<Self.weeks {
            for weekday in 0..<7 {
                guard let day = calendar.date(byAdding: .day, value: week * 7 + weekday, to: gridStart),
                      day <= today else { continue }
                let rect = NSRect(
                    x: Self.weekdayCol + CGFloat(week) * step,
                    y: Self.monthRow + CGFloat(weekday) * step,
                    width: Self.cell,
                    height: Self.cell
                )
                let path = NSBezierPath(roundedRect: rect, xRadius: 3, yRadius: 3)
                let key = dictationUsageDayKey(for: day, calendar: calendar)
                let chars = byDay[key]?.characterCount ?? 0
                if chars > 0 && scalePeak > 0 {
                    let ratio = min(1.0, CGFloat(chars) / CGFloat(scalePeak))
                    blendedColor(emptyColor, toward: accentColor, ratio: 0.28 + 0.72 * ratio).setFill()
                } else {
                    emptyColor.setFill()
                }
                path.fill()
            }

            if let weekStart = calendar.date(byAdding: .day, value: week * 7, to: gridStart) {
                let month = calendar.component(.month, from: weekStart)
                if month != lastMonth {
                    lastMonth = month
                    if week - lastLabelWeek >= 3 {
                        let label = statsMonthAbbreviation(month, language: language) as NSString
                        label.draw(
                            at: NSPoint(x: Self.weekdayCol + CGFloat(week) * step, y: 0),
                            withAttributes: labelAttrs
                        )
                        lastLabelWeek = week
                    }
                }
            }
        }
    }
}

// MARK: - Thin Split Progress Bar (Mac vs Synced Devices)

private final class DeviceSplitBarView: NSView {
    private let localFraction: CGFloat

    init(localFraction: Double) {
        self.localFraction = max(0, min(1, CGFloat(localFraction)))
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        heightAnchor.constraint(equalToConstant: 5).isActive = true
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { nil }

    override func draw(_ dirtyRect: NSRect) {
        guard bounds.width > 0 else { return }
        let bg = NSBezierPath(roundedRect: bounds, xRadius: 2.5, yRadius: 2.5)
        NSColor.systemPurple.withAlphaComponent(0.55).setFill()
        bg.fill()

        let localWidth = bounds.width * localFraction
        if localWidth > 0.5 {
            let localRect = NSRect(x: 0, y: 0, width: localWidth, height: bounds.height)
            let localPath = NSBezierPath(roundedRect: localRect, xRadius: 2.5, yRadius: 2.5)
            NSColor.controlAccentColor.setFill()
            localPath.fill()
        }
    }
}

// MARK: - Statistics Section Builder

extension LexomorphControlPanelApp {

    @objc func statisticsPeriodChanged(_ sender: NSSegmentedControl) {
        guard let period = StatisticsPeriod(rawValue: sender.selectedSegment),
              period != selectedStatisticsPeriod else { return }
        selectedStatisticsPeriod = period
        refreshDetailContent(preserveScroll: true)
    }

    @objc func statisticsChartMetricChanged(_ sender: NSSegmentedControl) {
        guard let metric = StatisticsChartMetric(rawValue: sender.selectedSegment),
              metric != selectedStatisticsChartMetric else { return }
        selectedStatisticsChartMetric = metric
        refreshDetailContent(preserveScroll: true)
    }

    func buildStatisticsSection() -> NSView {
        settings.refreshFromDisk()

        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date())
        let todayKey = dictationUsageDayKey(for: today, calendar: calendar)

        let localDays = settings.dailyDictationUsage
        let remoteRows = vocabularySync.isSignedIn ? settings.remoteDailyUsage : []
        let allDays = settings.combinedDailyDictationUsage
        let byDay = Dictionary(uniqueKeysWithValues: allDays.map { ($0.day, $0) })

        let period = selectedStatisticsPeriod
        let agg = computePeriodAggregate(period: period, allDays: allDays, byDay: byDay, today: today, calendar: calendar)
        let allTimeAgg = computePeriodAggregate(period: .allTime, allDays: allDays, byDay: byDay, today: today, calendar: calendar)
        let todayUsage = byDay[todayKey] ?? DailyDictationUsage(day: todayKey)
        let streaks = computeStreaks(byDay: byDay, today: today, calendar: calendar)

        let remoteDeviceCount = Set(remoteRows.map(\.device)).count
        let totalDeviceCount = 1 + remoteDeviceCount

        // Period selector in the header
        let periodControl = NSSegmentedControl(
            labels: [
                t("Сегодня", "Today"),
                t("7 дней", "7 days"),
                t("30 дней", "30 days"),
                t("Всё время", "All time"),
            ],
            trackingMode: .selectOne,
            target: self,
            action: #selector(statisticsPeriodChanged(_:))
        )
        periodControl.selectedSegment = period.rawValue
        periodControl.controlSize = .small
        periodControl.setContentHuggingPriority(.required, for: .horizontal)

        // Exact date span subtitle so every KPI number has unmistakable context
        let spanText: String
        switch period {
        case .today:
            spanText = "\(t("Сегодня", "Today")) · \(shortDayMonth(today, language: language))"
        case .last7Days:
            spanText = "\(t("За 7 дней", "Last 7 days")) · \(shortDayMonth(agg.startDate, language: language)) – \(shortDayMonth(agg.endDate, language: language))"
        case .last30Days:
            spanText = "\(t("За 30 дней", "Last 30 days")) · \(shortDayMonth(agg.startDate, language: language)) – \(shortDayMonth(agg.endDate, language: language))"
        case .allTime:
            if agg.dictations > 0 {
                spanText = "\(t("За всё время", "All time")) · \(shortDayMonth(agg.startDate, language: language)) – \(shortDayMonth(agg.endDate, language: language))"
            } else {
                spanText = t("За всё время · данных пока нет", "All time · no data yet")
            }
        }
        let deviceScopeSuffix: String
        if vocabularySync.isSignedIn && remoteDeviceCount > 0 {
            deviceScopeSuffix = " · \(totalDeviceCount) \(t("устр.", "devices"))"
        } else {
            deviceScopeSuffix = " · \(t("этот Mac", "this Mac"))"
        }

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12

        stack.addArrangedSubview(sectionHeader(
            title: t("Статистика", "Statistics"),
            subtitle: spanText + deviceScopeSuffix,
            trailing: periodControl
        ))

        // 1. Four strictly period-consistent KPI tiles
        let tilesRow = NSStackView()
        tilesRow.orientation = .horizontal
        tilesRow.alignment = .top
        tilesRow.distribution = .fillEqually
        tilesRow.spacing = 10

        let dictationsSub: String
        if agg.dictations == 0 {
            dictationsSub = t("нет записей", "no records")
        } else if period == .today {
            dictationsSub = t("за сегодня", "today")
        } else {
            let avgPerDay = Int(agg.averageDictationsPerActiveDay.rounded())
            dictationsSub = t("~\(formattedUsageInteger(max(1, avgPerDay), language: language)) / активн. день",
                              "~\(formattedUsageInteger(max(1, avgPerDay), language: language)) / active day")
        }

        let charsSub = agg.characters > 0
            ? "\(t("симв.", "chars")) · \(readableApproxWords(characters: agg.characters, language: language))"
            : t("символов", "characters")

        let audioValue = agg.audioSeconds > 0
            ? readableDurationShort(agg.audioSeconds, language: language)
            : t("0 сек", "0 sec")
        let audioSub = agg.dictations > 0
            ? t("~\(readableDurationShort(agg.averageSecondsPerDictation, language: language)) / дикт.",
                "~\(readableDurationShort(agg.averageSecondsPerDictation, language: language)) / dict.")
            : t("время речи", "speech time")

        let savedValue = agg.estimatedSavedSeconds >= 30
            ? "~\(readableDurationShort(agg.estimatedSavedSeconds, language: language))"
            : (agg.characters > 0 ? "< 1 \(t("мин", "min"))" : "—")
        let savedSub: String
        if agg.charsPerMinute > 0 {
            let mult = String(format: "%.1f", agg.typingSpeedMultiplier)
            let multFmt = language == .russian ? mult.replacingOccurrences(of: ".", with: ",") : mult
            savedSub = "\(formattedUsageInteger(agg.charsPerMinute, language: language)) \(t("симв./мин", "ch/min")) · \(multFmt)×"
        } else {
            savedSub = t("vs ~200 симв./мин", "vs ~200 ch/min")
        }

        tilesRow.addArrangedSubview(makeMetricTile(
            symbol: "mic.fill",
            symbolColor: .controlAccentColor,
            caption: t("Диктовки", "Dictations"),
            value: formattedUsageInteger(agg.dictations, language: language),
            unit: dictationsSub,
            toolTip: t("Количество завершённых диктовок за выбранный период.",
                       "Completed dictations in the selected period.")
        ))
        tilesRow.addArrangedSubview(makeMetricTile(
            symbol: "text.alignleft",
            symbolColor: .systemIndigo,
            caption: t("Надиктовано", "Volume"),
            value: readableBigInteger(agg.characters, language: language),
            unit: charsSub,
            toolTip: t("Точно: \(formattedUsageInteger(agg.characters, language: language)) симв. (оценка слов: ~6,5 симв./слово).",
                       "Exact: \(formattedUsageInteger(agg.characters, language: language)) chars (word estimate: ~6.5 chars/word).")
        ))
        tilesRow.addArrangedSubview(makeMetricTile(
            symbol: "waveform",
            symbolColor: .systemTeal,
            caption: t("Наговорено", "Speech time"),
            value: audioValue,
            unit: audioSub,
            toolTip: t("Суммарная длительность записанного голоса за выбранный период.",
                       "Total recorded voice duration in the selected period.")
        ))
        tilesRow.addArrangedSubview(makeMetricTile(
            symbol: "bolt.fill",
            symbolColor: .systemGreen,
            caption: t("Экономия", "Time saved"),
            value: savedValue,
            unit: savedSub,
            toolTip: t("Оценка сэкономленного времени относительно ручного набора ~200 симв./мин (время печати минус время речи).",
                       "Estimated time saved vs typing at ~200 chars/min (typing time minus speech duration).")
        ))
        stack.addArrangedSubview(tilesRow)

        // 2. 14-day Bar Chart card with metric toggle & 14-day totals
        let fourteenAgg = (0..<14).reduce(into: (dicts: 0, chars: 0)) { acc, offset in
            if let d = calendar.date(byAdding: .day, value: -offset, to: today),
               let row = byDay[dictationUsageDayKey(for: d, calendar: calendar)] {
                acc.dicts += row.dictationCount
                acc.chars += row.characterCount
            }
        }

        let chartMetricToggle = NSSegmentedControl(
            labels: [t("Символы", "Chars"), t("Диктовки", "Dictations")],
            trackingMode: .selectOne,
            target: self,
            action: #selector(statisticsChartMetricChanged(_:))
        )
        chartMetricToggle.selectedSegment = selectedStatisticsChartMetric.rawValue
        chartMetricToggle.controlSize = .mini
        chartMetricToggle.setContentHuggingPriority(.required, for: .horizontal)

        let chartAccessory = NSStackView()
        chartAccessory.orientation = .horizontal
        chartAccessory.alignment = .centerY
        chartAccessory.spacing = 10
        let fourteenSummary = panelLabel(
            "\(formattedUsageInteger(fourteenAgg.dicts, language: language)) \(t("дикт.", "dict.")) · \(formattedUsageInteger(fourteenAgg.chars, language: language)) \(t("симв.", "chars"))",
            size: 11,
            color: .tertiaryLabelColor
        )
        fourteenSummary.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        chartAccessory.addArrangedSubview(fourteenSummary)
        chartAccessory.addArrangedSubview(chartMetricToggle)

        let barChart = StatsBarChartView(
            byDay: byDay,
            metric: selectedStatisticsChartMetric,
            language: language
        )
        stack.addArrangedSubview(settingsCard(
            title: t("Последние 14 дней", "Last 14 days"),
            symbol: "chart.bar.fill",
            accessory: chartAccessory,
            rows: [barChart]
        ))

        // 3. Combined Bottom Card: Compact 15-Week Heatmap (LEFT) + Summary & Insights (RIGHT)
        let gridView = StatsActivityGridView(byDay: byDay, language: language)
        let leftColumn = NSStackView()
        leftColumn.orientation = .vertical
        leftColumn.alignment = .leading
        leftColumn.spacing = 8
        leftColumn.addArrangedSubview(gridView)
        leftColumn.addArrangedSubview(buildHeatmapLegendRow(activeDays: gridView.activeDaysInWindow))
        leftColumn.setContentHuggingPriority(.required, for: .horizontal)

        let vDivider = NSView()
        vDivider.wantsLayer = true
        vDivider.layer?.backgroundColor = NSColor.separatorColor.withAlphaComponent(0.32).cgColor
        vDivider.translatesAutoresizingMaskIntoConstraints = false
        vDivider.widthAnchor.constraint(equalToConstant: 1).isActive = true

        let rightColumn = buildStatisticsInsightsColumn(
            period: period,
            agg: agg,
            allTimeAgg: allTimeAgg,
            todayUsage: todayUsage,
            streaks: streaks,
            localDays: localDays,
            remoteRows: remoteRows,
            calendar: calendar
        )

        let bottomSplit = NSStackView()
        bottomSplit.orientation = .horizontal
        bottomSplit.alignment = .top
        bottomSplit.spacing = 14
        bottomSplit.addArrangedSubview(leftColumn)
        bottomSplit.addArrangedSubview(vDivider)
        bottomSplit.addArrangedSubview(rightColumn)
        vDivider.heightAnchor.constraint(equalTo: bottomSplit.heightAnchor).isActive = true

        stack.addArrangedSubview(settingsCard(
            title: t("Активность и сводка", "Activity & Summary"),
            symbol: "calendar",
            rows: [bottomSplit]
        ))

        for child in stack.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        return stack
    }

    private func buildHeatmapLegendRow(activeDays: Int) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 6
        row.translatesAutoresizingMaskIntoConstraints = false
        row.widthAnchor.constraint(equalToConstant: StatsActivityGridView.fixedWidth).isActive = true

        let activeLabel = panelLabel(
            t("\(activeDays) активн. дн. за \(StatsActivityGridView.weeks) нед.",
              "\(activeDays) active days in \(StatsActivityGridView.weeks) wks"),
            size: 10,
            color: .tertiaryLabelColor
        )
        row.addArrangedSubview(activeLabel)
        row.addArrangedSubview(NSView())

        let legend = NSStackView()
        legend.orientation = .horizontal
        legend.alignment = .centerY
        legend.spacing = 3
        legend.addArrangedSubview(panelLabel(t("Меньше", "Less"), size: 9.5, color: .tertiaryLabelColor))
        let emptyColor = NSColor.labelColor.withAlphaComponent(0.08)
        for level in [0.0, 0.30, 0.55, 0.78, 1.0] as [CGFloat] {
            let swatch = NSView()
            swatch.wantsLayer = true
            swatch.layer?.cornerRadius = 2.5
            swatch.layer?.backgroundColor = (level == 0
                ? emptyColor
                : blendedColor(emptyColor, toward: .controlAccentColor, ratio: level)).cgColor
            swatch.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([
                swatch.widthAnchor.constraint(equalToConstant: 9),
                swatch.heightAnchor.constraint(equalToConstant: 9),
            ])
            legend.addArrangedSubview(swatch)
        }
        legend.addArrangedSubview(panelLabel(t("Больше", "More"), size: 9.5, color: .tertiaryLabelColor))
        row.addArrangedSubview(legend)
        return row
    }

    private func buildStatisticsInsightsColumn(period: StatisticsPeriod,
                                               agg: PeriodAggregate,
                                               allTimeAgg: PeriodAggregate,
                                               todayUsage: DailyDictationUsage,
                                               streaks: (current: Int, longest: Int),
                                               localDays: [DailyDictationUsage],
                                               remoteRows: [DeviceDictationUsage],
                                               calendar: Calendar) -> NSView {
        let col = NSStackView()
        col.orientation = .vertical
        col.alignment = .leading
        col.spacing = 7
        col.translatesAutoresizingMaskIntoConstraints = false

        // 1. Contextual anchor row: Today (when viewing multi-day) or All-Time (when viewing Today)
        if period == .today {
            col.addArrangedSubview(insightRow(
                label: t("За всё время", "All time"),
                value: "\(formattedUsageInteger(allTimeAgg.dictations, language: language)) \(t("дикт.", "dict.")) · \(compactChartNumber(allTimeAgg.characters, language: language))"
            ))
        } else {
            col.addArrangedSubview(insightRow(
                label: t("Сегодня", "Today"),
                value: "\(formattedUsageInteger(todayUsage.dictationCount, language: language)) \(t("дикт.", "dict.")) · \(formattedUsageInteger(todayUsage.characterCount, language: language)) \(t("симв.", "ch"))"
            ))
        }

        // 2. Active days in selected period
        let activeDaysValue = period == .today
            ? (agg.activeDays > 0 ? t("Активен", "Active") : t("Нет записей", "Inactive"))
            : t("\(agg.activeDays) из \(agg.totalDaysInSpan)", "\(agg.activeDays) of \(agg.totalDaysInSpan)")
        col.addArrangedSubview(insightRow(
            label: t("Активных дней", "Active days"),
            value: activeDaysValue
        ))

        // 3. Current & longest streak
        let streakValue: String
        if streaks.longest == 0 {
            streakValue = "—"
        } else if streaks.current > 0 {
            streakValue = t("\(streaks.current) дн. (рекорд \(streaks.longest))",
                            "\(streaks.current)d (best \(streaks.longest)d)")
        } else {
            streakValue = t("рекорд \(streaks.longest) дн.", "best \(streaks.longest)d")
        }
        col.addArrangedSubview(insightRow(
            label: t("Серия дней", "Streak"),
            value: streakValue
        ))

        // 4. Peak day in selected period
        let peakValue: String
        if let peak = agg.peakDay,
           let date = parseDayKey(peak.day, calendar: calendar) {
            peakValue = "\(shortDayMonth(date, language: language)) · \(formattedUsageInteger(peak.characterCount, language: language)) \(t("симв.", "ch"))"
        } else {
            peakValue = "—"
        }
        col.addArrangedSubview(insightRow(
            label: t("Рекордный день", "Peak day"),
            value: peakValue
        ))

        // 5. Average dictation length
        let avgDictValue = agg.dictations > 0
            ? "\(formattedUsageInteger(agg.averageCharsPerDictation, language: language)) \(t("симв.", "ch")) · \(readableDurationShort(agg.averageSecondsPerDictation, language: language))"
            : "—"
        col.addArrangedSubview(insightRow(
            label: t("Средн. диктовка", "Avg dictation"),
            value: avgDictValue
        ))

        // 6. Local ASR speed (Mac) when available
        let localAudio = localDays.reduce(0.0) { $0 + $1.audioSeconds }
        let localASR = localDays.reduce(0.0) { $0 + $1.asrSeconds }
        if localASR >= 0.5 && localAudio >= 1.0 {
            let ratio = localAudio / localASR
            let ratioStr = String(format: "%.1f", ratio)
            let formattedRatio = language == .russian ? ratioStr.replacingOccurrences(of: ".", with: ",") : ratioStr
            col.addArrangedSubview(insightRow(
                label: t("Скорость ASR", "ASR speed"),
                value: "\(formattedRatio)× \(t("быстрее речи", "realtime"))"
            ))
        }

        // 7. Device breakdown when account sync has other devices
        let remoteChars = remoteRows.reduce(0) { $0 + $1.characterCount }
        let localChars = localDays.reduce(0) { $0 + $1.characterCount }
        let combinedChars = localChars + remoteChars
        let remoteDeviceCount = Set(remoteRows.map(\.device)).count
        if vocabularySync.isSignedIn && remoteDeviceCount > 0 && combinedChars > 0 {
            let localShare = Double(localChars) / Double(combinedChars)
            let localPct = Int((localShare * 100).rounded())
            let remotePct = max(0, 100 - localPct)

            let divider = cardDivider()
            col.addArrangedSubview(divider)

            let splitBlock = NSStackView()
            splitBlock.orientation = .vertical
            splitBlock.alignment = .leading
            splitBlock.spacing = 4

            let splitBar = DeviceSplitBarView(localFraction: localShare)
            splitBlock.addArrangedSubview(splitBar)

            let caption = NSStackView()
            caption.orientation = .horizontal
            caption.alignment = .centerY
            caption.spacing = 6
            caption.addArrangedSubview(statusDot(color: .controlAccentColor, size: 6))
            caption.addArrangedSubview(panelLabel(
                t("Mac \(localPct)%", "Mac \(localPct)%"),
                size: 10.5,
                color: .secondaryLabelColor
            ))
            caption.addArrangedSubview(NSView())
            caption.addArrangedSubview(statusDot(color: NSColor.systemPurple.withAlphaComponent(0.7), size: 6))
            caption.addArrangedSubview(panelLabel(
                t("Другие (\(remoteDeviceCount)): \(remotePct)%",
                  "Others (\(remoteDeviceCount)): \(remotePct)%"),
                size: 10.5,
                color: .secondaryLabelColor
            ))
            splitBlock.addArrangedSubview(caption)
            splitBar.widthAnchor.constraint(equalTo: splitBlock.widthAnchor).isActive = true
            caption.widthAnchor.constraint(equalTo: splitBlock.widthAnchor).isActive = true

            col.addArrangedSubview(splitBlock)
        }

        for child in col.arrangedSubviews {
            child.widthAnchor.constraint(equalTo: col.widthAnchor).isActive = true
        }
        return col
    }

    private func insightRow(label: String, value: String) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .firstBaseline
        row.spacing = 6

        let left = panelLabel(label, size: 11.5, color: .secondaryLabelColor)
        left.maximumNumberOfLines = 1
        left.lineBreakMode = .byTruncatingTail
        left.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)

        let right = panelLabel(value, size: 11.5, weight: .semibold, color: .labelColor)
        right.font = .monospacedDigitSystemFont(ofSize: 11.5, weight: .semibold)
        right.alignment = .right
        right.maximumNumberOfLines = 1
        right.lineBreakMode = .byTruncatingTail
        right.setContentHuggingPriority(.required, for: .horizontal)
        right.setContentCompressionResistancePriority(.required, for: .horizontal)

        row.addArrangedSubview(left)
        row.addArrangedSubview(NSView())
        row.addArrangedSubview(right)
        return row
    }

    private func makeMetricTile(symbol: String,
                                symbolColor: NSColor,
                                caption: String,
                                value: String,
                                unit: String,
                                toolTip: String) -> NSView {
        let card = compactCard(cornerRadius: 10)
        card.toolTip = toolTip

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 3
        stack.translatesAutoresizingMaskIntoConstraints = false

        let head = NSStackView()
        head.orientation = .horizontal
        head.alignment = .centerY
        head.spacing = 5
        head.addArrangedSubview(panelSymbol(symbol, color: symbolColor, description: nil, pointSize: 11.5))
        let cap = panelLabel(caption, size: 11, weight: .semibold, color: .secondaryLabelColor)
        cap.maximumNumberOfLines = 1
        cap.lineBreakMode = .byTruncatingTail
        head.addArrangedSubview(cap)
        head.addArrangedSubview(NSView())

        let valueLabel = panelLabel(value, size: 19, weight: .bold, color: .labelColor)
        valueLabel.font = .monospacedDigitSystemFont(ofSize: 19, weight: .bold)
        valueLabel.maximumNumberOfLines = 1
        valueLabel.lineBreakMode = .byTruncatingTail

        let unitLabel = panelLabel(unit, size: 10.5, weight: .regular, color: .tertiaryLabelColor)
        unitLabel.maximumNumberOfLines = 1
        unitLabel.lineBreakMode = .byTruncatingTail

        stack.addArrangedSubview(head)
        stack.addArrangedSubview(valueLabel)
        stack.addArrangedSubview(unitLabel)

        pin(stack, inside: card, horizontal: 12, vertical: 10)
        return card
    }
}
