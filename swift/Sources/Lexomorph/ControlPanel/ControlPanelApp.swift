// Lexomorph — unified Control Panel & Settings application controller.
//
// Combines the Control Panel and Settings into a single resizable macOS window
// with a left sidebar, instant live-applied settings (Option A), and a
// contextual footer bar that appears only when staged/restart-required edits
// are pending.

import AppKit
import AVFoundation
import Foundation
import ServiceManagement

@MainActor
final class LexomorphControlPanelApp: NSObject, NSApplicationDelegate, NSWindowDelegate, NSTextFieldDelegate, NSTextViewDelegate {
    private let openSettingsDirectly: Bool
    var window: NSWindow?

    // Permanent layout containers (avoid destructive full-window rebuilds!)
    private var sidebarStack: NSStackView?
    private var sidebarFooterStack: NSStackView?
    private var detailScrollView: NSScrollView?
    private var stagedFooterContainer: NSView?
    private var stagedFooterHeightConstraint: NSLayoutConstraint?

    // Auto-height fitting for the Overview page while preserving manual resize
    private var userManuallyResizedWindow = false
    private var isAutoSizingWindow = false

    lazy var vocabularyManagerWindowController = VocabularyManagerWindowController(store: Settings.shared.vocabularyStore)
    lazy var vocabularyCleanupWindowController = VocabularyCleanupWindowController(store: Settings.shared.vocabularyStore) { [weak self] in
        self?.refreshDetailContent(preserveScroll: true)
    }
    lazy var vocabularySync = VocabularySyncCoordinator(settings: Settings.shared, role: .controlPanel)

    // Sync transient UI state
    var vocabularySyncEmailInput: String?
    var vocabularySyncPasswordInput = ""
    var vocabularySyncBusy = false
    var vocabularySyncMessage: String?
    weak var vocabularySyncStatusLabel: NSTextField?

    // Service & update state
    private var refreshTimer: Timer?
    var serviceOperation: ControlPanelServiceOperation?
    private var updateTask: Task<Void, Never>?
    var updateState: ControlPanelUpdateState = .checking
    private var lastRuntimeFingerprint = ""
    let settings = Settings.shared
    var permissionClickCount: [Permission: Int] = [:]

    // Navigation & disclosure state
    var selectedSection: ControlPanelSection = .overview
    var selectedAISubsection: AISubsection = .correction
    var selectedStatisticsPeriod: StatisticsPeriod = .allTime
    var selectedStatisticsChartMetric: StatisticsChartMetric = .characters
    var fillerListExpanded = false
    var correctionPromptExpanded = false
    var rewritePromptExpanded = false
    var rewritePromptEditorStyleID: String = RewriteStyle.polish.rawValue

    // Staged draft state (only differs from baseline for staged/restart-required settings)
    var settingsDraft: ControlPanelSettingsDraft?
    var settingsDraftBaseline: ControlPanelSettingsDraft?

    private var distributedObservers: [NSObjectProtocol] = []
    var hotkeyRecorder: HotkeyRecorderController?

    // Model download state
    var llmModelDownloadState: LLMModelDownloadState = .idle
    var llmModelDownloadTask: Task<Void, Never>?
    var llmModelDownloadProgress: (received: Int64, total: Int64)?
    weak var llmDownloadStatusLabel: NSTextField?
    weak var llmDownloadProgressBar: NSProgressIndicator?
    var llmModelDownloadModel: BundledLLMModel = .voiceScribe

    var punctuationDownloadTask: Task<Void, Never>?
    var punctuationDownloadModel: PunctuationModel?
    var punctuationDownloadFraction: Double?
    var punctuationDownloadError: String?
    weak var punctuationDownloadStatusLabel: NSTextField?
    weak var punctuationDownloadProgressBar: NSProgressIndicator?

    // Custom rewrite style editor state
    static let customStylePalette: [String] = [
        "#0A84FF", "#34C759", "#FF9F0A", "#FF375F", "#BF5AF2",
        "#00C7BE", "#FFD60A", "#FF453A", "#5E5CE6", "#98989D",
    ]
    var customStyleEditorHotkey: HotkeyChoice?
    var customStyleEditorColor: String = "#0A84FF"
    var customStyleSwatchButtons: [NSButton] = []
    var customStyleEditorWindow: NSWindow?
    var customStyleEditorExisting: CustomRewriteStyle?
    var customStyleEditorNameField: NSTextField?
    var customStyleEditorInstructionView: NSTextView?
    weak var customStyleEditorHotkeyButton: NSButton?

    // Field tags & identifiers
    static let llmCustomBaseURLFieldTag = 9001
    static let llmCustomAPIKeyFieldTag = 9002
    static let llmCustomModelNameFieldTag = 9003
    static let rewriteCustomBaseURLFieldTag = 9004
    static let rewriteCustomAPIKeyFieldTag = 9005
    static let rewriteCustomModelNameFieldTag = 9006
    static let vocabularySyncEmailFieldTag = 9007
    static let vocabularySyncPasswordFieldTag = 9008
    static let correctionSystemPromptEditorID = NSUserInterfaceItemIdentifier("correction-system-prompt-editor")
    static let rewriteSystemPromptEditorID = NSUserInterfaceItemIdentifier("rewrite-system-prompt-editor")

    static let enterDelayOptions: [(title: String, value: String)] = [
        ("0 ms", "0"), ("50 ms", "50"), ("80 ms", "80"),
        ("120 ms", "120"), ("200 ms", "200"), ("300 ms", "300"),
    ]

    var silenceDurationOptions: [(title: String, value: String)] {
        (1...10).map { ("\($0) \(t("сек", "sec"))", String($0)) }
    }

    var language: InterfaceLanguage { settings.interfaceLanguage }

    init(openSettingsDirectly: Bool = false) {
        self.openSettingsDirectly = openSettingsDirectly
        super.init()
    }

    // MARK: - Defaults for Prompt Editors

    func defaultCorrectionSystemPrompt(for model: BundledLLMModel) -> String {
        LLMCorrectionPrompt.systemPrompt(vocabulary: [], model: model)
    }

    func defaultRewriteSystemPrompt(for style: RewriteStyle) -> String {
        LLMRewritePrompt.systemPrompt(style: style)
    }

    func defaultRewriteSystemPrompt(forStyleID id: String, draft: ControlPanelSettingsDraft) -> String {
        if let builtin = RewriteStyle(rawValue: id) {
            return LLMRewritePrompt.systemPrompt(style: builtin)
        }
        if let custom = draft.customRewriteStyles.first(where: { $0.id == id }) {
            return LLMRewritePrompt.systemPrompt(custom: custom)
        }
        return LLMRewritePrompt.systemPrompt(style: .polish)
    }

    // MARK: - NSApplicationDelegate

    func applicationDidFinishLaunching(_ notification: Notification) {
        if !LexomorphControlPanelRegistry.claimCurrentPanel() {
            if LexomorphControlPanelRegistry.activateExistingPanelIfPresent() {
                DistributedNotificationCenter.default().postNotificationName(
                    openSettingsDirectly ? OPEN_SETTINGS_WINDOW_NOTIFICATION : OPEN_CONTROL_PANEL_NOTIFICATION,
                    object: nil,
                    userInfo: nil,
                    deliverImmediately: true
                )
                NSApp.terminate(nil)
                return
            }
            log("controlPanel: claimCurrentPanel failed and no existing panel could be activated; opening anyway")
        }

        NSApp.setActivationPolicy(.regular)
        reloadDraftFromDisk()
        showWindow()
        startRefreshTimer()
        vocabularySync.start()

        let center = DistributedNotificationCenter.default()
        distributedObservers.append(center.addObserver(
            forName: VOCABULARY_SYNC_STATUS_NOTIFICATION, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.vocabularySyncStatusChanged() }
        })
        distributedObservers.append(center.addObserver(
            forName: OPEN_SETTINGS_WINDOW_NOTIFICATION, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.showWindow() }
        })
        distributedObservers.append(center.addObserver(
            forName: OPEN_CONTROL_PANEL_NOTIFICATION, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.showWindow() }
        })
        distributedObservers.append(center.addObserver(
            forName: AGENT_TOGGLED_MODE_NOTIFICATION, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.syncFromExternalChange() }
        })

        checkForUpdates()
        HardwareCapabilities.shared.warmUpAsync { [weak self] _ in
            guard let self else { return }
            if self.selectedSection == .ai || self.selectedSection == .system {
                self.refreshDetailContent(preserveScroll: true)
            }
        }
        if settings.agentEnabled && !LexomorphAgentService.isAgentLoadedOrRunning() {
            beginServiceOperation(.starting)
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        let center = DistributedNotificationCenter.default()
        for observer in distributedObservers {
            center.removeObserver(observer)
        }
        distributedObservers.removeAll()
        hotkeyRecorder?.cancel()
        hotkeyRecorder = nil
        refreshTimer?.invalidate()
        refreshTimer = nil
        updateTask?.cancel()
        updateTask = nil
        LexomorphControlPanelRegistry.clearCurrentPanel()
    }

    func windowWillClose(_ notification: Notification) {
        guard let closingWindow = notification.object as? NSWindow,
              closingWindow === window else { return }
        closeCustomStyleEditor()
        hotkeyRecorder?.cancel()
        hotkeyRecorder = nil
        NSApp.terminate(nil)
    }

    func windowDidEndLiveResize(_ notification: Notification) {
        guard let resizedWindow = notification.object as? NSWindow,
              resizedWindow === window,
              !isAutoSizingWindow else { return }
        userManuallyResizedWindow = true
    }

    // MARK: - Unified Main Window

    private func showWindow() {
        if let window {
            syncFromExternalChange()
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let mainWindow = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 780, height: 600),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        mainWindow.title = mainWindowTitle()
        mainWindow.minSize = NSSize(width: 720, height: 460)
        mainWindow.isReleasedWhenClosed = false
        mainWindow.delegate = self
        mainWindow.contentView = buildRootSplitLayout()
        let restoredFrame = mainWindow.setFrameUsingName("LexomorphUnifiedPanelWindow")
        mainWindow.setFrameAutosaveName("LexomorphUnifiedPanelWindow")
        self.window = mainWindow
        userManuallyResizedWindow = false

        refreshSidebar()
        refreshDetailContent(preserveScroll: false)
        updateStagedFooter()

        // Always fit initial window height cleanly to the Overview page's elements
        // (while keeping saved width/position and allowing manual resize afterwards).
        fitWindowHeightToOverview(animated: false, anchorTop: restoredFrame)
        if !restoredFrame {
            mainWindow.center()
        }

        mainWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Computes the exact height needed by the Overview ("Главная") page at the
    /// window's current width and adjusts the window's content height to match,
    /// clamped safely to the visible screen area. Preserves manual resizing once
    /// the user explicitly drags the window border.
    func fitWindowHeightToOverview(animated: Bool, anchorTop: Bool) {
        guard !userManuallyResizedWindow,
              selectedSection == .overview,
              let mainWindow = window,
              let scrollView = detailScrollView,
              let doc = scrollView.documentView else { return }

        mainWindow.layoutIfNeeded()
        let viewportWidth = max(480, scrollView.contentView.bounds.width)
        if abs(doc.frame.width - viewportWidth) > 0.5 {
            doc.frame.size.width = viewportWidth
        }
        doc.layoutSubtreeIfNeeded()

        let measuredDocHeight = ceil(doc.fittingSize.height)
        guard measuredDocHeight > 100 else { return }

        let stagedHeight = stagedFooterHeightConstraint?.constant ?? 0
        let rawContentHeight = measuredDocHeight + stagedHeight

        let visibleFrame = (mainWindow.screen ?? NSScreen.main)?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let titleBarHeight = mainWindow.frame.height - mainWindow.contentLayoutRect.height
        let minContentHeight = max(420, mainWindow.minSize.height - titleBarHeight)
        let maxContentHeight = max(minContentHeight, floor(visibleFrame.height - titleBarHeight - 36))
        let targetContentHeight = min(max(minContentHeight, rawContentHeight), maxContentHeight)

        let currentContentHeight = mainWindow.contentLayoutRect.height
        guard abs(targetContentHeight - currentContentHeight) > 2 else { return }

        let newFrameHeight = targetContentHeight + titleBarHeight
        var targetFrame = mainWindow.frame
        if anchorTop {
            let oldTop = targetFrame.maxY
            targetFrame.size.height = newFrameHeight
            targetFrame.origin.y = oldTop - newFrameHeight
            if targetFrame.minY < visibleFrame.minY + 12 {
                targetFrame.origin.y = visibleFrame.minY + 12
            }
            if targetFrame.maxY > visibleFrame.maxY {
                targetFrame.origin.y = visibleFrame.maxY - targetFrame.height
            }
        } else {
            targetFrame.size.height = newFrameHeight
        }

        isAutoSizingWindow = true
        mainWindow.setFrame(targetFrame, display: true, animate: animated)
        isAutoSizingWindow = false
    }

    private func mainWindowTitle() -> String {
        "Lexomorph · v\(currentBundleVersion())"
    }

    private func buildRootSplitLayout() -> NSView {
        let container = NSView()

        // Left Sidebar (.sidebar visual effect)
        let sidebarBG = NSVisualEffectView()
        sidebarBG.material = .sidebar
        sidebarBG.blendingMode = .behindWindow
        sidebarBG.state = .active
        sidebarBG.translatesAutoresizingMaskIntoConstraints = false

        let sidebarRoot = NSStackView()
        sidebarRoot.orientation = .vertical
        sidebarRoot.alignment = .leading
        sidebarRoot.spacing = 6
        sidebarRoot.edgeInsets = NSEdgeInsets(top: 14, left: 10, bottom: 12, right: 10)
        sidebarRoot.translatesAutoresizingMaskIntoConstraints = false

        // Brand Header inside Sidebar
        let brandRow = NSStackView()
        brandRow.orientation = .horizontal
        brandRow.alignment = .centerY
        brandRow.spacing = 8
        brandRow.edgeInsets = NSEdgeInsets(top: 2, left: 6, bottom: 8, right: 6)
        if let appIcon = NSImage(named: "Lexomorph") {
            let iconView = NSImageView(image: appIcon)
            iconView.translatesAutoresizingMaskIntoConstraints = false
            NSLayoutConstraint.activate([
                iconView.widthAnchor.constraint(equalToConstant: 26),
                iconView.heightAnchor.constraint(equalToConstant: 26),
            ])
            brandRow.addArrangedSubview(iconView)
        }
        let brandText = NSStackView()
        brandText.orientation = .vertical
        brandText.alignment = .leading
        brandText.spacing = 0
        brandText.addArrangedSubview(panelLabel("Lexomorph", size: 14.5, weight: .semibold))
        brandText.addArrangedSubview(panelLabel("v\(currentBundleVersion())", size: 10.5, color: .tertiaryLabelColor))
        brandRow.addArrangedSubview(brandText)

        let navStack = NSStackView()
        navStack.orientation = .vertical
        navStack.alignment = .leading
        navStack.spacing = 3
        self.sidebarStack = navStack

        let footerStack = NSStackView()
        footerStack.orientation = .vertical
        footerStack.alignment = .leading
        footerStack.spacing = 8
        self.sidebarFooterStack = footerStack

        sidebarRoot.addArrangedSubview(brandRow)
        sidebarRoot.addArrangedSubview(navStack)
        sidebarRoot.addArrangedSubview(NSView())
        sidebarRoot.addArrangedSubview(cardDivider())
        sidebarRoot.addArrangedSubview(footerStack)

        for view in sidebarRoot.arrangedSubviews {
            view.widthAnchor.constraint(equalTo: sidebarRoot.widthAnchor, constant: -20).isActive = true
        }

        sidebarBG.addSubview(sidebarRoot)
        NSLayoutConstraint.activate([
            sidebarRoot.leadingAnchor.constraint(equalTo: sidebarBG.leadingAnchor),
            sidebarRoot.trailingAnchor.constraint(equalTo: sidebarBG.trailingAnchor),
            sidebarRoot.topAnchor.constraint(equalTo: sidebarBG.topAnchor),
            sidebarRoot.bottomAnchor.constraint(equalTo: sidebarBG.bottomAnchor),
        ])

        // Vertical Divider
        let verticalDivider = NSView()
        verticalDivider.wantsLayer = true
        verticalDivider.layer?.backgroundColor = NSColor.separatorColor.withAlphaComponent(0.4).cgColor
        verticalDivider.translatesAutoresizingMaskIntoConstraints = false

        // Right Content Area (.underWindowBackground)
        let detailBG = NSVisualEffectView()
        detailBG.material = .underWindowBackground
        detailBG.blendingMode = .behindWindow
        detailBG.state = .active
        detailBG.translatesAutoresizingMaskIntoConstraints = false

        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.autohidesScrollers = true
        scrollView.drawsBackground = false
        scrollView.borderType = .noBorder
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        self.detailScrollView = scrollView

        let footerBar = NSView()
        footerBar.wantsLayer = true
        footerBar.layer?.backgroundColor = NSColor.windowBackgroundColor.withAlphaComponent(0.92).cgColor
        footerBar.translatesAutoresizingMaskIntoConstraints = false
        self.stagedFooterContainer = footerBar
        let footerHeight = footerBar.heightAnchor.constraint(equalToConstant: 0)
        footerHeight.isActive = true
        self.stagedFooterHeightConstraint = footerHeight

        detailBG.addSubview(scrollView)
        detailBG.addSubview(footerBar)

        NSLayoutConstraint.activate([
            scrollView.leadingAnchor.constraint(equalTo: detailBG.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: detailBG.trailingAnchor),
            scrollView.topAnchor.constraint(equalTo: detailBG.topAnchor),
            scrollView.bottomAnchor.constraint(equalTo: footerBar.topAnchor),

            footerBar.leadingAnchor.constraint(equalTo: detailBG.leadingAnchor),
            footerBar.trailingAnchor.constraint(equalTo: detailBG.trailingAnchor),
            footerBar.bottomAnchor.constraint(equalTo: detailBG.bottomAnchor),
        ])

        container.addSubview(sidebarBG)
        container.addSubview(verticalDivider)
        container.addSubview(detailBG)

        NSLayoutConstraint.activate([
            sidebarBG.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            sidebarBG.topAnchor.constraint(equalTo: container.topAnchor),
            sidebarBG.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            sidebarBG.widthAnchor.constraint(equalToConstant: 206),

            verticalDivider.leadingAnchor.constraint(equalTo: sidebarBG.trailingAnchor),
            verticalDivider.topAnchor.constraint(equalTo: container.topAnchor),
            verticalDivider.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            verticalDivider.widthAnchor.constraint(equalToConstant: 1),

            detailBG.leadingAnchor.constraint(equalTo: verticalDivider.trailingAnchor),
            detailBG.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            detailBG.topAnchor.constraint(equalTo: container.topAnchor),
            detailBG.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        ])

        return container
    }

    // MARK: - Sidebar Rendering (Lightweight, Non-Destructive)

    func refreshSidebar() {
        guard let navStack = sidebarStack, let footerStack = sidebarFooterStack else { return }
        navStack.arrangedSubviews.forEach { $0.removeFromSuperview() }
        footerStack.arrangedSubviews.forEach { $0.removeFromSuperview() }

        let running = LexomorphAgentService.isAgentRunning()
        let state = AgentRuntimeStateStore.read()
        let serviceInfo = servicePresentation(running: running, state: state)
        let missingPerms = Permission.allCases.filter { !Permissions.isGranted($0) }.count
        let hasUpdate: Bool = {
            if case .available = updateState { return true }
            return false
        }()

        for section in ControlPanelSection.allCases {
            let dotColor: NSColor?
            switch section {
            case .overview:
                dotColor = serviceInfo.color
            case .system:
                if hasUpdate { dotColor = .systemBlue }
                else if missingPerms > 0 { dotColor = .systemOrange }
                else { dotColor = nil }
            default:
                dotColor = nil
            }
            let itemView = makeSidebarItemView(section: section,
                                               selected: section == selectedSection,
                                               indicatorColor: dotColor)
            navStack.addArrangedSubview(itemView)
            itemView.widthAnchor.constraint(equalTo: navStack.widthAnchor).isActive = true
        }

        // Pinned sidebar footer: live status pill + RU/EN toggle
        let statusRow = NSStackView()
        statusRow.orientation = .horizontal
        statusRow.alignment = .centerY
        statusRow.spacing = 6
        statusRow.edgeInsets = NSEdgeInsets(top: 2, left: 6, bottom: 0, right: 6)
        statusRow.addArrangedSubview(statusDot(color: serviceInfo.color, size: 7))
        let statusLabel = panelLabel(serviceInfo.status, size: 11, weight: .medium, color: .secondaryLabelColor)
        statusLabel.lineBreakMode = .byTruncatingTail
        statusLabel.maximumNumberOfLines = 1
        statusRow.addArrangedSubview(statusLabel)
        statusRow.addArrangedSubview(NSView())
        footerStack.addArrangedSubview(statusRow)
        statusRow.widthAnchor.constraint(equalTo: footerStack.widthAnchor).isActive = true

        let langRow = NSStackView()
        langRow.orientation = .horizontal
        langRow.alignment = .centerY
        langRow.spacing = 6
        langRow.edgeInsets = NSEdgeInsets(top: 0, left: 6, bottom: 0, right: 6)
        langRow.addArrangedSubview(panelLabel(t("Язык", "Language"), size: 11, color: .tertiaryLabelColor))
        langRow.addArrangedSubview(NSView())
        let languageControl = NSSegmentedControl(labels: ["RU", "EN"],
                                                 trackingMode: .selectOne,
                                                 target: self,
                                                 action: #selector(selectInterfaceLanguage(_:)))
        languageControl.selectedSegment = language == .russian ? 0 : 1
        languageControl.controlSize = .small
        languageControl.setContentHuggingPriority(.required, for: .horizontal)
        langRow.addArrangedSubview(languageControl)
        footerStack.addArrangedSubview(langRow)
        langRow.widthAnchor.constraint(equalTo: footerStack.widthAnchor).isActive = true
    }

    private func makeSidebarItemView(section: ControlPanelSection,
                                     selected: Bool,
                                     indicatorColor: NSColor?) -> NSView {
        let row = NSView()
        row.wantsLayer = true
        row.layer?.cornerRadius = 7
        row.layer?.backgroundColor = selected
            ? NSColor.controlAccentColor.withAlphaComponent(0.16).cgColor
            : NSColor.clear.cgColor
        row.translatesAutoresizingMaskIntoConstraints = false
        row.heightAnchor.constraint(equalToConstant: 30).isActive = true

        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false

        let icon = panelSymbol(section.symbolName,
                               color: selected ? .controlAccentColor : .secondaryLabelColor,
                               description: nil,
                               pointSize: 13)
        icon.widthAnchor.constraint(equalToConstant: 18).isActive = true

        let title = panelLabel(localizedSectionTitle(section),
                               size: 12.5,
                               weight: selected ? .semibold : .regular,
                               color: selected ? .labelColor : .secondaryLabelColor)
        title.maximumNumberOfLines = 1
        title.lineBreakMode = .byTruncatingTail

        stack.addArrangedSubview(icon)
        stack.addArrangedSubview(title)
        stack.addArrangedSubview(NSView())
        if let indicatorColor {
            stack.addArrangedSubview(statusDot(color: indicatorColor, size: 7))
        }

        pin(stack, inside: row, horizontal: 9, vertical: 4)

        // Transparent full-row button overlay for crisp clicking
        let clickButton = NSButton(title: "", target: self, action: #selector(sidebarSectionClicked(_:)))
        clickButton.isBordered = false
        clickButton.tag = section.rawValue
        clickButton.translatesAutoresizingMaskIntoConstraints = false
        clickButton.setAccessibilityLabel(localizedSectionTitle(section))
        row.addSubview(clickButton)
        NSLayoutConstraint.activate([
            clickButton.leadingAnchor.constraint(equalTo: row.leadingAnchor),
            clickButton.trailingAnchor.constraint(equalTo: row.trailingAnchor),
            clickButton.topAnchor.constraint(equalTo: row.topAnchor),
            clickButton.bottomAnchor.constraint(equalTo: row.bottomAnchor),
        ])
        return row
    }

    // MARK: - Detail Rendering (Scroll-Preserving!)

    func refreshDetailContent(preserveScroll: Bool = true) {
        guard let scrollView = detailScrollView else { return }
        let savedScrollY = preserveScroll ? scrollView.contentView.bounds.origin.y : 0
        let draft = settingsDraft ?? ControlPanelSettingsDraft(settings: settings)

        let sectionView: NSView
        switch selectedSection {
        case .overview: sectionView = buildOverviewSection(draft: draft)
        case .statistics: sectionView = buildStatisticsSection()
        case .dictation: sectionView = buildDictationSection(draft: draft)
        case .text: sectionView = buildTextSection(draft: draft)
        case .ai: sectionView = buildAIProcessingSection(draft: draft)
        case .audio: sectionView = buildAudioSection(draft: draft)
        case .appearance: sectionView = buildAppearanceSection(draft: draft)
        case .system: sectionView = buildSystemSection(draft: draft)
        }
        sectionView.translatesAutoresizingMaskIntoConstraints = false

        let doc = FlippedView()
        doc.translatesAutoresizingMaskIntoConstraints = false
        doc.addSubview(sectionView)

        NSLayoutConstraint.activate([
            sectionView.leadingAnchor.constraint(equalTo: doc.leadingAnchor, constant: 22),
            sectionView.trailingAnchor.constraint(equalTo: doc.trailingAnchor, constant: -22),
            sectionView.topAnchor.constraint(equalTo: doc.topAnchor, constant: 18),
            sectionView.bottomAnchor.constraint(equalTo: doc.bottomAnchor, constant: -20),
        ])

        scrollView.documentView = doc
        doc.widthAnchor.constraint(equalTo: scrollView.contentView.widthAnchor).isActive = true

        if selectedSection == .overview && !userManuallyResizedWindow && window?.isVisible == true {
            fitWindowHeightToOverview(animated: true, anchorTop: true)
        }

        if preserveScroll && savedScrollY > 0 {
            doc.layoutSubtreeIfNeeded()
            let maxY = max(0, doc.frame.height - scrollView.contentView.bounds.height)
            scrollView.contentView.scroll(to: NSPoint(x: 0, y: min(savedScrollY, maxY)))
            scrollView.reflectScrolledClipView(scrollView.contentView)
        }
    }

    // MARK: - Contextual Staged-Changes Footer (Option A)

    func updateStagedFooter() {
        guard let footer = stagedFooterContainer,
              let heightConstraint = stagedFooterHeightConstraint else { return }
        footer.subviews.forEach { $0.removeFromSuperview() }

        let draft = settingsDraft ?? ControlPanelSettingsDraft(settings: settings)
        let baseline = settingsDraftBaseline ?? ControlPanelSettingsDraft(settings: settings)
        let hasChanges = draft != baseline
        guard hasChanges else {
            heightConstraint.constant = 0
            footer.isHidden = true
            return
        }

        footer.isHidden = false
        heightConstraint.constant = 52

        let validation = settingsValidationMessage(draft)
        let restartNeeded = settingsRestartRequired(draft)

        let topBorder = cardDivider()
        footer.addSubview(topBorder)

        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10
        row.translatesAutoresizingMaskIntoConstraints = false

        let iconName = validation != nil ? "exclamationmark.triangle.fill"
            : (restartNeeded ? "arrow.clockwise.circle.fill" : "pencil.circle.fill")
        let iconColor: NSColor = validation != nil ? .systemRed
            : (restartNeeded ? .systemOrange : .controlAccentColor)
        row.addArrangedSubview(panelSymbol(iconName, color: iconColor, description: nil, pointSize: 15))

        let msgText = validation ?? (restartNeeded
            ? t("Изменения требуют перезапуска службы", "Changes require restarting the service")
            : t("Есть несохранённые изменения", "You have unsaved changes"))
        let msgLabel = panelLabel(msgText, size: 12, weight: .medium,
                                  color: validation == nil ? .labelColor : .systemRed)
        msgLabel.toolTip = validation
        row.addArrangedSubview(msgLabel)
        row.addArrangedSubview(NSView())

        let discard = panelButton(
            t("Отменить", "Discard"),
            action: #selector(discardSettingsClicked(_:)),
            enabled: serviceOperation == nil
        )
        let save = panelButton(
            restartNeeded ? t("Применить и перезапустить", "Apply & Restart") : t("Сохранить", "Save"),
            action: #selector(saveSettingsClicked(_:)),
            enabled: validation == nil && serviceOperation == nil
        )
        save.keyEquivalent = "\r"
        row.addArrangedSubview(discard)
        row.addArrangedSubview(save)

        footer.addSubview(row)
        NSLayoutConstraint.activate([
            topBorder.leadingAnchor.constraint(equalTo: footer.leadingAnchor),
            topBorder.trailingAnchor.constraint(equalTo: footer.trailingAnchor),
            topBorder.topAnchor.constraint(equalTo: footer.topAnchor),

            row.leadingAnchor.constraint(equalTo: footer.leadingAnchor, constant: 20),
            row.trailingAnchor.constraint(equalTo: footer.trailingAnchor, constant: -20),
            row.centerYAnchor.constraint(equalTo: footer.centerYAnchor),
        ])
    }

    // MARK: - Option A Helpers: Instant Apply vs Staged Apply

    private func reloadDraftFromDisk() {
        _ = settings.refreshFromDisk()
        let fresh = ControlPanelSettingsDraft(settings: settings)
        settingsDraft = fresh
        settingsDraftBaseline = fresh
    }

    /// Applies a live setting immediately, notifies the running agent, and keeps
    /// both draft & baseline aligned so the staged footer never triggers falsely.
    func applyLiveSetting(_ mutateSettings: (Settings) -> Void,
                          updateDraft: (inout ControlPanelSettingsDraft) -> Void,
                          refreshDetail: Bool = true) {
        mutateSettings(settings)
        _ = settings.refreshFromDisk()
        var draft = settingsDraft ?? ControlPanelSettingsDraft(settings: settings)
        var baseline = settingsDraftBaseline ?? ControlPanelSettingsDraft(settings: settings)
        updateDraft(&draft)
        updateDraft(&baseline)
        settingsDraft = draft
        settingsDraftBaseline = baseline

        DistributedNotificationCenter.default().postNotificationName(
            SETTINGS_LIVE_CHANGED_NOTIFICATION,
            object: nil,
            userInfo: nil,
            deliverImmediately: true
        )
        if refreshDetail {
            refreshDetailContent(preserveScroll: true)
        }
        updateStagedFooter()
    }

    /// Stages a setting change in `settingsDraft` (requires Save or Apply & Restart).
    func stageSetting(_ updateDraft: (inout ControlPanelSettingsDraft) -> Void,
                      refreshDetail: Bool = true) {
        var draft = settingsDraft ?? ControlPanelSettingsDraft(settings: settings)
        updateDraft(&draft)
        settingsDraft = draft
        if refreshDetail {
            refreshDetailContent(preserveScroll: true)
        }
        updateStagedFooter()
    }

    // MARK: - Periodic Runtime Refresh (Never Interrupts Typing!)

    private func startRefreshTimer() {
        refreshTimer?.invalidate()
        refreshTimer = Timer.scheduledTimer(timeInterval: 0.75,
                                            target: self,
                                            selector: #selector(refreshTimerFired(_:)),
                                            userInfo: nil,
                                            repeats: true)
        refreshTimer?.tolerance = 0.15
    }

    @objc private func refreshTimerFired(_ timer: Timer) {
        refresh(force: false)
    }

    private func isEditingTextInMainWindow() -> Bool {
        guard let responder = window?.firstResponder else { return false }
        return responder is NSTextView || responder is NSTextField
    }

    private func runtimeFingerprint() -> String {
        let state = AgentRuntimeStateStore.read()
        let permissions = Permission.allCases.map { Permissions.isGranted($0) ? "1" : "0" }.joined()
        let inputDevices = selectedSection == .audio
            ? availableAudioInputDevices().map { "\($0.uid)=\($0.name)" }.joined(separator: "|")
            : ""
        let stateToken: String
        if serviceOperation != nil {
            stateToken = "operation"
        } else {
            let rawStatus = state?.status ?? "none"
            let healthy = ["ready", "recording", "transcribing"].contains(rawStatus)
            stateToken = [
                healthy ? "ready" : rawStatus,
                healthy ? "" : (state?.detail ?? ""),
                state?.downloadProgressFraction.map { String(format: "%.2f", $0) } ?? "",
                String(state?.pid ?? 0),
                state?.speechModelReady == true ? "1" : "0",
            ].joined(separator: "|")
        }
        return [
            language.rawValue,
            serviceOperation?.rawValue ?? "idle",
            updateStateFingerprint(),
            LexomorphAgentService.isAgentRunning() ? "running" : "stopped",
            stateToken,
            permissions,
            inputDevices,
            permissionClickCount.description,
        ].joined(separator: "::")
    }

    private func updateStateFingerprint() -> String {
        switch updateState {
        case .checking: return "checking"
        case .upToDate(let v): return "current:\(v)"
        case .available(let r): return "available:\(r.version)"
        case .preparing(let v, let p): return "preparing:\(v):\(p)"
        case .failed(let m): return "failed:\(m)"
        }
    }

    func refresh(force: Bool = false) {
        let fp = runtimeFingerprint()
        guard force || fp != lastRuntimeFingerprint else { return }
        lastRuntimeFingerprint = fp
        window?.title = mainWindowTitle()
        refreshSidebar()
        // Never rebuild detail content while user is actively typing in an input field!
        if force || !isEditingTextInMainWindow() {
            if force || selectedSection == .overview || selectedSection == .statistics || selectedSection == .system || selectedSection == .audio {
                refreshDetailContent(preserveScroll: true)
            }
        }
        updateStagedFooter()
    }

    private func syncFromExternalChange() {
        let hasStaged: Bool = {
            guard let draft = settingsDraft, let baseline = settingsDraftBaseline else { return false }
            return draft != baseline
        }()
        _ = settings.refreshFromDisk()
        if !hasStaged {
            let fresh = ControlPanelSettingsDraft(settings: settings)
            settingsDraft = fresh
            settingsDraftBaseline = fresh
        } else if var draft = settingsDraft, var baseline = settingsDraftBaseline {
            // Merge live-toggled modes from menu bar / hotkeys without losing staged edits!
            draft.textPostprocessingMode = settings.textPostprocessingMode
            draft.rewriteEnabled = settings.rewriteEnabled
            draft.rewriteStyleID = settings.rewriteStyleID
            baseline.textPostprocessingMode = settings.textPostprocessingMode
            baseline.rewriteEnabled = settings.rewriteEnabled
            baseline.rewriteStyleID = settings.rewriteStyleID
            settingsDraft = draft
            settingsDraftBaseline = baseline
        }
        refreshSidebar()
        if !isEditingTextInMainWindow() {
            refreshDetailContent(preserveScroll: true)
        }
        updateStagedFooter()
    }

    // MARK: - Navigation Actions

    @objc private func sidebarSectionClicked(_ sender: NSButton) {
        guard let section = ControlPanelSection(rawValue: sender.tag),
              section != selectedSection else { return }
        selectedSection = section
        refreshSidebar()
        refreshDetailContent(preserveScroll: false)
    }

    @objc func jumpToSectionClicked(_ sender: NSButton) {
        guard let section = ControlPanelSection(rawValue: sender.tag) else { return }
        selectedSection = section
        refreshSidebar()
        refreshDetailContent(preserveScroll: false)
    }

    @objc func jumpToAIRewriteClicked(_ sender: NSButton) {
        selectedSection = .ai
        selectedAISubsection = .rewrite
        refreshSidebar()
        refreshDetailContent(preserveScroll: false)
    }

    @objc func jumpToAIPunctuationClicked(_ sender: NSButton) {
        selectedSection = .ai
        selectedAISubsection = .punctuation
        refreshSidebar()
        refreshDetailContent(preserveScroll: false)
    }

    @objc func selectAISubsection(_ sender: NSSegmentedControl) {
        guard let sub = AISubsection(rawValue: sender.selectedSegment) else { return }
        selectedAISubsection = sub
        refreshDetailContent(preserveScroll: false)
    }

    @objc func toggleFillerListDisclosure(_ sender: NSButton) {
        fillerListExpanded.toggle()
        refreshDetailContent(preserveScroll: true)
    }

    @objc func toggleCorrectionPromptDisclosure(_ sender: NSButton) {
        correctionPromptExpanded.toggle()
        refreshDetailContent(preserveScroll: true)
    }

    @objc func toggleRewritePromptDisclosure(_ sender: NSButton) {
        rewritePromptExpanded.toggle()
        refreshDetailContent(preserveScroll: true)
    }

    // MARK: - Overview Quick Mode Actions (Instant Live Apply!)

    @objc func quickToggleCorrectionClicked(_ sender: NSSwitch) {
        let mode: TextPostprocessingMode = sender.state == .on ? .correction : .off
        applyLiveSetting({ $0.textPostprocessingMode = mode }, updateDraft: { $0.textPostprocessingMode = mode })
    }

    @objc func quickToggleRewriteClicked(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.rewriteEnabled = on }, updateDraft: { $0.rewriteEnabled = on })
    }

    @objc func quickSelectRewriteStyle(_ sender: NSPopUpButton) {
        guard let id = sender.selectedItem?.representedObject as? String else { return }
        applyLiveSetting({ $0.rewriteStyleID = id }, updateDraft: { $0.rewriteStyleID = id })
    }

    @objc func quickTogglePunctuationClicked(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.punctuationRestorationEnabled = on },
                         updateDraft: { $0.punctuationRestorationEnabled = on })
    }

    // MARK: - Instant Live Settings Actions (Option A)

    @objc func selectInterfaceLanguage(_ sender: NSSegmentedControl) {
        settings.interfaceLanguage = sender.selectedSegment == 1 ? .english : .russian
        _ = settings.refreshFromDisk()
        DistributedNotificationCenter.default().postNotificationName(
            SETTINGS_LIVE_CHANGED_NOTIFICATION,
            object: nil,
            userInfo: nil,
            deliverImmediately: true
        )
        lastRuntimeFingerprint = ""
        refresh(force: true)
    }

    @objc func selectTriggerModeDraft(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let mode = TriggerMode(rawValue: raw) else { return }
        applyLiveSetting({ $0.triggerMode = mode }, updateDraft: { $0.triggerMode = mode })
    }

    @objc func selectDictationLanguageDraft(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let lang = DictationLanguage(rawValue: raw) else { return }
        applyLiveSetting({ $0.dictationLanguage = lang }, updateDraft: { $0.dictationLanguage = lang })
    }

    @objc func selectPrimaryCompletionBehavior(_ sender: NSSegmentedControl) {
        let behavior: DictationCompletionBehavior = sender.selectedSegment == 1 ? .insertAndEnter : .insert
        applyLiveSetting({ $0.primaryCompletionBehavior = behavior },
                         updateDraft: { $0.primaryCompletionBehavior = behavior })
    }

    @objc func selectEnterDelay(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let ms = Int(raw) else { return }
        applyLiveSetting({ $0.enterDelayMilliseconds = ms }, updateDraft: { $0.enterDelayMilliseconds = ms })
    }

    @objc func selectPasteSuffixDraft(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let suffix = PasteSuffix(rawValue: raw) else { return }
        applyLiveSetting({ $0.pasteSuffix = suffix }, updateDraft: { $0.pasteSuffix = suffix })
    }

    @objc func selectRecentTranscriptLimitDraft(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let limit = RecentTranscriptLimit(rawValue: raw) else { return }
        applyLiveSetting({ $0.recentTranscriptLimit = limit }, updateDraft: { $0.recentTranscriptLimit = limit })
    }

    @objc func toggleNormalizeNumbers(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.normalizeNumbersToDigits = on }, updateDraft: { $0.normalizeNumbersToDigits = on })
    }

    @objc func toggleRemoveFillerWordsSetting(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.removeFillerWords = on }, updateDraft: { $0.removeFillerWords = on })
    }

    @objc func toggleRemoveFinalPeriodSetting(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.removeFinalPeriod = on }, updateDraft: { $0.removeFinalPeriod = on })
    }

    @objc func toggleFillerPreset(_ sender: NSButton) {
        guard let key = sender.identifier?.rawValue else { return }
        let on = sender.state == .on
        applyLiveSetting({
            var keys = $0.enabledFillerPresetKeys
            if on { keys.insert(key) } else { keys.remove(key) }
            $0.enabledFillerPresetKeys = keys
        }, updateDraft: {
            if on { $0.enabledFillerPresetKeys.insert(key) } else { $0.enabledFillerPresetKeys.remove(key) }
        }, refreshDetail: false)
    }

    @objc func toggleCustomFillerWord(_ sender: NSButton) {
        guard let word = sender.identifier?.rawValue else { return }
        let on = sender.state == .on
        applyLiveSetting({
            var disabled = $0.disabledCustomFillerWords
            if on { disabled.remove(word) } else { disabled.insert(word) }
            $0.disabledCustomFillerWords = disabled
        }, updateDraft: {
            if on { $0.disabledCustomFillerWords.remove(word) } else { $0.disabledCustomFillerWords.insert(word) }
        }, refreshDetail: false)
    }

    @objc func addCustomFillerWord(_ sender: NSTextField) {
        let word = sender.stringValue.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").lowercased()
        guard !word.isEmpty else { return }
        sender.stringValue = ""
        applyLiveSetting({
            if let preset = FillerWordRemover.presets.first(where: { $0.displayText.lowercased() == word }) {
                var keys = $0.enabledFillerPresetKeys; keys.insert(preset.key); $0.enabledFillerPresetKeys = keys
            } else if let existing = $0.customFillerWords.first(where: { $0.lowercased() == word }) {
                var disabled = $0.disabledCustomFillerWords; disabled.remove(existing); $0.disabledCustomFillerWords = disabled
            } else {
                var list = $0.customFillerWords; list.append(word); $0.customFillerWords = list
            }
        }, updateDraft: {
            if let preset = FillerWordRemover.presets.first(where: { $0.displayText.lowercased() == word }) {
                $0.enabledFillerPresetKeys.insert(preset.key)
            } else if let existing = $0.customFillerWords.first(where: { $0.lowercased() == word }) {
                $0.disabledCustomFillerWords.remove(existing)
            } else {
                $0.customFillerWords.append(word)
            }
        })
    }

    @objc func removeCustomFillerWord(_ sender: NSButton) {
        guard let word = sender.identifier?.rawValue else { return }
        applyLiveSetting({
            $0.customFillerWords = $0.customFillerWords.filter { $0 != word }
            var disabled = $0.disabledCustomFillerWords; disabled.remove(word); $0.disabledCustomFillerWords = disabled
        }, updateDraft: {
            $0.customFillerWords.removeAll { $0 == word }
            $0.disabledCustomFillerWords.remove(word)
        })
    }

    @objc func toggleAutoLearnVocabularySetting(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.autoLearnVocabularyEnabled = on }, updateDraft: { $0.autoLearnVocabularyEnabled = on })
    }

    @objc func toggleAsrHotwordsSetting(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.asrHotwordsEnabled = on }, updateDraft: { $0.asrHotwordsEnabled = on })
    }

    @objc func selectAsrHotwordsStrength(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let strength = AsrHotwordsStrength(rawValue: raw) else { return }
        applyLiveSetting({ $0.asrHotwordsStrength = strength }, updateDraft: { $0.asrHotwordsStrength = strength })
    }

    @objc func togglePlayFeedbackSoundsSetting(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.playFeedbackSounds = on }, updateDraft: { $0.playFeedbackSounds = on })
    }

    @objc func toggleShowRecordingWaveformSetting(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.showRecordingWaveform = on }, updateDraft: { $0.showRecordingWaveform = on })
    }

    @objc func selectRecordingHUDSize(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let size = RecordingHUDSize(rawValue: raw) else { return }
        applyLiveSetting({ $0.recordingHUDSize = size }, updateDraft: { $0.hudSize = size })
    }

    @objc func selectRecordingHUDDisplayMode(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let mode = RecordingHUDDisplayMode(rawValue: raw) else { return }
        applyLiveSetting({ $0.recordingHUDDisplayMode = mode }, updateDraft: { $0.hudDisplayMode = mode })
    }

    @objc func selectRecordingHUDBackgroundStyle(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let style = RecordingHUDBackgroundStyle(rawValue: raw) else { return }
        applyLiveSetting({ $0.recordingHUDBackgroundStyle = style }, updateDraft: { $0.backgroundStyle = style })
    }

    @objc func selectRecordingHUDRecordingColor(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let color = RecordingHUDAccentColor(rawValue: raw) else { return }
        applyLiveSetting({ $0.recordingHUDRecordingColor = color }, updateDraft: { $0.recordingColor = color })
    }

    @objc func selectRecordingHUDTranscribingColor(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let color = RecordingHUDAccentColor(rawValue: raw) else { return }
        applyLiveSetting({ $0.recordingHUDTranscribingColor = color }, updateDraft: { $0.transcribingColor = color })
    }

    @objc func selectRecordingHUDCorrectingColor(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let color = RecordingHUDAccentColor(rawValue: raw) else { return }
        applyLiveSetting({ $0.recordingHUDCorrectingColor = color }, updateDraft: { $0.correctingColor = color })
    }

    @objc func toggleCheckForUpdatesSetting(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.checkForUpdates = on }, updateDraft: { $0.checkForUpdates = on })
    }

    @objc func toggleLLMUseGPUSetting(_ sender: NSSwitch) {
        let on = sender.state == .on && HardwareCapabilities.shared.current().vulkanGPUAvailable
        applyLiveSetting({ $0.llmUseGPU = on }, updateDraft: { $0.llmUseGPU = on })
    }

    @objc func toggleLLMUseSystemProxy(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.llmUseSystemProxy = on }, updateDraft: { $0.llmUseSystemProxy = on })
    }

    @objc func toggleLLMCorrectionMode(_ sender: NSSwitch) {
        let mode: TextPostprocessingMode = sender.state == .on ? .correction : .off
        applyLiveSetting({ $0.textPostprocessingMode = mode }, updateDraft: { $0.textPostprocessingMode = mode })
    }

    @objc func selectLLMEngineBackend(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let backend = LLMEngineBackend(rawValue: raw) else { return }
        applyLiveSetting({ $0.llmEngineBackend = backend }, updateDraft: { $0.llmEngineBackend = backend })
    }

    @objc func selectCorrectionBundledModel(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let model = BundledLLMModel(rawValue: raw),
              BundledLLMModel.correctionModels.contains(model) else { return }
        applyLiveSetting({ $0.correctionBundledModel = model }, updateDraft: {
            $0.correctionModel = model
            if settings.correctionSystemPromptOverride.isEmpty {
                $0.correctionSystemPrompt = defaultCorrectionSystemPrompt(for: model)
            }
        })
    }

    @objc func toggleRewriteMode(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.rewriteEnabled = on }, updateDraft: { $0.rewriteEnabled = on })
    }

    @objc func selectRewriteStyle(_ sender: NSPopUpButton) {
        guard let id = sender.selectedItem?.representedObject as? String else { return }
        applyLiveSetting({ $0.rewriteStyleID = id }, updateDraft: { $0.rewriteStyleID = id })
    }

    @objc func selectRewriteBundledModel(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let model = BundledLLMModel(rawValue: raw),
              BundledLLMModel.rewriteModels.contains(model) else { return }
        applyLiveSetting({ $0.rewriteBundledModel = model }, updateDraft: { $0.rewriteBundledModel = model })
    }

    @objc func selectRewriteEngineBackend(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let backend = LLMEngineBackend(rawValue: raw) else { return }
        applyLiveSetting({ $0.rewriteEngineBackend = backend }, updateDraft: { $0.rewriteEngineBackend = backend })
    }

    @objc func togglePunctuationRestoration(_ sender: NSSwitch) {
        let on = sender.state == .on
        applyLiveSetting({ $0.punctuationRestorationEnabled = on },
                         updateDraft: { $0.punctuationRestorationEnabled = on })
    }

    @objc func selectPunctuationModel(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let model = PunctuationModel(rawValue: raw) else { return }
        applyLiveSetting({ $0.punctuationModel = model }, updateDraft: { $0.punctuationModel = model })
    }

    @objc func toggleLaunchAtLoginSetting(_ sender: NSSwitch) {
        do {
            switch SMAppService.mainApp.status {
            case .enabled, .requiresApproval:
                try SMAppService.mainApp.unregister()
                log("launch at login disabled")
            default:
                try SMAppService.mainApp.register()
                log("launch at login enabled")
            }
        } catch {
            showError(title: t("Не удалось изменить запуск при входе", "Couldn't change Launch at Login"),
                      detail: "\(error)")
        }
        refreshDetailContent(preserveScroll: true)
    }

    // MARK: - Staged (Restart-Required / Buffered Text) Actions

    @objc func selectSpeechModelProfile(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let profile = SpeechModelProfile(rawValue: raw) else { return }
        stageSetting { $0.speechModelProfile = profile }
    }

    @objc func toggleAlternateCompletion(_ sender: NSSwitch) {
        stageSetting { $0.alternateCompletionEnabled = sender.state == .on }
    }

    @objc func selectInputDeviceDraft(_ sender: NSPopUpButton) {
        guard let preference = sender.selectedItem?.representedObject as? String else { return }
        stageSetting { $0.inputDevicePreference = preference }
    }

    @objc func toggleAutoStopOnSilence(_ sender: NSSwitch) {
        stageSetting { $0.autoStopOnSilenceEnabled = sender.state == .on }
    }

    @objc func selectAutoStopSilenceSeconds(_ sender: NSPopUpButton) {
        guard let raw = sender.selectedItem?.representedObject as? String,
              let seconds = Int(raw) else { return }
        stageSetting { $0.autoStopSilenceSeconds = seconds }
    }

    @objc func toggleMuteWhileRecordingSetting(_ sender: NSSwitch) {
        stageSetting { $0.muteWhileRecording = sender.state == .on }
    }

    @objc func selectRewritePromptStyle(_ sender: NSPopUpButton) {
        guard let id = sender.selectedItem?.representedObject as? String else { return }
        rewritePromptEditorStyleID = id
        refreshDetailContent(preserveScroll: true)
    }

    @objc func resetCorrectionPromptClicked(_ sender: NSButton) {
        stageSetting { $0.correctionSystemPrompt = defaultCorrectionSystemPrompt(for: $0.correctionModel) }
    }

    @objc func resetRewritePromptClicked(_ sender: NSButton) {
        let styleID = rewritePromptEditorStyleID
        stageSetting { $0.rewriteSystemPrompts[styleID] = defaultRewriteSystemPrompt(forStyleID: styleID, draft: $0) }
    }

    // MARK: - Text Delegate (Prompts, Endpoints, Account Sign-In)

    func textDidChange(_ notification: Notification) {
        guard let textView = notification.object as? NSTextView else { return }
        switch textView.identifier {
        case Self.correctionSystemPromptEditorID:
            stageSetting({ $0.correctionSystemPrompt = textView.string }, refreshDetail: false)
        case Self.rewriteSystemPromptEditorID:
            let styleID = rewritePromptEditorStyleID
            stageSetting({ $0.rewriteSystemPrompts[styleID] = textView.string }, refreshDetail: false)
        default:
            return
        }
    }

    func controlTextDidChange(_ obj: Notification) {
        guard let field = obj.object as? NSTextField else { return }
        switch field.tag {
        case Self.vocabularySyncEmailFieldTag:
            vocabularySyncEmailInput = field.stringValue
            return
        case Self.vocabularySyncPasswordFieldTag:
            vocabularySyncPasswordInput = field.stringValue
            return
        case Self.llmCustomBaseURLFieldTag:
            stageSetting({ $0.llmCustomBaseURL = field.stringValue }, refreshDetail: false)
        case Self.llmCustomAPIKeyFieldTag:
            stageSetting({ $0.llmCustomAPIKey = field.stringValue }, refreshDetail: false)
        case Self.llmCustomModelNameFieldTag:
            stageSetting({ $0.llmCustomModelName = field.stringValue }, refreshDetail: false)
        case Self.rewriteCustomBaseURLFieldTag:
            stageSetting({ $0.rewriteCustomBaseURL = field.stringValue }, refreshDetail: false)
        case Self.rewriteCustomAPIKeyFieldTag:
            stageSetting({ $0.rewriteCustomAPIKey = field.stringValue }, refreshDetail: false)
        case Self.rewriteCustomModelNameFieldTag:
            stageSetting({ $0.rewriteCustomModelName = field.stringValue }, refreshDetail: false)
        default:
            return
        }
    }

    // MARK: - Save & Discard Staged Changes

    func settingsRestartRequired(_ draft: ControlPanelSettingsDraft) -> Bool {
        let persisted = settingsDraftBaseline ?? ControlPanelSettingsDraft(settings: settings)
        return draft.speechModelProfile != persisted.speechModelProfile
            || draft.dictationHotkey != persisted.dictationHotkey
            || draft.alternateCompletionHotkey != persisted.alternateCompletionHotkey
            || draft.alternateCompletionEnabled != persisted.alternateCompletionEnabled
            || draft.historyHotkey != persisted.historyHotkey
            || draft.correctionHotkey != persisted.correctionHotkey
            || draft.rewriteToggleHotkey != persisted.rewriteToggleHotkey
            || draft.rewriteStyleHotkey != persisted.rewriteStyleHotkey
            || draft.customRewriteStyles != persisted.customRewriteStyles
            || draft.inputDevicePreference != persisted.inputDevicePreference
            || draft.muteWhileRecording != persisted.muteWhileRecording
            || draft.autoStopOnSilenceEnabled != persisted.autoStopOnSilenceEnabled
            || draft.autoStopSilenceSeconds != persisted.autoStopSilenceSeconds
    }

    func settingsValidationMessage(_ draft: ControlPanelSettingsDraft) -> String? {
        var pairs: [(HotkeyChoice, HotkeyChoice, Bool)] = [
            (draft.dictationHotkey, draft.historyHotkey, true),
            (draft.dictationHotkey, draft.correctionHotkey, true),
            (draft.correctionHotkey, draft.historyHotkey, true),
        ]
        if draft.alternateCompletionEnabled {
            pairs.append((draft.dictationHotkey, draft.alternateCompletionHotkey, false))
            pairs.append((draft.alternateCompletionHotkey, draft.historyHotkey, true))
            pairs.append((draft.correctionHotkey, draft.alternateCompletionHotkey, true))
        }
        for (first, second, allowModifierPrefix) in pairs {
            if hotkeysConflict(first, second) {
                return t("Сочетания для диктовки, завершения, истории и коррекции должны отличаться.",
                         "Dictation, finish, history, and correction shortcuts must be different.")
            }
            if !allowModifierPrefix &&
                (hotkeyIsModifierPrefix(first, of: second) || hotkeyIsModifierPrefix(second, of: first)) {
                return t("Одна активная комбинация не должна быть частью другой.",
                         "One active shortcut cannot be a prefix of another.")
            }
        }
        return nil
    }

    @objc func discardSettingsClicked(_ sender: NSButton) {
        reloadDraftFromDisk()
        refreshDetailContent(preserveScroll: true)
        updateStagedFooter()
    }

    @objc func saveSettingsClicked(_ sender: NSButton) {
        guard let draft = settingsDraft,
              settingsValidationMessage(draft) == nil else { return }
        let restartRequired = settingsRestartRequired(draft)

        settings.setConfiguredHotkey(draft.dictationHotkey)
        settings.setConfiguredEnterHotkey(draft.alternateCompletionHotkey)
        settings.setConfiguredHistoryHotkey(draft.historyHotkey)
        settings.setConfiguredCorrectionHotkey(draft.correctionHotkey)
        settings.setConfiguredRewriteToggleHotkey(draft.rewriteToggleHotkey)
        settings.setConfiguredRewriteStyleHotkey(draft.rewriteStyleHotkey)
        settings.alternateCompletionEnabled = draft.alternateCompletionEnabled
        settings.speechModelProfile = draft.speechModelProfile
        settings.inputDevice = draft.inputDevicePreference
        settings.autoStopOnSilenceEnabled = draft.autoStopOnSilenceEnabled
        settings.autoStopSilenceSeconds = draft.autoStopSilenceSeconds
        settings.muteWhileRecording = draft.muteWhileRecording
        settings.llmCustomBaseURL = draft.llmCustomBaseURL
        settings.llmCustomAPIKey = draft.llmCustomAPIKey
        settings.llmCustomModelName = draft.llmCustomModelName
        settings.rewriteCustomBaseURL = draft.rewriteCustomBaseURL
        settings.rewriteCustomAPIKey = draft.rewriteCustomAPIKey
        settings.rewriteCustomModelName = draft.rewriteCustomModelName
        settings.rewriteStyleID = draft.rewriteStyleID

        let correctionPromptDefault = defaultCorrectionSystemPrompt(for: draft.correctionModel)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let correctionPromptText = draft.correctionSystemPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
        settings.correctionSystemPromptOverride = correctionPromptText == correctionPromptDefault ? "" : draft.correctionSystemPrompt

        let allStyles: [(id: String, defaultPrompt: String)] =
            RewriteStyle.allCases.map { ($0.rawValue, defaultRewriteSystemPrompt(for: $0)) }
            + draft.customRewriteStyles.map { ($0.id, LLMRewritePrompt.systemPrompt(custom: $0)) }
        for styleEntry in allStyles {
            if RewriteStyle(rawValue: styleEntry.id) != nil,
               let loaded = draft.rewriteSystemPromptsBaseline[styleEntry.id],
               draft.rewriteSystemPrompts[styleEntry.id] == loaded {
                continue
            }
            let styleDefault = styleEntry.defaultPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
            let styleText = (draft.rewriteSystemPrompts[styleEntry.id] ?? styleEntry.defaultPrompt)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            settings.setRewriteSystemPromptOverride(
                styleText == styleDefault ? "" : (draft.rewriteSystemPrompts[styleEntry.id] ?? styleDefault),
                forStyleID: styleEntry.id)
        }
        settings.mergeCustomRewriteStyles(draft: draft.customRewriteStyles,
                                          baseline: draft.customRewriteStylesBaseline)
        settings.agentEnabled = true
        reloadDraftFromDisk()

        if restartRequired {
            beginServiceOperation(.applyingSettings)
        } else {
            DistributedNotificationCenter.default().postNotificationName(
                SETTINGS_LIVE_CHANGED_NOTIFICATION,
                object: nil,
                userInfo: nil,
                deliverImmediately: true
            )
            refreshDetailContent(preserveScroll: true)
            updateStagedFooter()
        }
    }

    // MARK: - Hotkey Recording

    @objc func recordDictationShortcutClicked(_ sender: NSButton) {
        guard serviceOperation == nil,
              let kind = ControlPanelShortcutKind(rawValue: sender.tag) else { return }
        if let hotkeyRecorder {
            hotkeyRecorder.present(relativeTo: window)
            return
        }
        let state = AgentRuntimeStateStore.read()
        if state?.isRecording == true || state?.isTranscribing == true {
            showError(title: t("Сначала завершите диктовку", "Finish Dictation First"),
                      detail: t("Сочетание нельзя менять во время записи или распознавания.",
                                "Shortcuts cannot be changed while recording or transcribing."))
            return
        }
        if LexomorphAgentService.isAgentRunning(), state?.isReady != true {
            showError(title: t("Служба ещё запускается", "Service Is Still Starting"),
                      detail: t("Дождитесь статуса «Работает» и попробуйте ещё раз.",
                                "Wait for Running status, then try again."))
            return
        }

        DistributedNotificationCenter.default().postNotificationName(
            HOTKEY_CAPTURE_BEGIN_NOTIFICATION, object: nil, userInfo: nil, deliverImmediately: true
        )
        let recorderTitle: String
        switch kind {
        case .dictation: recorderTitle = t("Новое сочетание для диктовки", "New Dictation Shortcut")
        case .alternateCompletion: recorderTitle = t("Дополнительное сочетание завершения", "Alternative Finish Shortcut")
        case .history: recorderTitle = t("Новое сочетание для истории", "New History Shortcut")
        case .correction: recorderTitle = t("Новое сочетание для коррекции", "New Correction Shortcut")
        case .rewriteToggle: recorderTitle = t("Новое сочетание для рерайта", "New Rewrite Shortcut")
        case .rewriteStyle: recorderTitle = t("Новое сочетание режима рерайта", "New Rewrite Style Shortcut")
        }
        let recorder = HotkeyRecorderController(language: language, titleOverride: recorderTitle) { [weak self] selected in
            DistributedNotificationCenter.default().postNotificationName(
                HOTKEY_CAPTURE_END_NOTIFICATION, object: nil, userInfo: nil, deliverImmediately: true
            )
            guard let self else { return }
            self.hotkeyRecorder = nil
            guard let selected else { return }
            self.stageSetting { draft in
                switch kind {
                case .dictation: draft.dictationHotkey = selected
                case .alternateCompletion: draft.alternateCompletionHotkey = selected
                case .history: draft.historyHotkey = selected
                case .correction: draft.correctionHotkey = selected
                case .rewriteToggle: draft.rewriteToggleHotkey = selected
                case .rewriteStyle: draft.rewriteStyleHotkey = selected
                }
            }
        }
        hotkeyRecorder = recorder
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) { [weak self, weak recorder] in
            guard self?.hotkeyRecorder === recorder else { return }
            recorder?.present(relativeTo: self?.window)
        }
    }

    // MARK: - Custom Rewrite Style Actions

    @objc func customStyleEditorCancelClicked(_ sender: NSButton) {
        closeCustomStyleEditor()
    }

    @objc func customStyleEditorSaveClicked(_ sender: NSButton) {
        guard let nameField = customStyleEditorNameField else { return }
        let name = nameField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else {
            nameField.placeholderString = t("Введите имя режима", "Enter a mode name")
            return
        }
        let instructionText = customStyleEditorInstructionView?.string ?? ""
        let colorHex = customStyleEditorColor
        let keycode = Int(customStyleEditorHotkey?.keycode ?? 0)
        let modifiers = customStyleEditorHotkey?.requiredModifiers.rawValue ?? 0

        stageSetting { draft in
            var styles = draft.customRewriteStyles
            if let existing = customStyleEditorExisting,
               let index = styles.firstIndex(where: { $0.id == existing.id }) {
                styles[index].name = name
                styles[index].colorHex = colorHex
                styles[index].instruction = instructionText
                styles[index].hotkeyKeycode = keycode
                styles[index].hotkeyModifiers = modifiers
            } else {
                styles.append(CustomRewriteStyle(
                    id: "c-\(UUID().uuidString)",
                    name: name,
                    colorHex: colorHex,
                    instruction: instructionText,
                    hotkeyKeycode: keycode,
                    hotkeyModifiers: modifiers
                ))
            }
            draft.customRewriteStyles = styles
        }
        closeCustomStyleEditor()
    }

    @objc func addCustomRewriteStyleClicked(_ sender: NSButton) {
        let draft = settingsDraft ?? ControlPanelSettingsDraft(settings: settings)
        presentCustomStyleEditor(draft, existing: nil)
    }

    @objc func editCustomRewriteStyleClicked(_ sender: NSButton) {
        let draft = settingsDraft ?? ControlPanelSettingsDraft(settings: settings)
        guard draft.customRewriteStyles.indices.contains(sender.tag) else { return }
        presentCustomStyleEditor(draft, existing: draft.customRewriteStyles[sender.tag])
    }

    @objc func deleteCustomRewriteStyleClicked(_ sender: NSButton) {
        stageSetting { draft in
            guard draft.customRewriteStyles.indices.contains(sender.tag) else { return }
            let removed = draft.customRewriteStyles.remove(at: sender.tag)
            if draft.rewriteStyleID == removed.id {
                draft.rewriteStyleID = RewriteStyle.polish.rawValue
            }
        }
    }

    @objc func customStyleHotkeyClicked(_ sender: NSButton) {
        let index = sender.tag
        guard (settingsDraft?.customRewriteStyles ?? []).indices.contains(index) else { return }
        startCustomStyleHotkeyRecording { [weak self] selected in
            self?.stageSetting { draft in
                guard draft.customRewriteStyles.indices.contains(index) else { return }
                draft.customRewriteStyles[index].hotkeyKeycode = Int(selected.keycode)
                draft.customRewriteStyles[index].hotkeyModifiers = selected.requiredModifiers.rawValue
            }
        }
    }

    @objc func customStyleEditorHotkeyClicked(_ sender: NSButton) {
        startCustomStyleHotkeyRecording { [weak self] selected in
            guard let self else { return }
            self.customStyleEditorHotkey = selected
            sender.title = localizedHotkeyName(selected, language: self.language)
        }
    }

    private func startCustomStyleHotkeyRecording(completion: @escaping (HotkeyChoice) -> Void) {
        DistributedNotificationCenter.default().postNotificationName(
            HOTKEY_CAPTURE_BEGIN_NOTIFICATION, object: nil, userInfo: nil, deliverImmediately: true
        )
        let recorder = HotkeyRecorderController(
            language: language,
            titleOverride: t("Нажмите сочетание для режима", "Press the shortcut for this mode")
        ) { [weak self] selected in
            DistributedNotificationCenter.default().postNotificationName(
                HOTKEY_CAPTURE_END_NOTIFICATION, object: nil, userInfo: nil, deliverImmediately: true
            )
            guard let self else { return }
            self.hotkeyRecorder = nil
            guard let selected else { return }
            completion(selected)
        }
        hotkeyRecorder = recorder
        recorder.present(relativeTo: window)
    }

    // MARK: - Model Downloads & Benchmark Help

    @objc func startBundledModelDownloadClicked(_ sender: NSButton) {
        guard BundledLLMModel.allCases.indices.contains(sender.tag) else { return }
        let model = BundledLLMModel.allCases[sender.tag]
        guard llmModelDownloadTask == nil else { return }
        llmModelDownloadModel = model
        llmModelDownloadState = .downloading
        refreshDetailContent(preserveScroll: true)
        llmModelDownloadTask = Task { [weak self, model] in
            do {
                _ = try await downloadBundledLLMModelIfNeeded(model, progress: { [weak self] received, total in
                    Task { @MainActor in
                        guard let self else { return }
                        self.llmModelDownloadProgress = (received, total)
                        let fraction = total > 0 ? Double(received) / Double(total) : 0
                        self.llmDownloadStatusLabel?.stringValue = self.t(
                            "Скачивание… \(Int(fraction * 100))% (\(formattedByteCount(UInt64(received))) из \(formattedByteCount(UInt64(total))))",
                            "Downloading… \(Int(fraction * 100))% (\(formattedByteCount(UInt64(received))) of \(formattedByteCount(UInt64(total))))"
                        )
                        if let bar = self.llmDownloadProgressBar, !bar.isIndeterminate {
                            bar.doubleValue = fraction
                        }
                    }
                })
                guard let self, !Task.isCancelled else { return }
                self.llmModelDownloadState = .idle
                self.llmModelDownloadProgress = nil
            } catch is CancellationError {
            } catch {
                guard let self else { return }
                self.llmModelDownloadState = .failed(
                    self.t("Не удалось скачать модель: \(error.localizedDescription)",
                           "Couldn't download model: \(error.localizedDescription)")
                )
            }
            guard let self else { return }
            self.llmModelDownloadTask = nil
            self.refreshDetailContent(preserveScroll: true)
        }
    }

    @objc func cancelLLMModelDownload(_ sender: NSButton) {
        llmModelDownloadTask?.cancel()
        llmModelDownloadTask = nil
        llmModelDownloadState = .idle
        refreshDetailContent(preserveScroll: true)
    }

    @objc func startPunctuationModelDownload(_ sender: NSButton) {
        guard punctuationDownloadTask == nil else { return }
        let model = (settingsDraft ?? ControlPanelSettingsDraft(settings: settings)).punctuationModel
        punctuationDownloadModel = model
        punctuationDownloadFraction = 0
        punctuationDownloadError = nil
        refreshDetailContent(preserveScroll: true)
        punctuationDownloadTask = Task { [weak self, model] in
            do {
                try await downloadPunctuationModelIfNeeded(model, progressHandler: { [weak self] fraction in
                    Task { @MainActor in
                        guard let self else { return }
                        self.punctuationDownloadFraction = fraction
                        self.punctuationDownloadStatusLabel?.stringValue = self.t(
                            "Скачивание… \(Int(fraction * 100))%", "Downloading… \(Int(fraction * 100))%")
                        self.punctuationDownloadProgressBar?.doubleValue = fraction
                    }
                })
            } catch is CancellationError {
            } catch {
                guard let self else { return }
                self.punctuationDownloadError = self.t("Не удалось скачать модель: \(error.localizedDescription)",
                                                       "Couldn't download model: \(error.localizedDescription)")
            }
            guard let self else { return }
            self.punctuationDownloadTask = nil
            self.punctuationDownloadFraction = nil
            self.refreshDetailContent(preserveScroll: true)
        }
    }

    @objc func cancelPunctuationModelDownload(_ sender: NSButton) {
        punctuationDownloadTask?.cancel()
        punctuationDownloadTask = nil
        punctuationDownloadFraction = nil
        refreshDetailContent(preserveScroll: true)
    }

    @objc func showBenchmarkHelp(_ sender: NSButton) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = t("Замеры моделей (бенчмарк, 21.08.2026)", "Model benchmark (Aug 21, 2026)")
        alert.informativeText = t("""
        Замеры на этом Mac (AMD Radeon RX 6600, llama.cpp/Vulkan). Полный отчёт — benchmark/REPORT.md.

        КОРРЕКЦИЯ (EM — доля идеально исправленных фраз)
        • VoiceScribe V15 R-3 — EM 0,60, 0,19 с, 0,7 ГБ. Рекомендуется для повседневной диктовки.
        • Qwen3.5-4B Q6_K — EM 0,72, 0,55 с, 3,8 ГБ.
        • RuAdapt Qwen3-4B Q6_K — EM 0,68, 0,38 с, 3,3 ГБ.
        • YandexGPT 5 Lite 8B Q4_K_M — EM 0,89, 0,43 с, 4,9 ГБ.

        РЕРАЙТ (FactRec — сохранение фактов, длина — отношение к исходнику)
        • YandexGPT 5 Lite 8B Q4_K_M — FactRec 0,53, длина 0,97×, ~2,7 с, 4,9 ГБ. Рекомендуется.
        • Qwen3.5-9B Q4_K_M — FactRec 0,49, длина 1,19×, ~3,2 с, 5,7 ГБ.
        • Gemma 4 E4B Q4_0 — FactRec 0,48, длина 1,44×, ~2,3 с, 5,2 ГБ.
        """, """
        Measured on AMD Radeon RX 6600, llama.cpp/Vulkan. Full report: benchmark/REPORT.md.

        CORRECTION (EM — exact-match share)
        • VoiceScribe V15 R-3 — EM 0.60, 0.19 s, 0.7 GB. Recommended for everyday dictation.
        • Qwen3.5-4B Q6_K — EM 0.72, 0.55 s, 3.8 GB.
        • RuAdapt Qwen3-4B Q6_K — EM 0.68, 0.38 s, 3.3 GB.
        • YandexGPT 5 Lite 8B Q4_K_M — EM 0.89, 0.43 s, 4.9 GB.

        REWRITE (FactRec — fact preservation)
        • YandexGPT 5 Lite 8B Q4_K_M — FactRec 0.53, length 0.97×, ~2.7 s, 4.9 GB. Recommended.
        • Qwen3.5-9B Q4_K_M — FactRec 0.49, length 1.19×, ~3.2 s, 5.7 GB.
        • Gemma 4 E4B Q4_0 — FactRec 0.48, length 1.44×, ~2.3 s, 5.2 GB.
        """)
        alert.addButton(withTitle: t("Понятно", "Got it"))
        _ = alert.runModal()
    }

    // MARK: - Account & Sync Actions

    @objc func openVocabularyManager() {
        vocabularyManagerWindowController.show()
    }

    @objc func cleanVocabularyClicked() {
        vocabularyCleanupWindowController.present(relativeTo: window)
    }

    private func vocabularySyncStatusChanged() {
        if vocabularySyncStatusLabel != nil, !vocabularySyncBusy, !vocabularySync.isSignedIn {
            refreshDetailContent(preserveScroll: true)
        } else {
            updateVocabularySyncStatusLabel()
        }
    }

    func updateVocabularySyncStatusLabel() {
        guard let label = vocabularySyncStatusLabel else { return }
        _ = settings.refreshFromDisk()
        var parts: [String] = []
        if let last = settings.vocabularySyncLastSyncAt {
            let formatter = DateFormatter()
            formatter.dateStyle = .short
            formatter.timeStyle = .short
            formatter.locale = Locale(identifier: language == .russian ? "ru_RU" : "en_US")
            parts.append(t("Синхронизировано: \(formatter.string(from: last))",
                           "Synced: \(formatter.string(from: last))"))
        } else {
            parts.append(t("Ещё не синхронизировано", "Not synced yet"))
        }
        if vocabularySync.isSyncing || vocabularySyncBusy {
            parts.append(t("синхронизация…", "syncing…"))
        } else if let raw = settings.vocabularySyncLastError, let failure = VocabularySyncFailure(rawValue: raw) {
            parts.append(vocabularySyncFailureText(failure))
        } else if settings.vocabularySyncLastSyncAt != nil {
            parts.append(t("актуально", "up to date"))
        }
        label.stringValue = parts.joined(separator: " · ")
    }

    private func vocabularySyncFailureText(_ failure: VocabularySyncFailure) -> String {
        switch failure {
        case .wrongPassword: return t("Неверный пароль.", "Wrong password.")
        case .tooManyAttempts: return t("Слишком много попыток входа. Попробуйте позже.", "Too many attempts. Try later.")
        case .invalidCredentials: return t("Проверьте почту; пароль не короче 8 символов.", "Check e-mail; password must be at least 8 chars.")
        case .unauthorized, .notSignedIn: return t("Войдите снова.", "Sign in again.")
        case .network: return t("Нет соединения с сервером.", "No connection to sync server.")
        case .server: return t("Ошибка сервера синхронизации.", "Sync server error.")
        case .busy: return t("Синхронизация занята, повторим позже.", "Sync is busy; retrying later.")
        case .keychain: return t("Не удалось сохранить вход в связке ключей.", "Could not store sign-in in Keychain.")
        }
    }

    @objc func vocabularySyncSignInClicked() {
        let email = (vocabularySyncEmailInput ?? settings.vocabularySyncEmail).trimmingCharacters(in: .whitespacesAndNewlines)
        let password = vocabularySyncPasswordInput
        guard !email.isEmpty, !password.isEmpty else {
            vocabularySyncMessage = t("Введите почту и пароль.", "Enter e-mail and password.")
            refreshDetailContent(preserveScroll: true)
            return
        }
        vocabularySyncBusy = true
        vocabularySyncMessage = nil
        refreshDetailContent(preserveScroll: true)
        Task { @MainActor in
            let result = await vocabularySync.signIn(email: email, password: password)
            vocabularySyncBusy = false
            switch result {
            case .success:
                vocabularySyncPasswordInput = ""
                vocabularySyncEmailInput = nil
                if let raw = settings.vocabularySyncLastError, let failure = VocabularySyncFailure(rawValue: raw) {
                    vocabularySyncMessage = vocabularySyncFailureText(failure)
                }
            case .failure(let failure):
                vocabularySyncMessage = vocabularySyncFailureText(failure)
            }
            reloadDraftFromDisk()
            refreshDetailContent(preserveScroll: true)
        }
    }

    @objc func vocabularySyncNowClicked() {
        vocabularySyncBusy = true
        vocabularySyncMessage = nil
        refreshDetailContent(preserveScroll: true)
        Task { @MainActor in
            let failure = await vocabularySync.sync(trigger: "manual", manual: true)
            vocabularySyncBusy = false
            vocabularySyncMessage = failure.map(vocabularySyncFailureText)
            reloadDraftFromDisk()
            refreshDetailContent(preserveScroll: true)
        }
    }

    @objc func vocabularySyncSignOutClicked() {
        vocabularySyncBusy = true
        vocabularySyncMessage = nil
        refreshDetailContent(preserveScroll: true)
        Task { @MainActor in
            await vocabularySync.signOut()
            vocabularySyncBusy = false
            vocabularySyncPasswordInput = ""
            refreshDetailContent(preserveScroll: true)
        }
    }

    // MARK: - Service Lifecycle, Permissions, Maintenance & Updates

    private func beginServiceOperation(_ operation: ControlPanelServiceOperation) {
        guard serviceOperation == nil else { return }
        serviceOperation = operation
        lastRuntimeFingerprint = ""
        refresh(force: true)
        let startedAt = Date().timeIntervalSince1970

        Task { [weak self] in
            let failure = await Task.detached(priority: .userInitiated) { () -> String? in
                do {
                    switch operation {
                    case .starting: try LexomorphAgentService.installAndStart()
                    case .restarting, .applyingSettings: try LexomorphAgentService.restart()
                    case .stopping: LexomorphAgentService.stop()
                    }
                    return nil
                } catch {
                    return error.localizedDescription
                }
            }.value

            guard let self else { return }
            if failure == nil {
                await self.waitForServiceResult(operation: operation, startedAt: startedAt)
            }
            self.serviceOperation = nil
            self.lastRuntimeFingerprint = ""
            self.refresh(force: true)
            if let failure {
                self.showError(title: self.t("Не удалось изменить состояние службы", "Service operation failed"),
                               detail: failure)
            }
        }
    }

    private func waitForServiceResult(operation: ControlPanelServiceOperation, startedAt: TimeInterval) async {
        for _ in 0..<80 {
            let state = AgentRuntimeStateStore.read()
            if operation == .stopping {
                if state?.status == "stopped" { return }
            } else if let state,
                      state.updatedAt >= startedAt,
                      ["ready", "error", "needs_permissions"].contains(state.status) {
                return
            }
            try? await Task.sleep(nanoseconds: 250_000_000)
        }
    }

    @objc func startAgentClicked(_ sender: NSButton) {
        settings.agentEnabled = true
        _ = settings.refreshFromDisk()
        beginServiceOperation(.starting)
    }

    @objc func restartAgentClicked(_ sender: NSButton) {
        settings.agentEnabled = true
        _ = settings.refreshFromDisk()
        beginServiceOperation(.restarting)
    }

    @objc func stopAgentClicked(_ sender: NSButton) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = t("Остановить службу диктовки?", "Stop Dictation Service?")
        alert.informativeText = t("Хоткей перестанет работать, но история, модель и настройки сохранятся.",
                                  "The shortcut will stop, but history, model, and settings remain saved.")
        alert.addButton(withTitle: t("Оставить включённой", "Keep Running"))
        alert.addButton(withTitle: t("Остановить", "Stop Service"))
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        settings.agentEnabled = false
        _ = settings.refreshFromDisk()
        beginServiceOperation(.stopping)
    }

    @objc func grantPermissionClicked(_ sender: NSButton) {
        guard Permission.allCases.indices.contains(sender.tag) else { return }
        let permission = Permission.allCases[sender.tag]
        if Permissions.isGranted(permission) {
            permissionClickCount[permission] = nil
            refresh(force: true)
            return
        }
        let clicks = (permissionClickCount[permission] ?? 0) + 1
        permissionClickCount[permission] = clicks
        if clicks >= 2 {
            Permissions.openSettings(for: permission)
        } else {
            Permissions.request(permission)
        }
        refresh(force: true)
    }

    @objc func resetPermissionsClicked(_ sender: NSButton) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = t("Сбросить разрешения?", "Reset Permissions?")
        alert.informativeText = t("macOS отзовёт у Lexomorph микрофон, вставку текста и мониторинг ввода. Приложение перезапустится и снова попросит доступ.",
                                  "macOS will revoke Lexomorph's microphone, text insertion, and input monitoring. The app will relaunch and ask again.")
        alert.addButton(withTitle: t("Отмена", "Cancel"))
        alert.addButton(withTitle: t("Сбросить", "Reset"))
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        Permissions.resetAll()
        permissionClickCount = [:]
        refresh(force: true)
    }

    @objc func openDiagnosticLogClicked(_ sender: NSButton) {
        NSWorkspace.shared.open(Logger.shared.fileURL)
        log("diagnostics log opened")
    }

    @objc func resetSpeechModelCacheFromSettingsClicked(_ sender: NSButton) {
        guard serviceOperation == nil else { return }
        let profile = settings.speechModelProfile
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = t("Сбросить кэш речевой модели?", "Reset Speech Model Cache?")
        alert.informativeText = t(
            "Lexomorph удалит локальный кэш модели \(profile.shortName), перезапустит службу и заново скачает проверенную копию.",
            "Lexomorph will delete the local \(profile.shortName) model cache, restart the service, and download a fresh verified copy."
        )
        alert.addButton(withTitle: t("Отмена", "Cancel"))
        alert.addButton(withTitle: t("Сбросить", "Reset"))
        guard alert.runModal() == .alertSecondButtonReturn else { return }

        let cacheDir = speechModelCacheDirectory(for: profile)
        Task { [weak self] in
            guard let self else { return }
            do {
                _ = try await removeSpeechModelCacheDirectory(cacheDir)
                log("ASR: removed \(profile.shortName) cache from settings")
                self.beginServiceOperation(.restarting)
            } catch {
                self.showError(title: self.t("Не удалось сбросить кэш модели", "Couldn't reset speech model cache"),
                               detail: error.localizedDescription)
            }
        }
    }

    // MARK: - Updates

    func compactUpdatePresentation() -> (symbol: String,
                                         color: NSColor,
                                         title: String,
                                         detail: String,
                                         buttonTitle: String?,
                                         action: Selector?,
                                         buttonEnabled: Bool,
                                         buttonToolTip: String?) {
        switch updateState {
        case .checking:
            return ("arrow.triangle.2.circlepath", .systemBlue,
                    t("Проверяю обновления", "Checking for updates"),
                    t("Установлена v\(currentBundleVersion())", "Installed v\(currentBundleVersion())"),
                    nil, nil, false, nil)
        case .upToDate:
            return ("checkmark.circle.fill", .systemGreen,
                    t("Lexomorph актуален", "Lexomorph is up to date"),
                    t("Установлена последняя версия v\(currentBundleVersion())",
                      "Latest version v\(currentBundleVersion()) is installed"),
                    t("Проверить", "Check"), #selector(updateButtonClicked(_:)), true,
                    t("Проверить GitHub Releases ещё раз", "Check GitHub Releases again"))
        case .available(let release):
            return ("arrow.down.circle.fill", .systemBlue,
                    t("Доступна версия v\(release.version)", "Version v\(release.version) is available"),
                    t("Скачается, проверится и установится автоматически",
                      "Downloads, verifies, and installs automatically"),
                    t("Обновить", "Update"), #selector(updateButtonClicked(_:)), serviceOperation == nil,
                    t("Обновить Lexomorph до v\(release.version)", "Update Lexomorph to v\(release.version)"))
        case .preparing(let version, let phase):
            return ("arrow.down.circle", .systemBlue,
                    t("Обновляю до v\(version)", "Updating to v\(version)"),
                    phase, nil, nil, false, nil)
        case .failed(let message):
            return ("exclamationmark.triangle.fill", .systemRed,
                    t("Обновление не проверено", "Update check failed"),
                    message,
                    t("Повторить", "Retry"), #selector(updateButtonClicked(_:)), true,
                    t("Повторить проверку обновлений", "Retry update check"))
        }
    }

    @objc func updateButtonClicked(_ sender: NSButton) {
        switch updateState {
        case .available(let release): beginInAppUpdate(for: release)
        case .checking, .preparing: return
        case .upToDate, .failed: checkForUpdates()
        }
    }

    private func checkForUpdates() {
        updateTask?.cancel()
        updateState = .checking
        refresh(force: true)
        updateTask = Task { [weak self] in
            let outcome = await UpdateCheck.fetchLatest()
            guard !Task.isCancelled, let self else { return }
            self.updateTask = nil
            switch outcome {
            case .success(let release):
                self.settings.lastUpdateCheckAt = Date()
                self.settings.lastUpdateCheckSource = .manual
                self.settings.lastUpdateCheckVersion = release.version
                if isNewer(release.version, than: currentBundleVersion()) {
                    self.settings.lastUpdateCheckResult = .available
                    self.updateState = .available(release)
                } else {
                    self.settings.lastUpdateCheckResult = .upToDate
                    self.updateState = .upToDate(currentBundleVersion())
                }
            case .failure(let failure):
                self.settings.lastUpdateCheckAt = Date()
                self.settings.lastUpdateCheckSource = .manual
                self.settings.lastUpdateCheckResult = .failed
                self.updateState = .failed(self.localizedUpdateFailure(failure))
            }
            self.lastRuntimeFingerprint = ""
            self.refresh(force: true)
        }
    }

    private func localizedUpdateFailure(_ failure: UpdateCheckFailure) -> String {
        guard language == .russian else { return manualUpdateCheckFailureText(failure) }
        switch failure {
        case .network: return "Не удалось связаться с GitHub. Проверьте интернет."
        case .httpStatus(403): return "GitHub временно ограничил проверку обновлений."
        case .httpStatus(let code): return "GitHub вернул ошибку HTTP \(code)."
        case .unexpectedResponse: return "Не удалось проверить ответ GitHub."
        }
    }

    private func beginInAppUpdate(for release: GitHubRelease) {
        guard updateTask == nil else { return }
        let version = release.version
        updateState = .preparing(version: version, phase: t("Получаю манифест…", "Fetching manifest…"))
        refresh(force: true)
        updateTask = Task { [weak self] in
            guard let self else { return }
            do {
                let manifest = try await LexomorphUpdateInstaller.fetchManifest(expectedVersion: version)
                guard !Task.isCancelled else { return }
                self.updateState = .preparing(version: version, phase: self.t("Скачиваю и проверяю SHA-256…", "Downloading and verifying SHA-256…"))
                self.refresh(force: true)
                let prepared = try await LexomorphUpdateInstaller.prepare(manifest: manifest, tagName: release.tagName)
                guard !Task.isCancelled else {
                    try? FileManager.default.removeItem(at: prepared.workDirectory)
                    return
                }
                self.updateState = .preparing(version: version, phase: self.t("Запускаю установку…", "Starting installation…"))
                self.refresh(force: true)
                try self.launchPreparedUpdate(prepared)
            } catch {
                self.updateTask = nil
                let message = (error as? LexomorphUpdateInstallerError)?.message(language: self.language) ?? error.localizedDescription
                self.updateState = .failed(message)
                self.lastRuntimeFingerprint = ""
                self.refresh(force: true)
            }
        }
    }

    private func launchPreparedUpdate(_ prepared: PreparedLexomorphUpdate) throws {
        let statePath = try createPrivateUpdateProgressStateFile()
        let helperLog = try openPrivateUpdateHelperLog()
        let appURL = Bundle.main.bundleURL
        let backupURL = appURL.deletingLastPathComponent()
            .appendingPathComponent(".Lexomorph-update-backup-\(UUID().uuidString).app", isDirectory: true)
        let script = lexomorphDirectUpdateHelperScript(
            pid: getpid(),
            targetVersion: prepared.version,
            statePath: statePath,
            stagedAppPath: prepared.stagedAppURL.path,
            workDirectory: prepared.workDirectory.path,
            backupAppPath: backupURL.path,
            appPath: appURL.path,
            language: language
        )
        let helperPath = try writePrivateUpdateHelperScript(script)
        let progressAppPath: String
        do {
            progressAppPath = try launchUpdateProgressApp(statePath: statePath,
                                                          logPath: helperLog.path,
                                                          targetVersion: prepared.version)
        } catch {
            try? FileManager.default.removeItem(atPath: helperPath)
            try? FileManager.default.removeItem(atPath: statePath)
            try? FileManager.default.removeItem(at: prepared.workDirectory)
            helperLog.handle.closeFile()
            throw error
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [helperPath]
        process.environment = systemToolProcessEnvironment()
        process.standardOutput = helperLog.handle
        process.standardError = helperLog.handle
        do {
            try process.run()
        } catch {
            try? FileManager.default.removeItem(atPath: helperPath)
            try? FileManager.default.removeItem(atPath: statePath)
            try? FileManager.default.removeItem(at: prepared.workDirectory)
            try? FileManager.default.removeItem(atPath: progressAppPath)
            helperLog.handle.closeFile()
            throw error
        }

        updateTask = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            NSApp.terminate(nil)
        }
    }

    private func launchUpdateProgressApp(statePath: String, logPath: String, targetVersion: String) throws -> String {
        let sourceAppURL = Bundle.main.bundleURL
        guard sourceAppURL.pathExtension == "app",
              let executableName = Bundle.main.executableURL?.lastPathComponent else {
            throw posixError(EINVAL)
        }
        let progressAppURL = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
            .appendingPathComponent("\(UPDATE_PROGRESS_APP_PREFIX)\(UUID().uuidString).app", isDirectory: true)
        try FileManager.default.copyItem(at: sourceAppURL, to: progressAppURL)
        let executableURL = progressAppURL.appendingPathComponent("Contents/MacOS/\(executableName)")
        let process = Process()
        process.executableURL = executableURL
        process.arguments = [UPDATE_PROGRESS_ARGUMENT, statePath, logPath, targetVersion, progressAppURL.path]
        process.environment = systemToolProcessEnvironment()
        do {
            try process.run()
            return progressAppURL.path
        } catch {
            try? FileManager.default.removeItem(at: progressAppURL)
            throw error
        }
    }

    private func showError(title: String, detail: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = detail
        alert.addButton(withTitle: t("ОК", "OK"))
        alert.runModal()
    }
}
