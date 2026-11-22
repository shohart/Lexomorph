// Lexomorph — unified Control Panel & Settings state models.

import AppKit
import Foundation

enum ControlPanelServiceOperation: String, Sendable {
    case starting
    case restarting
    case stopping
    case applyingSettings
}

enum ControlPanelShortcutKind: Int {
    case dictation = 0
    case alternateCompletion = 1
    case history = 2
    case correction = 3
    case rewriteToggle = 4
    case rewriteStyle = 5
}

enum ControlPanelSection: Int, CaseIterable {
    case overview = 0
    case dictation = 1
    case text = 2
    case ai = 3
    case audio = 4
    case appearance = 5
    case system = 6
    case statistics = 7

    var identifier: String {
        switch self {
        case .overview: return "overview"
        case .dictation: return "dictation"
        case .text: return "text"
        case .ai: return "ai"
        case .audio: return "audio"
        case .appearance: return "appearance"
        case .system: return "system"
        case .statistics: return "statistics"
        }
    }

    init?(identifier: String) {
        switch identifier {
        case "overview": self = .overview
        case "dictation": self = .dictation
        case "text": self = .text
        case "ai": self = .ai
        case "audio": self = .audio
        case "appearance": self = .appearance
        case "system": self = .system
        case "statistics": self = .statistics
        default: return nil
        }
    }

    var symbolName: String {
        switch self {
        case .overview: return "house.fill"
        case .dictation: return "mic.fill"
        case .text: return "text.alignleft"
        case .ai: return "wand.and.stars"
        case .audio: return "speaker.wave.2.fill"
        case .appearance: return "paintbrush.fill"
        case .system: return "gearshape.2.fill"
        case .statistics: return "chart.bar.xaxis"
        }
    }
}

enum AISubsection: Int, CaseIterable {
    case correction = 0
    case rewrite = 1
    case punctuation = 2
    case shortcutsAndHardware = 3
}

enum StatisticsPeriod: Int, CaseIterable {
    case today = 0
    case last7Days = 1
    case last30Days = 2
    case allTime = 3
}

enum StatisticsChartMetric: Int, CaseIterable {
    case characters = 0
    case dictations = 1
}

struct ControlPanelSettingsDraft: Equatable {
    var speechModelProfile: SpeechModelProfile
    var triggerMode: TriggerMode
    var dictationLanguage: DictationLanguage
    var dictationHotkey: HotkeyChoice
    var alternateCompletionHotkey: HotkeyChoice
    var historyHotkey: HotkeyChoice
    var correctionHotkey: HotkeyChoice
    var rewriteToggleHotkey: HotkeyChoice
    var rewriteStyleHotkey: HotkeyChoice
    var primaryCompletionBehavior: DictationCompletionBehavior
    var alternateCompletionEnabled: Bool
    var enterDelayMilliseconds: Int
    var inputDevicePreference: String
    var showRecordingWaveform: Bool
    var recordingColor: RecordingHUDAccentColor
    var transcribingColor: RecordingHUDAccentColor
    var correctingColor: RecordingHUDAccentColor
    var backgroundStyle: RecordingHUDBackgroundStyle
    var hudSize: RecordingHUDSize
    var hudDisplayMode: RecordingHUDDisplayMode
    var pasteSuffix: PasteSuffix
    var recentTranscriptLimit: RecentTranscriptLimit
    var normalizeNumbersToDigits: Bool
    var removeFillerWords: Bool
    var removeFinalPeriod: Bool
    var enabledFillerPresetKeys: Set<String>
    var customFillerWords: [String]
    var disabledCustomFillerWords: Set<String>
    var autoStopOnSilenceEnabled: Bool
    var autoStopSilenceSeconds: Int
    var muteWhileRecording: Bool
    var playFeedbackSounds: Bool
    var checkForUpdates: Bool
    var llmUseGPU: Bool
    var autoLearnVocabularyEnabled: Bool
    var asrHotwordsEnabled: Bool
    var asrHotwordsStrength: AsrHotwordsStrength
    var textPostprocessingMode: TextPostprocessingMode
    var llmEngineBackend: LLMEngineBackend
    var llmCustomBaseURL: String
    var llmCustomAPIKey: String
    var llmCustomModelName: String
    var llmUseSystemProxy: Bool
    var correctionModel: BundledLLMModel
    var correctionSystemPrompt: String
    var rewriteEnabled: Bool
    var punctuationRestorationEnabled: Bool
    var punctuationModel: PunctuationModel
    var rewriteStyleID: String
    var customRewriteStyles: [CustomRewriteStyle]
    var customRewriteStylesBaseline: [CustomRewriteStyle]
    var rewriteBundledModel: BundledLLMModel
    var rewriteSystemPrompts: [String: String]
    var rewriteSystemPromptsBaseline: [String: String] = [:]
    var rewriteEngineBackend: LLMEngineBackend
    var rewriteCustomBaseURL: String
    var rewriteCustomAPIKey: String
    var rewriteCustomModelName: String

    init(settings: Settings) {
        speechModelProfile = settings.speechModelProfile
        triggerMode = settings.triggerMode
        dictationLanguage = settings.dictationLanguage
        dictationHotkey = settings.configuredHotkey
        alternateCompletionHotkey = settings.configuredEnterHotkey
        historyHotkey = settings.configuredHistoryHotkey
        correctionHotkey = settings.configuredCorrectionHotkey
        rewriteToggleHotkey = settings.configuredRewriteToggleHotkey
        rewriteStyleHotkey = settings.configuredRewriteStyleHotkey
        primaryCompletionBehavior = settings.primaryCompletionBehavior
        alternateCompletionEnabled = settings.alternateCompletionEnabled
        enterDelayMilliseconds = settings.enterDelayMilliseconds
        let savedInput = settings.inputDevice
        inputDevicePreference = audioInputDevice(matching: savedInput)?.uid ?? savedInput
        showRecordingWaveform = settings.showRecordingWaveform
        recordingColor = settings.recordingHUDRecordingColor
        transcribingColor = settings.recordingHUDTranscribingColor
        correctingColor = settings.recordingHUDCorrectingColor
        backgroundStyle = settings.recordingHUDBackgroundStyle
        hudSize = settings.recordingHUDSize
        hudDisplayMode = settings.recordingHUDDisplayMode
        pasteSuffix = settings.pasteSuffix
        recentTranscriptLimit = settings.recentTranscriptLimit
        normalizeNumbersToDigits = settings.normalizeNumbersToDigits
        removeFillerWords = settings.removeFillerWords
        removeFinalPeriod = settings.removeFinalPeriod
        enabledFillerPresetKeys = settings.enabledFillerPresetKeys
        customFillerWords = settings.customFillerWords
        disabledCustomFillerWords = settings.disabledCustomFillerWords
        autoStopOnSilenceEnabled = settings.autoStopOnSilenceEnabled
        autoStopSilenceSeconds = settings.autoStopSilenceSeconds
        muteWhileRecording = settings.muteWhileRecording
        playFeedbackSounds = settings.playFeedbackSounds
        checkForUpdates = settings.checkForUpdates
        llmUseGPU = settings.llmUseGPU
        autoLearnVocabularyEnabled = settings.autoLearnVocabularyEnabled
        asrHotwordsEnabled = settings.asrHotwordsEnabled
        asrHotwordsStrength = settings.asrHotwordsStrength
        textPostprocessingMode = settings.textPostprocessingMode
        llmEngineBackend = settings.llmEngineBackend
        llmCustomBaseURL = settings.llmCustomBaseURL
        llmCustomAPIKey = settings.llmCustomAPIKey
        llmCustomModelName = settings.llmCustomModelName
        llmUseSystemProxy = settings.llmUseSystemProxy
        correctionModel = settings.correctionBundledModel
        correctionSystemPrompt = {
            let override = settings.correctionSystemPromptOverride
            return override.isEmpty
                ? LLMCorrectionPrompt.systemPrompt(vocabulary: [], model: settings.correctionBundledModel)
                : override
        }()
        rewriteEnabled = settings.rewriteEnabled
        punctuationRestorationEnabled = settings.punctuationRestorationEnabled
        punctuationModel = settings.punctuationModel
        rewriteStyleID = settings.rewriteStyleID
        customRewriteStyles = settings.customRewriteStyles
        customRewriteStylesBaseline = customRewriteStyles
        rewriteBundledModel = settings.rewriteBundledModel
        rewriteSystemPrompts = {
            var map: [String: String] = [:]
            for style in RewriteStyle.allCases {
                let override = settings.rewriteSystemPromptOverride(for: style)
                map[style.rawValue] = override.isEmpty
                    ? LLMRewritePrompt.systemPrompt(style: style)
                    : override
            }
            for custom in settings.customRewriteStyles {
                let override = settings.rewriteSystemPromptOverride(forStyleID: custom.id)
                map[custom.id] = override.isEmpty
                    ? LLMRewritePrompt.systemPrompt(custom: custom)
                    : override
            }
            return map
        }()
        rewriteSystemPromptsBaseline = rewriteSystemPrompts
        rewriteEngineBackend = settings.rewriteEngineBackend
        rewriteCustomBaseURL = settings.rewriteCustomBaseURL
        rewriteCustomAPIKey = settings.rewriteCustomAPIKey
        rewriteCustomModelName = settings.rewriteCustomModelName
    }
}

func hotkeysConflict(_ lhs: HotkeyChoice, _ rhs: HotkeyChoice) -> Bool {
    lhs.keycode == rhs.keycode && lhs.requiredModifiers == rhs.requiredModifiers
}

func hotkeyIsModifierPrefix(_ prefix: HotkeyChoice,
                            of shortcut: HotkeyChoice) -> Bool {
    guard prefix.isModifier,
          prefix.requiredModifiers.isEmpty,
          let prefixMask = prefix.modifierFlag else { return false }
    return shortcut.requiredModifiers.contains(prefixMask)
}

enum ControlPanelUpdateState: Equatable, Sendable {
    case checking
    case upToDate(String)
    case available(GitHubRelease)
    case preparing(version: String, phase: String)
    case failed(String)
}

enum LLMModelDownloadState: Equatable {
    case idle
    case downloading
    case failed(String)
}

/// Flipped NSView so NSScrollView documents naturally anchor to the top-left
/// and scroll offsets stay intuitive.
final class FlippedView: NSView {
    override var isFlipped: Bool { true }
}

/// NSButton's target must be an NSObject; this wraps a Swift closure that
/// receives the clicked button's tag.
@MainActor
final class SwatchAction: NSObject {
    nonisolated(unsafe) static var associationKey: UInt8 = 0
    let handler: (Int) -> Void
    init(handler: @escaping (Int) -> Void) { self.handler = handler }
    @objc func swatchClicked(_ sender: NSButton) { handler(sender.tag) }
}

extension NSColor {
    /// "#RRGGBB" → NSColor (sRGB); falls back to gray on malformed input.
    convenience init(hexString: String) {
        var value: UInt64 = 0
        let cleaned = hexString.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "#", with: "")
        if Scanner(string: cleaned).scanHexInt64(&value), cleaned.count == 6 {
            self.init(srgbRed: CGFloat((value >> 16) & 0xFF) / 255.0,
                      green: CGFloat((value >> 8) & 0xFF) / 255.0,
                      blue: CGFloat(value & 0xFF) / 255.0,
                      alpha: 1)
        } else {
            self.init(srgbRed: 0.6, green: 0.6, blue: 0.6, alpha: 1)
        }
    }
}
