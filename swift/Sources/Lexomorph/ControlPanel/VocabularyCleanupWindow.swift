// Lexomorph — interactive "Clean Up Vocabulary" ("Очистить словарь") window.
// Presents definite hygiene deletions/fixes (pre-checked) and borderline
// suspicious entries (unchecked by default) with per-row checkboxes, and
// applies the selected plan atomically through VocabularyStore.applyCleanup.

import AppKit
import Foundation

@MainActor
final class VocabularyCleanupWindowController: NSObject, NSWindowDelegate {
    private let store: VocabularyStore
    private let onApplied: () -> Void

    private var window: NSWindow?
    private var audit: VocabularyHygiene.ExtendedAudit?
    private var selectedIndices: Set<Int> = []
    private var checkboxes: [Int: NSButton] = [:]
    private weak var summaryLabel: NSTextField?
    private weak var applyButton: NSButton?

    init(store: VocabularyStore, onApplied: @escaping () -> Void) {
        self.store = store
        self.onApplied = onApplied
        super.init()
    }

    private func t(_ russian: String, _ english: String) -> String {
        localizedText(russian, english, language: Settings.shared.interfaceLanguage)
    }

    func present(relativeTo parentWindow: NSWindow? = nil) {
        let records = store.all()
        let computed = VocabularyHygiene.extendedAudit(for: records)

        if computed.isEmpty {
            let alert = NSAlert()
            alert.alertStyle = .informational
            alert.messageText = t("Словарь в порядке", "The vocabulary is clean")
            alert.informativeText = t(
                "Проверено записей: \(computed.totalScanned). Мусорных, ошибочных или подозрительных сохранений не найдено.",
                "Scanned \(computed.totalScanned) entries. No junk, broken, or suspicious items were found."
            )
            alert.addButton(withTitle: t("ОК", "OK"))
            alert.runModal()
            return
        }

        self.audit = computed
        // Pre-select definite hygiene deletions/fixes; leave borderline review items unchecked.
        self.selectedIndices = Set(computed.items.enumerated().compactMap { index, item in
            item.severity == .definite ? index : nil
        })

        window?.orderOut(nil)
        let panel = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 500),
            styleMask: [.titled, .closable, .resizable],
            backing: .buffered,
            defer: false
        )
        panel.title = t("Очистить словарь", "Clean Up Vocabulary")
        panel.minSize = NSSize(width: 540, height: 380)
        panel.isReleasedWhenClosed = false
        panel.delegate = self
        panel.contentView = buildContentView(audit: computed)

        if let parentFrame = parentWindow?.frame {
            let x = parentFrame.midX - panel.frame.width / 2
            let y = parentFrame.midY - panel.frame.height / 2
            panel.setFrameOrigin(NSPoint(x: x, y: y))
        } else {
            panel.center()
        }
        self.window = panel
        updateFooterState()
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        window = nil
        checkboxes.removeAll()
        audit = nil
        selectedIndices.removeAll()
    }

    // MARK: - View Construction

    private func buildContentView(audit: VocabularyHygiene.ExtendedAudit) -> NSView {
        checkboxes.removeAll()

        let bg = NSVisualEffectView()
        bg.material = .underWindowBackground
        bg.blendingMode = .behindWindow
        bg.state = .active

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 12
        root.edgeInsets = NSEdgeInsets(top: 16, left: 18, bottom: 16, right: 18)
        root.translatesAutoresizingMaskIntoConstraints = false

        // Header
        let title = makeLabel(t("Очистка словаря", "Vocabulary Cleanup"), size: 17, weight: .semibold)
        let subtitle = makeLabel(
            t("Проверено записей: \(audit.totalScanned). Отметьте лишние или ошибочные сохранения — удаления также синхронизируются с аккаунтом.",
              "Scanned \(audit.totalScanned) entries. Select junk or accidental entries to clean up — deletions sync with your account too."),
            size: 12,
            color: .secondaryLabelColor
        )
        subtitle.preferredMaxLayoutWidth = 570
        root.addArrangedSubview(title)
        root.addArrangedSubview(subtitle)

        // Scrollable checklist
        let listStack = NSStackView()
        listStack.orientation = .vertical
        listStack.alignment = .leading
        listStack.spacing = 12
        listStack.translatesAutoresizingMaskIntoConstraints = false

        let definiteDeletes = audit.items.enumerated().filter {
            $0.element.severity == .definite && $0.element.action == .delete
        }
        let definiteFixes = audit.items.enumerated().filter {
            if case .rewrite = $0.element.action { return $0.element.severity == .definite }
            return false
        }
        let reviewItems = audit.items.enumerated().filter {
            $0.element.severity == .review
        }

        if !definiteDeletes.isEmpty {
            listStack.addArrangedSubview(makeGroupCard(
                title: t("Удалить — мусор и ошибки (\(definiteDeletes.count))",
                         "Delete — junk & errors (\(definiteDeletes.count))"),
                symbol: "trash.fill",
                color: .systemRed,
                entries: definiteDeletes
            ))
        }
        if !definiteFixes.isEmpty {
            listStack.addArrangedSubview(makeGroupCard(
                title: t("Исправить — пунктуация, цепочки, регистр (\(definiteFixes.count))",
                         "Fix — punctuation, chains, casing (\(definiteFixes.count))"),
                symbol: "wand.and.stars",
                color: .systemOrange,
                entries: definiteFixes
            ))
        }
        if !reviewItems.isEmpty {
            listStack.addArrangedSubview(makeGroupCard(
                title: t("На проверку — подозрительные и короткие (\(reviewItems.count))",
                         "For review — suspicious or risky short entries (\(reviewItems.count))"),
                symbol: "questionmark.circle.fill",
                color: .systemBlue,
                entries: reviewItems
            ))
        }

        for card in listStack.arrangedSubviews {
            card.widthAnchor.constraint(equalTo: listStack.widthAnchor).isActive = true
        }

        let doc = FlippedView()
        doc.translatesAutoresizingMaskIntoConstraints = false
        doc.addSubview(listStack)
        NSLayoutConstraint.activate([
            listStack.leadingAnchor.constraint(equalTo: doc.leadingAnchor, constant: 2),
            listStack.trailingAnchor.constraint(equalTo: doc.trailingAnchor, constant: -10),
            listStack.topAnchor.constraint(equalTo: doc.topAnchor, constant: 2),
            listStack.bottomAnchor.constraint(equalTo: doc.bottomAnchor, constant: -4),
        ])

        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.drawsBackground = false
        scroll.borderType = .noBorder
        scroll.documentView = doc
        scroll.translatesAutoresizingMaskIntoConstraints = false
        doc.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor).isActive = true
        root.addArrangedSubview(scroll)

        // Selection helpers row
        let selectRow = NSStackView()
        selectRow.orientation = .horizontal
        selectRow.alignment = .centerY
        selectRow.spacing = 8

        let selectDefinite = makeButton(t("Только очевидные", "Definite Only"), action: #selector(selectDefiniteClicked))
        selectDefinite.controlSize = .small
        let selectAll = makeButton(t("Выбрать все", "Select All"), action: #selector(selectAllClicked))
        selectAll.controlSize = .small
        let clearAll = makeButton(t("Снять выбор", "Select None"), action: #selector(selectNoneClicked))
        clearAll.controlSize = .small

        selectRow.addArrangedSubview(selectDefinite)
        selectRow.addArrangedSubview(selectAll)
        selectRow.addArrangedSubview(clearAll)
        selectRow.addArrangedSubview(NSView())
        root.addArrangedSubview(selectRow)

        let divider = NSBox()
        divider.boxType = .separator
        root.addArrangedSubview(divider)

        // Footer buttons
        let footer = NSStackView()
        footer.orientation = .horizontal
        footer.alignment = .centerY
        footer.spacing = 10

        let summary = makeLabel("", size: 12, weight: .medium, color: .secondaryLabelColor)
        self.summaryLabel = summary
        let cancelBtn = makeButton(t("Отмена", "Cancel"), action: #selector(cancelClicked))
        let applyBtn = makeButton(t("Очистить выбранное", "Apply Cleanup"), action: #selector(applyClicked))
        applyBtn.keyEquivalent = "\r"
        self.applyButton = applyBtn

        footer.addArrangedSubview(summary)
        footer.addArrangedSubview(NSView())
        footer.addArrangedSubview(cancelBtn)
        footer.addArrangedSubview(applyBtn)
        root.addArrangedSubview(footer)

        for view in root.arrangedSubviews {
            view.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -36).isActive = true
        }
        scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 200).isActive = true

        bg.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: bg.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: bg.trailingAnchor),
            root.topAnchor.constraint(equalTo: bg.topAnchor),
            root.bottomAnchor.constraint(equalTo: bg.bottomAnchor),
        ])
        return bg
    }

    private func makeGroupCard(title: String,
                               symbol: String,
                               color: NSColor,
                               entries: [(offset: Int, element: VocabularyHygiene.AuditItem)]) -> NSView {
        let card = NSView()
        card.wantsLayer = true
        card.layer?.cornerRadius = 9
        card.layer?.backgroundColor = NSColor.controlBackgroundColor.withAlphaComponent(0.75).cgColor
        card.layer?.borderColor = NSColor.separatorColor.withAlphaComponent(0.38).cgColor
        card.layer?.borderWidth = 1

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 7
        stack.translatesAutoresizingMaskIntoConstraints = false

        let header = NSStackView()
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 6
        if let img = NSImage(systemSymbolName: symbol, accessibilityDescription: nil) {
            let icon = NSImageView(image: img)
            icon.contentTintColor = color
            icon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 12.5, weight: .semibold)
            header.addArrangedSubview(icon)
        }
        header.addArrangedSubview(makeLabel(title, size: 12, weight: .semibold, color: color))
        stack.addArrangedSubview(header)

        for (index, item) in entries {
            let row = NSStackView()
            row.orientation = .horizontal
            row.alignment = .top
            row.spacing = 8

            let box = NSButton(checkboxWithTitle: "", target: self, action: #selector(itemCheckboxToggled(_:)))
            box.tag = index
            box.state = selectedIndices.contains(index) ? .on : .off
            box.setContentHuggingPriority(.required, for: .horizontal)
            checkboxes[index] = box

            let text = NSStackView()
            text.orientation = .vertical
            text.alignment = .leading
            text.spacing = 1

            let headline: String
            switch item.action {
            case .delete:
                headline = "«\(item.record.source)» → «\(item.record.replacement)»"
            case .rewrite(let newSource, let newReplacement):
                headline = "«\(item.record.source)» → «\(item.record.replacement)»  ⇒  «\(newSource)» → «\(newReplacement)»"
            }
            let originTag = item.record.origin == .manual ? t("вручную", "manual") : t("выучено", "learned")
            let primary = makeLabel(headline, size: 12.5, weight: .medium)
            primary.preferredMaxLayoutWidth = 500
            let secondary = makeLabel("\(reasonDescription(item.reason)) · \(originTag)",
                                      size: 11, color: .secondaryLabelColor)
            secondary.preferredMaxLayoutWidth = 500
            text.addArrangedSubview(primary)
            text.addArrangedSubview(secondary)

            row.addArrangedSubview(box)
            row.addArrangedSubview(text)
            row.addArrangedSubview(NSView())
            stack.addArrangedSubview(row)
            row.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }

        card.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: 13),
            stack.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -13),
            stack.topAnchor.constraint(equalTo: card.topAnchor, constant: 10),
            stack.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -10),
        ])
        return card
    }

    private func reasonDescription(_ reason: VocabularyHygiene.AuditReason) -> String {
        switch reason {
        case .rejected(let r):
            switch r {
            case .punctuation: return t("правка только пунктуации или регистра", "punctuation or case only")
            case .noLetters: return t("пустая замена или нет букв", "empty or no letters")
            case .inflection: return t("смена словоформы (окончание/падеж)", "word-form inflection")
            case .rewrite: return t("переписан текст, а не термин", "text rewrite, not a term")
            }
        case .duplicate(let kept):
            return t("дубликат (остаётся «\(kept)»)", "duplicate (keeps «\(kept)»)")
        case .rewriteKinds(let kinds):
            return kinds.map {
                switch $0 {
                case .trimmed: return t("убрать пунктуацию по краям", "trim edge punctuation")
                case .chain: return t("схлопнуть цепочку", "collapse chain")
                case .caseUnified: return t("единый регистр", "unify casing")
                }
            }.joined(separator: ", ")
        case .identityMapping:
            return t("оригинал и замена совпадают", "source and replacement are identical")
        case .manualEdgePunctuation:
            return t("лишняя пунктуация по краям в ручной записи", "extra edge punctuation in manual entry")
        case .inverseConflict(let other):
            return t("конфликт: есть обратная запись «\(other)»", "conflict: inverse rule «\(other)» exists")
        case .longPhrase(let words):
            return t("длинная фраза (\(words) сл.) — похоже на разовую правку", "long phrase (\(words) words) — likely a one-off edit")
        case .shortSourceRisk:
            return t("короткое русское слово — риск ложных срабатываний в речи", "short Russian word — risk of accidental replacements")
        case .lowSimilarity(let percent):
            return t("низкое сходство (\(percent)%) — возможно, случайное или разовое сохранение",
                     "low similarity (\(percent)%) — possible accidental or one-off entry")
        }
    }

    private func updateFooterState() {
        guard let audit else { return }
        var deletes = 0
        var fixes = 0
        for index in selectedIndices where audit.items.indices.contains(index) {
            switch audit.items[index].action {
            case .delete: deletes += 1
            case .rewrite: fixes += 1
            }
        }
        if deletes == 0 && fixes == 0 {
            summaryLabel?.stringValue = t("Ничего не выбрано", "Nothing selected")
            applyButton?.isEnabled = false
        } else {
            summaryLabel?.stringValue = t(
                "Выбрано: удалить \(deletes), исправить \(fixes)",
                "Selected: delete \(deletes), fix \(fixes)"
            )
            applyButton?.isEnabled = true
        }
    }

    // MARK: - Actions

    @objc private func itemCheckboxToggled(_ sender: NSButton) {
        if sender.state == .on {
            selectedIndices.insert(sender.tag)
        } else {
            selectedIndices.remove(sender.tag)
        }
        updateFooterState()
    }

    @objc private func selectDefiniteClicked() {
        guard let audit else { return }
        selectedIndices = Set(audit.items.enumerated().compactMap { $0.element.severity == .definite ? $0.offset : nil })
        syncCheckboxes()
    }

    @objc private func selectAllClicked() {
        guard let audit else { return }
        selectedIndices = Set(audit.items.indices)
        syncCheckboxes()
    }

    @objc private func selectNoneClicked() {
        selectedIndices.removeAll()
        syncCheckboxes()
    }

    private func syncCheckboxes() {
        for (index, box) in checkboxes {
            box.state = selectedIndices.contains(index) ? .on : .off
        }
        updateFooterState()
    }

    @objc private func cancelClicked() {
        window?.close()
    }

    @objc private func applyClicked() {
        guard let audit else { return }
        let chosen = selectedIndices.sorted().compactMap { audit.items.indices.contains($0) ? audit.items[$0] : nil }
        guard !chosen.isEmpty else { return }

        let plan = VocabularyHygiene.cleanupPlan(from: chosen)
        do {
            try store.applyCleanup(plan)
            log("vocabulary: interactive cleanup applied — \(plan.deletions.count) deleted, \(plan.rewrites.count) rewritten")
            window?.close()
            onApplied()
        } catch {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = t("Не удалось почистить словарь", "Could not clean up vocabulary")
            alert.informativeText = error.localizedDescription
            alert.runModal()
        }
    }

    private func makeLabel(_ text: String, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor = .labelColor) -> NSTextField {
        let label = NSTextField(labelWithString: text)
        label.font = .systemFont(ofSize: size, weight: weight)
        label.textColor = color
        label.lineBreakMode = .byWordWrapping
        label.maximumNumberOfLines = 0
        return label
    }

    private func makeButton(_ title: String, action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        button.setContentHuggingPriority(.required, for: .horizontal)
        return button
    }
}
