// Lexomorph — startup hardware & capability probing.
//
// Inspects the Mac's CPU, RAM, Metal GPUs, Vulkan LLM devices, helper binaries,
// and Vulkan shader corpus once per process (warmed asynchronously at launch).
// UI panels use this snapshot to disable hardware-incompatible options and
// display clear, actionable banners explaining why a feature is unavailable.

import Foundation
import Metal

struct HardwareGPUInfo: Equatable, Sendable {
    let name: String
    let isLowPower: Bool
    let hasUnifiedMemory: Bool
    let recommendedMemoryGB: Double
}

enum CapabilityAvailability: Equatable, Sendable {
    case available(detail: String)
    case unavailable(reason: String)

    var isAvailable: Bool {
        if case .available = self { return true }
        return false
    }

    var message: String {
        switch self {
        case .available(let detail): return detail
        case .unavailable(let reason): return reason
        }
    }
}

enum ModelHardwareCompatibility: Equatable, Sendable {
    case recommended
    case cpuOnlyWarning(reason: String)
    case unsupported(reason: String)

    var isSupported: Bool {
        if case .unsupported = self { return false }
        return true
    }
}

struct HardwareProfile: Equatable, Sendable {
    let cpuModel: String
    let cpuCores: Int
    let architecture: String
    let physicalMemoryGB: Int
    let metalGPUs: [HardwareGPUInfo]
    let vulkanDevices: [String]
    let llmHelperAvailable: Bool
    let vulkanShadersAvailable: Bool
    let onnxHelperAvailable: Bool

    /// Minimum RAM (in GB) required to run a bundled model safely alongside
    /// the ONNX speech model and macOS without catastrophic swap thrashing.
    static func minimumRAMGB(for model: BundledLLMModel) -> Int {
        switch model {
        case .voiceScribe, .loqira, .vanilla08b:
            return 6
        case .lfm25, .ministral3b, .phi4mini, .ruAdapt4b, .qvikhr4b, .qwen35_4b:
            return 8
        case .yandexGPT, .gemma4e4b, .qwen35_9b:
            return 12
        }
    }

    static func isLargeModel(_ model: BundledLLMModel) -> Bool {
        minimumRAMGB(for: model) >= 12
    }

    /// Maximum Metal GPU working set reported by the system, or nil if Metal
    /// returned no devices.
    var maxMetalGPUMemoryGB: Double? {
        metalGPUs.map(\.recommendedMemoryGB).max()
    }

    var hasDiscreteMetalGPU: Bool {
        metalGPUs.contains { !$0.isLowPower }
    }

    var vulkanGPUAvailable: Bool {
        vulkanGPUStatus(language: .english).isAvailable
    }

    var localLLMAvailable: Bool {
        localLLMStatus(language: .english).isAvailable
    }

    func vulkanGPUStatus(language: InterfaceLanguage) -> CapabilityAvailability {
        if !llmHelperAvailable {
            return .unavailable(reason: localizedText(
                "Модуль локальных LLM (LexomorphLLMHost) не найден в этой сборке. Локальное ускорение на GPU недоступно.",
                "The local LLM helper (LexomorphLLMHost) is missing in this build. Local GPU acceleration is unavailable.",
                language: language
            ))
        }
        if !vulkanShadersAvailable {
            return .unavailable(reason: localizedText(
                "В пакете приложения отсутствуют шейдеры Vulkan — ускорение на GPU отключено, модели работают на CPU.",
                "Vulkan shaders are missing from the app bundle — GPU acceleration is disabled and local models run on CPU.",
                language: language
            ))
        }
        if vulkanDevices.isEmpty {
            return .unavailable(reason: localizedText(
                "На этом компьютере не обнаружена совместимая видеокарта с поддержкой Vulkan. Ускорение локальных моделей на GPU недоступно — обработка выполняется на CPU или через свой сервер.",
                "No compatible Vulkan GPU was detected on this computer. Local LLM GPU acceleration is unavailable — processing runs on CPU or via a custom server.",
                language: language
            ))
        }
        if let maxVRAM = maxMetalGPUMemoryGB, maxVRAM > 0, maxVRAM < 2.0 {
            let vramText = String(format: "%.1f", maxVRAM)
            return .unavailable(reason: localizedText(
                "Обнаруженной видеопамяти (\(vramText) ГБ) недостаточно для запуска локальных LLM на GPU (требуется от 2 ГБ). Обработка выполняется на CPU.",
                "Detected GPU memory (\(vramText) GB) is below the 2 GB minimum required for local LLM GPU acceleration. Processing runs on CPU.",
                language: language
            ))
        }
        let list = vulkanDevices.joined(separator: ", ")
        if let maxVRAM = maxMetalGPUMemoryGB, maxVRAM >= 2.0 {
            let vramGB = Int(maxVRAM.rounded())
            return .available(detail: "\(list) (~\(vramGB) \(localizedText("ГБ", "GB", language: language)))")
        }
        return .available(detail: list)
    }

    func localLLMStatus(language: InterfaceLanguage) -> CapabilityAvailability {
        if !llmHelperAvailable {
            return .unavailable(reason: localizedText(
                "Локальный LLM-движок отсутствует в этой сборке. Вы можете использовать «Свой сервер» (OpenAI-совместимый API).",
                "The bundled local LLM engine is missing from this build. Use 'Custom server' (OpenAI-compatible API) instead.",
                language: language
            ))
        }
        if physicalMemoryGB < 6 {
            return .unavailable(reason: localizedText(
                "Недостаточно оперативной памяти (\(physicalMemoryGB) ГБ, требуется от 6 ГБ) для запуска локальных LLM-моделей. Используйте «Свой сервер».",
                "Insufficient RAM (\(physicalMemoryGB) GB, minimum 6 GB required) to run local LLM models. Use 'Custom server' instead.",
                language: language
            ))
        }
        return .available(detail: localizedText(
            "\(physicalMemoryGB) ГБ ОЗУ",
            "\(physicalMemoryGB) GB RAM",
            language: language
        ))
    }

    func modelCompatibility(for model: BundledLLMModel, language: InterfaceLanguage) -> ModelHardwareCompatibility {
        if case .unavailable(let reason) = localLLMStatus(language: language) {
            return .unsupported(reason: reason)
        }
        let requiredRAM = Self.minimumRAMGB(for: model)
        if physicalMemoryGB < requiredRAM {
            return .unsupported(reason: localizedText(
                "Для модели \(model.displayName) требуется от \(requiredRAM) ГБ ОЗУ (на этом Mac: \(physicalMemoryGB) ГБ). Выберите более лёгкую модель или «Свой сервер».",
                "\(model.displayName) requires at least \(requiredRAM) GB RAM (this Mac has \(physicalMemoryGB) GB). Choose a lighter model or 'Custom server'.",
                language: language
            ))
        }
        if Self.isLargeModel(model), !vulkanGPUAvailable {
            return .cpuOnlyWarning(reason: localizedText(
                "На этом Mac нет совместимого Vulkan GPU — крупная модель \(model.displayName) будет работать на CPU заметно медленнее. Для быстрого отклика подойдут лёгкие модели (VoiceScribe / 3–4B) или свой сервер.",
                "No compatible Vulkan GPU was detected — the large \(model.displayName) model will run noticeably slower on CPU. For faster responses, consider lighter models or a custom server.",
                language: language
            ))
        }
        return .recommended
    }

    func punctuationStatus(language: InterfaceLanguage) -> CapabilityAvailability {
        if physicalMemoryGB < 6 {
            return .unavailable(reason: localizedText(
                "Недостаточно оперативной памяти (\(physicalMemoryGB) ГБ, требуется от 6 ГБ) для локальной модели восстановления пунктуации.",
                "Insufficient RAM (\(physicalMemoryGB) GB, minimum 6 GB required) for the local punctuation restoration model.",
                language: language
            ))
        }
        return .available(detail: localizedText("CPU · готово", "CPU · ready", language: language))
    }

    var logSummary: String {
        let gpuDesc: String
        if !vulkanDevices.isEmpty {
            gpuDesc = "Vulkan=[\(vulkanDevices.joined(separator: ", "))]"
        } else if !metalGPUs.isEmpty {
            let names = metalGPUs.map { "\($0.name)(\(String(format: "%.1f", $0.recommendedMemoryGB))GB)" }.joined(separator: ", ")
            gpuDesc = "Vulkan=none Metal=[\(names)]"
        } else {
            gpuDesc = "GPU=none"
        }
        return "Hardware probe: \(cpuModel) (\(architecture), \(cpuCores) cores, \(physicalMemoryGB) GB RAM), \(gpuDesc), llmHelper=\(llmHelperAvailable), shaders=\(vulkanShadersAvailable), onnxHelper=\(onnxHelperAvailable)"
    }
}

final class HardwareCapabilities: @unchecked Sendable {
    static let shared = HardwareCapabilities()

    private let lock = NSLock()
    private var cachedProfile: HardwareProfile?
    private var warmingUp = false

    /// Returns the cached hardware profile, probing synchronously on first access
    /// if `warmUpAsync` has not finished yet.
    func current() -> HardwareProfile {
        lock.lock()
        if let cached = cachedProfile {
            lock.unlock()
            return cached
        }
        lock.unlock()

        let probed = Self.probeNow()
        lock.lock()
        if cachedProfile == nil {
            cachedProfile = probed
        }
        let result = cachedProfile!
        lock.unlock()
        return result
    }

    /// Probes hardware once on a background utility queue at application launch
    /// so UI never stalls, logs the hardware summary, and invokes `onComplete`
    /// on the main queue when finished.
    func warmUpAsync(onComplete: (@MainActor @Sendable (HardwareProfile) -> Void)? = nil) {
        lock.lock()
        if let existing = cachedProfile {
            lock.unlock()
            if let onComplete {
                Task { @MainActor in onComplete(existing) }
            }
            return
        }
        let shouldStart = !warmingUp
        warmingUp = true
        lock.unlock()

        guard shouldStart else { return }
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let profile = Self.probeNow()
            log(profile.logSummary)
            self?.lock.lock()
            self?.cachedProfile = profile
            self?.warmingUp = false
            self?.lock.unlock()
            if let onComplete {
                Task { @MainActor in onComplete(profile) }
            }
        }
    }

    private static func probeNow() -> HardwareProfile {
        let cpuModel = readSysctlString("machdep.cpu.brand_string") ?? readSysctlString("hw.model") ?? "Mac"
        let cores = ProcessInfo.processInfo.processorCount
        #if arch(arm64)
        let arch = "arm64"
        #else
        let arch = "x86_64"
        #endif
        let ramBytes = ProcessInfo.processInfo.physicalMemory
        let ramGB = max(1, Int((Double(ramBytes) / 1_073_741_824.0).rounded()))

        let metalDevices = MTLCopyAllDevices().map { dev in
            HardwareGPUInfo(
                name: dev.name,
                isLowPower: dev.isLowPower,
                hasUnifiedMemory: dev.hasUnifiedMemory,
                recommendedMemoryGB: Double(dev.recommendedMaxWorkingSetSize) / 1_073_741_824.0
            )
        }

        let llmHelperURL = LLMHostProcess.resolvedHelperBinaryURL()
        let llmHelperAvailable = llmHelperURL.map { FileManager.default.isExecutableFile(atPath: $0.path) } ?? false
        let vulkanShadersAvailable = checkVulkanShadersAvailable(helperURL: llmHelperURL)
        let vulkanDevices = llmHelperAvailable ? LLMGPUProbe.shared.devices() : []
        let onnxHelperAvailable = checkOnnxHelperAvailable()

        return HardwareProfile(
            cpuModel: cpuModel,
            cpuCores: cores,
            architecture: arch,
            physicalMemoryGB: ramGB,
            metalGPUs: metalDevices,
            vulkanDevices: vulkanDevices,
            llmHelperAvailable: llmHelperAvailable,
            vulkanShadersAvailable: vulkanShadersAvailable,
            onnxHelperAvailable: onnxHelperAvailable
        )
    }

    private static func readSysctlString(_ name: String) -> String? {
        var size = 0
        guard sysctlbyname(name, nil, &size, nil, 0) == 0, size > 0 else { return nil }
        var buffer = [CChar](repeating: 0, count: size)
        guard sysctlbyname(name, &buffer, &size, nil, 0) == 0 else { return nil }
        let bytes = buffer.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }
        let result = String(decoding: bytes, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return result.isEmpty ? nil : result
    }

    private static func checkVulkanShadersAvailable(helperURL: URL?) -> Bool {
        let fm = FileManager.default
        if let resourceURL = Bundle.main.resourceURL {
            let bundled = resourceURL
                .appendingPathComponent("llama-vulkan-shaders", isDirectory: true)
                .appendingPathComponent("matmul_f32_f32.spv", isDirectory: false)
            if fm.fileExists(atPath: bundled.path) { return true }
        }
        if let helperURL {
            // App bundle layout: Contents/Helpers/LexomorphLLMHost -> Contents/Resources/llama-vulkan-shaders
            let contentsURL = helperURL.deletingLastPathComponent().deletingLastPathComponent()
            let bundled = contentsURL
                .appendingPathComponent("Resources", isDirectory: true)
                .appendingPathComponent("llama-vulkan-shaders", isDirectory: true)
                .appendingPathComponent("matmul_f32_f32.spv", isDirectory: false)
            if fm.fileExists(atPath: bundled.path) { return true }

            // Dev SwiftPM build tree layout: swift/.build/{debug,release}/LexomorphLLMHost
            let repoRoot = helperURL
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
            let devShaders = repoRoot
                .appendingPathComponent("swift/Sources/llama_cpp_host/upstream/ggml-vulkan/vulkan-shaders/matmul_f32_f32.spv", isDirectory: false)
            if fm.fileExists(atPath: devShaders.path) { return true }
        }
        return false
    }

    private static func checkOnnxHelperAvailable() -> Bool {
        let fm = FileManager.default
        let exeDir = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath().deletingLastPathComponent()
        let contentsDir = exeDir.deletingLastPathComponent()
        let candidates = [
            contentsDir.appendingPathComponent("Helpers/LexomorphOnnxHost", isDirectory: false),
            exeDir.appendingPathComponent("LexomorphOnnxHost", isDirectory: false),
            Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/LexomorphOnnxHost", isDirectory: false),
        ]
        return candidates.contains { fm.isExecutableFile(atPath: $0.path) }
    }
}
