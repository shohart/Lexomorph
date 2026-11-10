// Lexomorph 1.0 migration from the pre-1.0 "SuperDictate" identifiers.
//
// Owner decision: the product, bundle (/Applications/Lexomorph.app), bundle
// id (com.local.lexomorph), LaunchAgent label, defaults domain, Application
// Support folder and Keychain service were all renamed. A new bundle id is a
// new app for macOS, so the first launch copies the user's state forward:
//
//   * UserDefaults: every key of the legacy domain is copied into the new
//     domain unless the new domain already has that key (never overwrites).
//   * Application Support/SuperDictate -> Application Support/Lexomorph by
//     APFS clone (clonefile(2)): multi-gigabyte models take no second copy.
//     Falls back to a regular copy when cloning is unavailable.
//   * Keychain: the sync token is read under the legacy service and written
//     under the new one. This step runs only in the background agent, off the
//     main thread, and is attempted exactly once (a Keychain dialog must not
//     block or repeat at launch).
//   * A marker file in the new data directory records the migration; once it
//     exists the whole thing is a no-op.
//
// The legacy data, defaults and Keychain item are never modified or deleted:
// they are the rollback path. This file is the ONLY place in the app that
// spells the legacy identifiers.

import Foundation
import AppKit
import Darwin

let LEGACY_CORRECTIONS_FILE_EXTENSION = "superdictate-corrections"

enum LegacyIdentifiers {
    static let bundleIdentifier = "com.local.superdictate"
    static let defaultsDomain = "com.local.superdictate"
    static let appSupportDirName = "SuperDictate"
    static let keychainService = "com.local.superdictate.vocab-sync"
    static let agentLabel = "com.local.superdictate.agent"
    static let installedBundlePath = "/Applications/SuperDictate.app"
}

struct LegacyMigrationConfig {
    var legacyDefaultsDomain: String
    /// Domain that `target` stores into; compared to find keys already set.
    var newDefaultsDomain: String
    var target: UserDefaults
    var legacySupportDir: URL
    var newSupportDir: URL
    var lockFileURL: URL
    var appVersion: String
    var lockTimeoutSeconds: TimeInterval = 20
    var now: Date = Date()
    /// Reads the legacy preferences domain; replaced by self-tests.
    var readLegacyDefaults: (String) -> [String: Any]? = { UserDefaults.standard.persistentDomain(forName: $0) }

    /// Real configuration. nil unless this is the production bundle: test
    /// bundles and unbundled `swift build` binaries must never migrate.
    static func production() -> LegacyMigrationConfig? {
        guard Bundle.main.bundleIdentifier == PRODUCTION_BUNDLE_IDENTIFIER else { return nil }
        guard let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            return nil
        }
        return LegacyMigrationConfig(
            legacyDefaultsDomain: LegacyIdentifiers.defaultsDomain,
            newDefaultsDomain: PRODUCTION_BUNDLE_IDENTIFIER,
            target: .standard,
            legacySupportDir: base.appendingPathComponent(LegacyIdentifiers.appSupportDirName, isDirectory: true),
            newSupportDir: base.appendingPathComponent(APP_SUPPORT_DIR_NAME, isDirectory: true),
            lockFileURL: base.appendingPathComponent(".lexomorph-migration.lock", isDirectory: false),
            appVersion: currentBundleVersion()
        )
    }
}

struct LegacyMigrationMarker: Codable, Equatable {
    var schema: Int = 1
    var migratedAt: String
    var appVersion: String
    var legacyFound: Bool
    var defaultsCopied: Int
    var defaultsKept: Int
    var pathsRewritten: Int
    var filesCloned: [String]
    var filesSkipped: [String]
    /// pending | attempted | done | exists | absent | failed | skipped
    var keychain: String
    var noticeShown: Bool
}

struct LegacyMigrationReport: Equatable {
    var alreadyMigrated = false
    var lockTimedOut = false
    var legacyFound = false
    var defaultsCopied = 0
    var defaultsKept = 0
    var pathsRewritten = 0
    var filesCloned: [String] = []
    var filesSkipped: [String] = []
}

enum LegacyMigration {
    static let markerFileName = ".migrated-from-superdictate.json"
    static let emailDefaultsKey = "vocabulary_sync_email_v1"
    /// Run-state keys that must not travel: they describe the old process.
    static let transientDefaultsKeys: Set<String> = ["active_run_marker"]

    // MARK: Entry points

    /// Defaults + files. Fast, no Keychain, safe on the main thread before
    /// any delegate (and therefore `Settings.shared`) is created.
    @discardableResult
    static func run(_ config: LegacyMigrationConfig) -> LegacyMigrationReport {
        var report = LegacyMigrationReport()
        let fm = FileManager.default
        try? fm.createDirectory(at: config.lockFileURL.deletingLastPathComponent(),
                                withIntermediateDirectories: true)
        guard let lock = acquireLock(config.lockFileURL, timeout: config.lockTimeoutSeconds) else {
            // Proceed without migrating rather than hang the launch; the
            // next launch retries because no marker was written.
            report.lockTimedOut = true
            return report
        }
        defer { releaseLock(lock) }
        if readMarker(config) != nil {
            report.alreadyMigrated = true
            return report
        }

        let legacyDefaults = config.readLegacyDefaults(config.legacyDefaultsDomain) ?? [:]
        var isDirectory: ObjCBool = false
        let legacyDirExists = fm.fileExists(atPath: config.legacySupportDir.path, isDirectory: &isDirectory)
            && isDirectory.boolValue
        report.legacyFound = !legacyDefaults.isEmpty || legacyDirExists

        if report.legacyFound {
            migrateDefaults(legacyDefaults, config, &report)
            if legacyDirExists { migrateSupportDirectory(config, &report) }
        }

        try? fm.createDirectory(at: config.newSupportDir, withIntermediateDirectories: true,
                                attributes: [.posixPermissions: 0o700])
        let marker = LegacyMigrationMarker(
            migratedAt: ISO8601DateFormatter().string(from: config.now),
            appVersion: config.appVersion,
            legacyFound: report.legacyFound,
            defaultsCopied: report.defaultsCopied,
            defaultsKept: report.defaultsKept,
            pathsRewritten: report.pathsRewritten,
            filesCloned: report.filesCloned,
            filesSkipped: report.filesSkipped,
            keychain: report.legacyFound ? "pending" : "skipped",
            noticeShown: !report.legacyFound
        )
        writeMarker(marker, config)
        return report
    }

    /// Keychain token: legacy service -> new service. Attempted once, ever.
    /// Call from the agent on a background queue (a Keychain dialog may block
    /// until answered). Failures are final and never block anything.
    @discardableResult
    static func migrateKeychain(_ config: LegacyMigrationConfig,
                                legacyStore: any VocabularySyncTokenStore,
                                newStore: any VocabularySyncTokenStore) -> String {
        guard let lock = acquireLock(config.lockFileURL, timeout: config.lockTimeoutSeconds) else {
            return "locked"
        }
        guard var marker = readMarker(config) else { releaseLock(lock); return "no-marker" }
        guard marker.keychain == "pending" else {
            releaseLock(lock)
            return marker.keychain
        }
        marker.keychain = "attempted"
        writeMarker(marker, config)
        releaseLock(lock)   // never hold the file lock across a Keychain dialog

        let email = (config.target.string(forKey: emailDefaultsKey) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        var outcome = "absent"
        if !email.isEmpty {
            if newStore.token(for: email) != nil {
                outcome = "exists"
            } else if let token = legacyStore.token(for: email) {
                do {
                    try newStore.setToken(token, for: email)
                    outcome = "done"
                } catch {
                    outcome = "failed"
                }
            }
        }
        if let lock2 = acquireLock(config.lockFileURL, timeout: config.lockTimeoutSeconds) {
            if var current = readMarker(config) {
                current.keychain = outcome
                writeMarker(current, config)
            }
            releaseLock(lock2)
        }
        return outcome
    }

    /// True exactly once, and only when legacy data was migrated: the caller
    /// shows the one-time "SuperDictate is now Lexomorph" notice.
    static func consumeFirstRunNotice(_ config: LegacyMigrationConfig) -> Bool {
        guard let lock = acquireLock(config.lockFileURL, timeout: config.lockTimeoutSeconds) else { return false }
        defer { releaseLock(lock) }
        guard var marker = readMarker(config), marker.legacyFound, !marker.noticeShown else { return false }
        marker.noticeShown = true
        writeMarker(marker, config)
        return true
    }

    // MARK: UserDefaults

    static func migrateDefaults(_ legacy: [String: Any], _ config: LegacyMigrationConfig,
                                _ report: inout LegacyMigrationReport) {
        let existing = config.target.persistentDomain(forName: config.newDefaultsDomain) ?? [:]
        for key in legacy.keys.sorted() where !transientDefaultsKeys.contains(key) {
            if existing[key] != nil {
                report.defaultsKept += 1
                continue
            }
            var rewrites = 0
            let value = rewritePaths(legacy[key]!, from: config.legacySupportDir.path,
                                     to: config.newSupportDir.path, count: &rewrites)
            config.target.set(value, forKey: key)
            report.defaultsCopied += 1
            report.pathsRewritten += rewrites
        }
        config.target.synchronize()
    }

    /// Absolute paths that pointed into the legacy data folder now point at
    /// the new one, so the app does not keep reading the old copy.
    static func rewritePaths(_ value: Any, from legacy: String, to new: String, count: inout Int) -> Any {
        if let string = value as? String {
            if string == legacy || string.hasPrefix(legacy + "/") {
                count += 1
                return new + String(string.dropFirst(legacy.count))
            }
            return string
        }
        if let array = value as? [Any] {
            return array.map { rewritePaths($0, from: legacy, to: new, count: &count) }
        }
        if let dictionary = value as? [String: Any] {
            var out: [String: Any] = [:]
            for (key, item) in dictionary { out[key] = rewritePaths(item, from: legacy, to: new, count: &count) }
            return out
        }
        return value
    }

    // MARK: Application Support

    static func isExcludedFromMigration(_ name: String) -> Bool {
        name.hasPrefix("AgentStatus") || name.hasSuffix(".pid") || name.hasSuffix(".lock")
            || name.hasPrefix(".migrating-") || name == ".DS_Store" || name == markerFileName
    }

    static func migrateSupportDirectory(_ config: LegacyMigrationConfig, _ report: inout LegacyMigrationReport) {
        let fm = FileManager.default
        do {
            try fm.createDirectory(at: config.newSupportDir, withIntermediateDirectories: true,
                                   attributes: [.posixPermissions: 0o700])
        } catch {
            report.filesSkipped.append("(cannot create \(config.newSupportDir.lastPathComponent))")
            return
        }
        // Leftovers of an interrupted run.
        for stale in (try? fm.contentsOfDirectory(atPath: config.newSupportDir.path)) ?? []
        where stale.hasPrefix(".migrating-") {
            try? fm.removeItem(at: config.newSupportDir.appendingPathComponent(stale))
        }
        let children = ((try? fm.contentsOfDirectory(atPath: config.legacySupportDir.path)) ?? []).sorted()
        for name in children {
            if isExcludedFromMigration(name) { continue }
            let destination = config.newSupportDir.appendingPathComponent(name)
            if fm.fileExists(atPath: destination.path)
                || (try? destination.checkResourceIsReachable()) == true {
                report.filesSkipped.append(name)
                continue
            }
            // A SQLite side file only belongs to the database it was written
            // with: never attach the legacy -wal/-shm to a different database.
            if let base = sqliteBaseName(of: name),
               fm.fileExists(atPath: config.newSupportDir.appendingPathComponent(base).path),
               !report.filesCloned.contains(base) {
                report.filesSkipped.append(name)
                continue
            }
            do {
                try cloneItem(from: config.legacySupportDir.appendingPathComponent(name), to: destination)
                report.filesCloned.append(name)
            } catch {
                report.filesSkipped.append(name)
            }
        }
    }

    private static func sqliteBaseName(of name: String) -> String? {
        for suffix in ["-wal", "-shm", "-journal"] where name.hasSuffix(suffix) {
            return String(name.dropLast(suffix.count))
        }
        return nil
    }

    /// Copy-on-write clone to a hidden temporary name, then an atomic rename;
    /// a regular copy when the volume cannot clone.
    static func cloneItem(from source: URL, to destination: URL) throws {
        let fm = FileManager.default
        let temporary = destination.deletingLastPathComponent()
            .appendingPathComponent(".migrating-\(UUID().uuidString)-\(destination.lastPathComponent)")
        defer { try? fm.removeItem(at: temporary) }
        if clonefile(source.path, temporary.path, 0x0001 /* CLONE_NOFOLLOW */) != 0 {
            try? fm.removeItem(at: temporary)
            try fm.copyItem(at: source, to: temporary)
        }
        try fm.moveItem(at: temporary, to: destination)
    }

    // MARK: Marker

    static func markerURL(_ config: LegacyMigrationConfig) -> URL {
        config.newSupportDir.appendingPathComponent(markerFileName, isDirectory: false)
    }

    static func readMarker(_ config: LegacyMigrationConfig) -> LegacyMigrationMarker? {
        guard let data = try? Data(contentsOf: markerURL(config)) else { return nil }
        return try? JSONDecoder().decode(LegacyMigrationMarker.self, from: data)
    }

    static func writeMarker(_ marker: LegacyMigrationMarker, _ config: LegacyMigrationConfig) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? encoder.encode(marker) else { return }
        try? data.write(to: markerURL(config), options: [.atomic])
    }

    // MARK: Lock

    static func acquireLock(_ url: URL, timeout: TimeInterval) -> Int32? {
        let descriptor = open(url.path, O_CREAT | O_RDWR, 0o600)
        guard descriptor >= 0 else { return nil }
        let deadline = Date().addingTimeInterval(timeout)
        while true {
            if flock(descriptor, LOCK_EX | LOCK_NB) == 0 { return descriptor }
            if Date() >= deadline { close(descriptor); return nil }
            usleep(50_000)
        }
    }

    static func releaseLock(_ descriptor: Int32) {
        flock(descriptor, LOCK_UN)
        close(descriptor)
    }
}

// MARK: - First-run notice and launch wiring

/// Runs before any delegate (and so `Settings.shared`) exists.
func runLegacyMigrationAtLaunch() {
    guard let config = LegacyMigrationConfig.production() else { return }
    let report = LegacyMigration.run(config)
    if report.lockTimedOut {
        log("migration: another process holds the migration lock; continuing without migrating")
    } else if !report.alreadyMigrated {
        log("migration: legacy found=\(report.legacyFound) defaults copied=\(report.defaultsCopied) kept=\(report.defaultsKept) "
            + "paths rewritten=\(report.pathsRewritten) cloned=\(report.filesCloned) skipped=\(report.filesSkipped)")
    }
}

/// Agent only: Keychain token on a background queue, then the one-time notice.
func startLegacyMigrationFollowUps(language: @escaping @Sendable () -> InterfaceLanguage) {
    guard LegacyMigrationConfig.production() != nil else { return }
    DispatchQueue.global(qos: .utility).async {
        guard let config = LegacyMigrationConfig.production() else { return }
        let outcome = LegacyMigration.migrateKeychain(
            config,
            legacyStore: KeychainVocabularySyncTokenStore(service: LegacyIdentifiers.keychainService),
            newStore: KeychainVocabularySyncTokenStore()
        )
        log("migration: sync token \(outcome)")
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
        guard let config = LegacyMigrationConfig.production(),
              LegacyMigration.consumeFirstRunNotice(config) else { return }
        MainActor.assumeIsolated {
            presentLegacyMigrationNotice(language: language())
        }
    }
}

func legacyMigrationNoticeText(language: InterfaceLanguage) -> (title: String, body: String) {
    let title = localizedText("SuperDictate теперь Lexomorph",
                              "SuperDictate is now Lexomorph",
                              language: language)
    let body = localizedText(
        "Приложение переименовано: SuperDictate Next стало Lexomorph. Вместе с названием изменился пакет приложения "
            + "(/Applications/Lexomorph.app, com.local.lexomorph), поэтому macOS считает его новым приложением: "
            + "разрешения (микрофон, универсальный доступ, мониторинг ввода) нужно выдать заново. "
            + "Настройки, словарь и модели перенесены автоматически. Прежние данные SuperDictate остались нетронутыми "
            + "на случай отката.",
        "SuperDictate Next has been renamed to Lexomorph. The app bundle changed with the name "
            + "(/Applications/Lexomorph.app, com.local.lexomorph), so macOS treats it as a new app: "
            + "you need to grant the permissions again (Microphone, Accessibility, Input Monitoring). "
            + "Your settings, vocabulary and models were carried over automatically. The previous SuperDictate data "
            + "was left untouched in case you need to roll back.",
        language: language)
    return (title, body)
}

@MainActor
func presentLegacyMigrationNotice(language: InterfaceLanguage) {
    let text = legacyMigrationNoticeText(language: language)
    let alert = NSAlert()
    alert.messageText = text.title
    alert.informativeText = text.body
    alert.alertStyle = .informational
    alert.addButton(withTitle: "OK")
    NSApp.activate(ignoringOtherApps: true)
    alert.runModal()
}
