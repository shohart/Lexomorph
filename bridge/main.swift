// SuperDictate -> Lexomorph transition bridge (single file, no dependency on the main app).
//
// Build:   swiftc -O -o SuperDictate bridge/main.swift   (see scripts/build-bridge.sh)
// Modes:   (none) / --agent   interactive: one dialog, then install
//          --dry-run          everything except launchctl/open/removal, into the
//                             directories named by LEXOMORPH_BRIDGE_APPS_DIR and
//                             LEXOMORPH_BRIDGE_LAUNCHAGENTS_DIR; non-interactive
//          --print-plan       print paths and steps, change nothing
//          --self-test        run the built-in tests (needs ditto/bash, i.e. macOS)
// Spec: docs/specs/transition-release-spec.md section 2.

import AppKit
import Foundation

// MARK: - Constants

let newBundleID = "com.local.lexomorph"
let oldBundleID = "com.local.superdictate"
let newAppName = "Lexomorph.app"
let newExecutable = "Lexomorph"
let oldAppName = "SuperDictate.app"
let oldAgentLabel = "com.local.superdictate.agent"
let newAgentLabel = "com.local.lexomorph.agent"
let finishJobLabel = "com.local.lexomorph.bridge-finish"
let embeddedZipName = "Lexomorph.zip"

// MARK: - Process runner (injectable)

typealias RunResult = (status: Int32, output: String)
typealias Runner = (_ path: String, _ args: [String]) -> RunResult

func realRun(_ path: String, _ args: [String]) -> RunResult {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = pipe
    do { try p.run() } catch { return (127, "\(error)") }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(decoding: data, as: UTF8.self))
}

// MARK: - Configuration

struct BridgeConfig {
    var dryRun: Bool
    var appsDir: String
    var launchAgentsDir: String
    var logsDir: String?
    var uid: UInt32
    var home: String
    var bridgeVersion: String
    var zipPath: String
    var ownAppPath: String
    var language: Lang

    var newApp: String { appsDir + "/" + newAppName }
    var oldApp: String { appsDir + "/" + oldAppName }
    var oldAgentPlist: String { launchAgentsDir + "/" + oldAgentLabel + ".plist" }
    var newAgentPlist: String { launchAgentsDir + "/" + newAgentLabel + ".plist" }
    var newExecutablePath: String { newApp + "/Contents/MacOS/" + newExecutable }
    var agentLogPath: String { home + "/Library/Logs/Lexomorph-agent.launchd.log" }
    var bridgeLogPath: String? { logsDir.map { $0 + "/Lexomorph-bridge.log" } }
}

enum Lang { case en, ru }

func chooseLanguage(preferred: [String]) -> Lang {
    guard let first = preferred.first?.lowercased() else { return .en }
    return (first == "ru" || first.hasPrefix("ru-") || first.hasPrefix("ru_")) ? .ru : .en
}

func configFromEnvironment(arguments: [String], env: [String: String]) -> BridgeConfig {
    let dry = arguments.contains("--dry-run")
    let home = NSHomeDirectory()
    // Test hooks are honoured only in dry-run: a real run always uses the real locations.
    let apps = dry ? (env["LEXOMORPH_BRIDGE_APPS_DIR"] ?? "/Applications") : "/Applications"
    let agents = dry ? (env["LEXOMORPH_BRIDGE_LAUNCHAGENTS_DIR"] ?? home + "/Library/LaunchAgents")
                     : home + "/Library/LaunchAgents"
    let logs = dry ? env["LEXOMORPH_BRIDGE_LOGS_DIR"] : home + "/Library/Logs"
    let own = Bundle.main.bundlePath
    let zip = (dry ? env["LEXOMORPH_BRIDGE_ZIP"] : nil)
        ?? own + "/Contents/Resources/" + embeddedZipName
    let version = (dry ? env["LEXOMORPH_BRIDGE_VERSION"] : nil)
        ?? (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "")
    return BridgeConfig(dryRun: dry, appsDir: apps, launchAgentsDir: agents, logsDir: logs,
                        uid: getuid(), home: home, bridgeVersion: version, zipPath: zip,
                        ownAppPath: own, language: chooseLanguage(preferred: Locale.preferredLanguages))
}

// MARK: - Texts

struct Texts {
    let title: String, body: String, install: String, notNow: String
    let doneTitle: String
    func failure(_ reason: String) -> String { failurePrefix + reason }
    let failurePrefix: String
    let failureTitle: String
}

func dialogTexts(lang: Lang, alreadyInstalled: Bool, version: String) -> Texts {
    switch (lang, alreadyInstalled) {
    case (.en, false):
        return Texts(
            title: "SuperDictate Next is now Lexomorph",
            body: """
            SuperDictate Next has been renamed Lexomorph. The app has a new name, a new package \
            (com.local.lexomorph) and a new signature, so this small transition app will install \
            Lexomorph \(version) and remove the old SuperDictate app.

            \u{2022} Your settings, vocabulary, history and downloaded models are carried over by Lexomorph \
            the first time it starts. The originals are kept untouched.
            \u{2022} macOS treats Lexomorph as a new app: you will need to grant the Microphone, \
            Accessibility and Input Monitoring permissions again.

            Install Lexomorph now?
            """,
            install: "Install Lexomorph", notNow: "Not now", doneTitle: "Lexomorph",
            failurePrefix: "The installation was not completed and the previous state was restored.\n\n",
            failureTitle: "Lexomorph installation")
    case (.en, true):
        return Texts(
            title: "Lexomorph is already installed",
            body: """
            Lexomorph \(version) is already installed. Finish the transition: switch the background \
            service to Lexomorph and remove the old SuperDictate app? Your data is kept.
            """,
            install: "Finish cleanup", notNow: "Not now", doneTitle: "Lexomorph",
            failurePrefix: "The cleanup was not completed and the previous state was restored.\n\n",
            failureTitle: "Lexomorph installation")
    case (.ru, false):
        return Texts(
            title: "SuperDictate Next теперь Lexomorph",
            body: """
            SuperDictate Next переименован в Lexomorph. У приложения новое название, новый пакет \
            (com.local.lexomorph) и новая подпись, поэтому эта небольшая переходная программа \
            установит Lexomorph \(version) и удалит старое приложение SuperDictate.

            \u{2022} Настройки, словарь, история и загруженные модели переносятся самим Lexomorph при первом \
            запуске. Оригиналы остаются нетронутыми.
            \u{2022} macOS считает Lexomorph новым приложением: разрешения на микрофон, универсальный доступ \
            и мониторинг ввода нужно выдать заново.

            Установить Lexomorph сейчас?
            """,
            install: "Установить Lexomorph", notNow: "Не сейчас", doneTitle: "Lexomorph",
            failurePrefix: "Установка не завершена, прежнее состояние восстановлено.\n\n",
            failureTitle: "Установка Lexomorph")
    case (.ru, true):
        return Texts(
            title: "Lexomorph уже установлен",
            body: """
            Lexomorph \(version) уже установлен. Завершить переход: переключить фоновую службу на Lexomorph \
            и удалить старое приложение SuperDictate? Ваши данные сохранятся.
            """,
            install: "Завершить уборку", notNow: "Не сейчас", doneTitle: "Lexomorph",
            failurePrefix: "Уборка не завершена, прежнее состояние восстановлено.\n\n",
            failureTitle: "Установка Lexomorph")
    }
}

// MARK: - Pure logic: plist / signatures / bundle checks

struct BridgeError: Error, CustomStringConvertible {
    let description: String
    init(_ d: String) { description = d }
}

func shq(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\"'\"'") + "'" }

func xmlEscape(_ s: String) -> String {
    s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
        .replacingOccurrences(of: ">", with: "&gt;")
}

/// Same keys as LexomorphAgentService.writeLaunchAgentPlist and scripts/install-local.sh.
func agentPlistXML(label: String, executable: String, logPath: String) -> String {
    """
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
    \t<key>KeepAlive</key>
    \t<dict>
    \t\t<key>SuccessfulExit</key>
    \t\t<false/>
    \t</dict>
    \t<key>Label</key>
    \t<string>\(xmlEscape(label))</string>
    \t<key>ProcessType</key>
    \t<string>Interactive</string>
    \t<key>ProgramArguments</key>
    \t<array>
    \t\t<string>\(xmlEscape(executable))</string>
    \t\t<string>--agent</string>
    \t</array>
    \t<key>RunAtLoad</key>
    \t<true/>
    \t<key>StandardErrorPath</key>
    \t<string>\(xmlEscape(logPath))</string>
    \t<key>StandardOutPath</key>
    \t<string>\(xmlEscape(logPath))</string>
    </dict>
    </plist>

    """
}

func finishJobPlistXML(scriptPath: String) -> String {
    """
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
    \t<key>Label</key>
    \t<string>\(finishJobLabel)</string>
    \t<key>ProgramArguments</key>
    \t<array>
    \t\t<string>/bin/bash</string>
    \t\t<string>\(xmlEscape(scriptPath))</string>
    \t</array>
    \t<key>RunAtLoad</key>
    \t<true/>
    </dict>
    </plist>

    """
}

struct Signer: Equatable {
    var authority: String
    var team: String
}

/// Parses `codesign -dv --verbose=4` output (leaf Authority + TeamIdentifier).
func parseSigner(_ output: String) -> Signer {
    var authority = "", team = ""
    for line in output.split(separator: "\n") {
        if authority.isEmpty, line.hasPrefix("Authority=") { authority = String(line.dropFirst(10)) }
        if line.hasPrefix("TeamIdentifier=") { team = String(line.dropFirst(15)) }
    }
    if team == "not set" { team = "" }
    return Signer(authority: authority, team: team)
}

func signer(of path: String, run: Runner) -> Signer {
    let r = run("/usr/bin/codesign", ["-dv", "--verbose=4", path])
    return r.status == 0 ? parseSigner(r.output) : Signer(authority: "", team: "")
}

func readInfo(_ app: String) -> [String: Any]? {
    guard let d = FileManager.default.contents(atPath: app + "/Contents/Info.plist"),
          let o = try? PropertyListSerialization.propertyList(from: d, format: nil) as? [String: Any]
    else { return nil }
    return o
}

func containsSymlink(_ root: String) -> Bool {
    let fm = FileManager.default
    guard let e = fm.enumerator(at: URL(fileURLWithPath: root),
                                includingPropertiesForKeys: [.isSymbolicLinkKey]) else { return false }
    for case let u as URL in e {
        if (try? u.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true { return true }
    }
    return false
}

/// Checks a Lexomorph bundle: bundle id, version, executable, strict signature, same signer as the bridge.
func verifyLexomorphApp(_ app: String, expectedVersion: String, ownSigner: Signer,
                        requireSigner: Bool, run: Runner) throws {
    guard let info = readInfo(app) else { throw BridgeError("Info.plist is missing in \(newAppName).") }
    guard info["CFBundleIdentifier"] as? String == newBundleID else {
        throw BridgeError("Unexpected bundle identifier: \(info["CFBundleIdentifier"] as? String ?? "none").")
    }
    guard info["CFBundleShortVersionString"] as? String == expectedVersion else {
        throw BridgeError("Unexpected version: \(info["CFBundleShortVersionString"] as? String ?? "none"), expected \(expectedVersion).")
    }
    guard FileManager.default.isExecutableFile(atPath: app + "/Contents/MacOS/" + newExecutable) else {
        throw BridgeError("The Lexomorph executable is missing.")
    }
    let cs = run("/usr/bin/codesign", ["--verify", "--deep", "--strict", app])
    guard cs.status == 0 else { throw BridgeError("The signature check failed: \(cs.output)") }
    let theirs = signer(of: app, run: run)
    if requireSigner && ownSigner.authority.isEmpty {
        throw BridgeError("The bridge itself is not signed with a certificate.")
    }
    guard theirs == ownSigner else {
        throw BridgeError("Lexomorph is signed by a different identity (\(theirs.authority)) than this app (\(ownSigner.authority)).")
    }
}

// MARK: - Install (Swift side): extract, verify, stage, atomic replace, rollback

enum InstallOutcome: Equatable {
    case alreadyInstalled
    case installed(backup: String?)
}

struct Installer {
    let cfg: BridgeConfig
    let run: Runner

    func log(_ s: String) {
        let line = "\(ISO8601DateFormatter().string(from: Date())) \(s)\n"
        FileHandle.standardOutput.write(Data(line.utf8))
        if let p = cfg.bridgeLogPath {
            try? FileManager.default.createDirectory(atPath: (p as NSString).deletingLastPathComponent,
                                                     withIntermediateDirectories: true)
            if let h = FileHandle(forWritingAtPath: p) ?? {
                FileManager.default.createFile(atPath: p, contents: nil); return FileHandle(forWritingAtPath: p) }() {
                h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close()
            }
        }
    }

    /// Cheap check used to pick the dialog variant (no signature work).
    func installedLooksCurrent() -> Bool {
        guard let info = readInfo(cfg.newApp) else { return false }
        return info["CFBundleIdentifier"] as? String == newBundleID
            && info["CFBundleShortVersionString"] as? String == cfg.bridgeVersion
    }

    func perform() throws -> InstallOutcome {
        let fm = FileManager.default
        let own = signer(of: cfg.ownAppPath, run: run)
        let requireSigner = !cfg.dryRun

        // Idempotency: a fully valid installed copy of the same version is left alone.
        if installedLooksCurrent(),
           (try? verifyLexomorphApp(cfg.newApp, expectedVersion: cfg.bridgeVersion, ownSigner: own,
                                    requireSigner: requireSigner, run: run)) != nil {
            log("Lexomorph \(cfg.bridgeVersion) is already installed and valid; leaving it in place.")
            return .alreadyInstalled
        }

        guard fm.fileExists(atPath: cfg.zipPath) else {
            throw BridgeError("The embedded \(embeddedZipName) is missing.")
        }
        guard fm.isWritableFile(atPath: cfg.appsDir) else {
            throw BridgeError("\(cfg.appsDir) is not writable. Install with the command-line installer instead.")
        }
        let tag = "\(getpid())-\(UInt32.random(in: 0...UInt32.max))"
        let work = cfg.appsDir + "/.Lexomorph.bridge.\(tag)"
        let incoming = cfg.appsDir + "/.Lexomorph.incoming.\(tag)"
        let backup = cfg.appsDir + "/.Lexomorph.previous.\(tag)"
        defer {
            try? fm.removeItem(atPath: work)
            try? fm.removeItem(atPath: incoming)
        }
        try fm.createDirectory(atPath: work, withIntermediateDirectories: false,
                               attributes: [.posixPermissions: 0o700])

        // 1. extract into a private temp dir and verify
        log("Extracting \(embeddedZipName)...")
        let x = run("/usr/bin/ditto", ["-x", "-k", cfg.zipPath, work])
        guard x.status == 0 else { throw BridgeError("Could not extract Lexomorph: \(x.output)") }
        let extracted = work + "/" + newAppName
        guard fm.fileExists(atPath: extracted) else { throw BridgeError("The archive has no \(newAppName).") }
        try verifyLexomorphApp(extracted, expectedVersion: cfg.bridgeVersion, ownSigner: own,
                               requireSigner: requireSigner, run: run)

        // 2. stage next to the destination (same volume) and re-verify
        let c = run("/usr/bin/ditto", [extracted, incoming])
        guard c.status == 0 else { throw BridgeError("Could not stage Lexomorph: \(c.output)") }
        try verifyLexomorphApp(incoming, expectedVersion: cfg.bridgeVersion, ownSigner: own,
                               requireSigner: requireSigner, run: run)

        // 3. replace with backup; roll back on any failure
        var madeBackup = false
        do {
            if fm.fileExists(atPath: cfg.newApp) {
                try fm.moveItem(atPath: cfg.newApp, toPath: backup)
                madeBackup = true
            }
            try fm.moveItem(atPath: incoming, toPath: cfg.newApp)
            try verifyLexomorphApp(cfg.newApp, expectedVersion: cfg.bridgeVersion, ownSigner: own,
                                   requireSigner: requireSigner, run: run)
        } catch {
            try? fm.removeItem(atPath: cfg.newApp)
            if madeBackup { try? fm.moveItem(atPath: backup, toPath: cfg.newApp) }
            throw error
        }
        log("Installed \(cfg.newApp)\(madeBackup ? " (previous kept at \(backup))" : "").")
        return .installed(backup: madeBackup ? backup : nil)
    }

    /// Undo a replacement made by perform() (used if handing off to the helper fails).
    func rollback(_ outcome: InstallOutcome) {
        guard case .installed(let backup) = outcome else { return }
        let fm = FileManager.default
        try? fm.removeItem(atPath: cfg.newApp)
        if let b = backup { try? fm.moveItem(atPath: b, toPath: cfg.newApp) }
    }
}

// MARK: - Helper script (detached; survives the bridge and the old agent)

struct HelperParams {
    var uid: UInt32
    var appsDir: String
    var newApp: String
    var oldApp: String
    var backup: String?
    var installedByBridge: Bool
    var oldPlist: String
    var newPlistDst: String
    var newPlistSrc: String      // pre-generated content, in the work dir
    var workDir: String
    var bridgePID: Int32
    var logPath: String          // "" = no log file
    var failTitle: String
    var failMessage: String
    var launchctl: String = "/bin/launchctl"
    var quiet: Bool = false      // true: no osascript dialog (tests)
    var maxWaitSeconds: Int = 40
    var stableSeconds: Int = 4
}

func helperScript(_ p: HelperParams) -> String {
    #"""
    #!/bin/bash
    # Generated by the SuperDictate -> Lexomorph bridge. Runs detached.
    set -u
    UID_N=\#(p.uid)
    OLD_LABEL=\#(shq(oldAgentLabel))
    NEW_LABEL=\#(shq(newAgentLabel))
    JOB_LABEL=\#(shq(finishJobLabel))
    NEW_APP=\#(shq(p.newApp))
    OLD_APP=\#(shq(p.oldApp))
    BACKUP=\#(shq(p.backup ?? ""))
    INSTALLED_BY_BRIDGE=\#(p.installedByBridge ? 1 : 0)
    OLD_PLIST=\#(shq(p.oldPlist))
    NEW_PLIST_DST=\#(shq(p.newPlistDst))
    NEW_PLIST_SRC=\#(shq(p.newPlistSrc))
    WORK=\#(shq(p.workDir))
    BRIDGE_PID=\#(p.bridgePID)
    LOG=\#(shq(p.logPath))
    FAIL_TITLE=\#(shq(p.failTitle))
    FAIL_MESSAGE=\#(shq(p.failMessage))
    LAUNCHCTL=\#(shq(p.launchctl))
    QUIET=\#(p.quiet ? 1 : 0)
    MAX_WAIT=\#(p.maxWaitSeconds)
    STABLE=\#(p.stableSeconds)
    OLD_PLIST_BAK="$WORK/old-agent.plist.bak"
    NEW_PLIST_BAK="$WORK/new-agent.plist.bak"

    log() { [ -n "$LOG" ] && printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG" 2>/dev/null; return 0; }

    cleanup() {
        /bin/rm -rf "$WORK"
        "$LAUNCHCTL" bootout "gui/$UID_N/$JOB_LABEL" >/dev/null 2>&1
        exit "${1:-0}"
    }

    agent_pid() {
        "$LAUNCHCTL" print "gui/$UID_N/$NEW_LABEL" 2>/dev/null \
            | /usr/bin/sed -n 's/^[[:space:]]*pid = \([0-9][0-9]*\)$/\1/p' | /usr/bin/head -n 1
    }

    rollback() {
        log "ROLLBACK: $1"
        "$LAUNCHCTL" bootout "gui/$UID_N/$NEW_LABEL" >/dev/null 2>&1
        if [ -f "$NEW_PLIST_BAK" ]; then /bin/cp -p "$NEW_PLIST_BAK" "$NEW_PLIST_DST"; else /bin/rm -f "$NEW_PLIST_DST"; fi
        if [ -n "$BACKUP" ] && [ -d "$BACKUP" ]; then
            /bin/rm -rf "$NEW_APP"; /bin/mv "$BACKUP" "$NEW_APP"
        elif [ "$INSTALLED_BY_BRIDGE" = 1 ]; then
            /bin/rm -rf "$NEW_APP"
        fi
        # Restore the old agent definition (do not start it: it is the bridge and would ask again at once).
        if [ -f "$OLD_PLIST_BAK" ]; then /bin/cp -p "$OLD_PLIST_BAK" "$OLD_PLIST"; fi
        if [ "$QUIET" != 1 ]; then
            /usr/bin/osascript -e 'on run argv' \
                -e 'display dialog (item 2 of argv) & return & return & (item 3 of argv) with title (item 1 of argv) buttons {"OK"} default button "OK" with icon caution' \
                -e 'end run' "$FAIL_TITLE" "$FAIL_MESSAGE" "$1" >/dev/null 2>&1
        fi
        cleanup 1
    }

    log "finish helper started (bridge pid $BRIDGE_PID)"

    # 0. the bridge must be gone before its bundle can be removed
    for _ in $(seq 1 40); do /bin/kill -0 "$BRIDGE_PID" 2>/dev/null || break; /bin/sleep 0.25; done
    if /bin/kill -0 "$BRIDGE_PID" 2>/dev/null; then /bin/kill -TERM "$BRIDGE_PID" 2>/dev/null; /bin/sleep 1; fi

    # 1. retire the old agent, remembering its plist for rollback
    [ -f "$OLD_PLIST" ] && /bin/cp -p "$OLD_PLIST" "$OLD_PLIST_BAK"
    [ -f "$NEW_PLIST_DST" ] && /bin/cp -p "$NEW_PLIST_DST" "$NEW_PLIST_BAK"
    "$LAUNCHCTL" bootout "gui/$UID_N/$OLD_LABEL" >/dev/null 2>&1
    /usr/bin/pkill -f "$OLD_APP/Contents/MacOS/" >/dev/null 2>&1
    /bin/rm -f "$OLD_PLIST"

    # 2. install the new agent definition and start Lexomorph
    [ -d "$NEW_APP" ] || rollback "Lexomorph.app is missing"
    /bin/mkdir -p "$(dirname "$NEW_PLIST_DST")"
    /bin/cp "$NEW_PLIST_SRC" "$NEW_PLIST_DST" || rollback "could not write the Lexomorph agent plist"
    "$LAUNCHCTL" bootout "gui/$UID_N/$NEW_LABEL" >/dev/null 2>&1
    "$LAUNCHCTL" bootstrap "gui/$UID_N" "$NEW_PLIST_DST" >/dev/null 2>&1
    "$LAUNCHCTL" enable "gui/$UID_N/$NEW_LABEL" >/dev/null 2>&1
    "$LAUNCHCTL" kickstart "gui/$UID_N/$NEW_LABEL" >/dev/null 2>&1

    # 3. only a stable running agent counts as success
    ok=0; waited=0
    while [ "$waited" -lt "$MAX_WAIT" ]; do
        pid="$(agent_pid)"
        if [ -n "$pid" ] && /bin/kill -0 "$pid" 2>/dev/null; then
            /bin/sleep "$STABLE"
            pid2="$(agent_pid)"
            if [ "$pid2" = "$pid" ] && /bin/kill -0 "$pid2" 2>/dev/null; then ok=1; break; fi
        fi
        /bin/sleep 1; waited=$((waited + 1))
    done
    [ "$ok" = 1 ] || rollback "the Lexomorph agent did not start"

    # 4. the new agent runs: remove the old app (only if it really is the old app) and the backup
    if [ -d "$OLD_APP" ]; then
        bid="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$OLD_APP/Contents/Info.plist" 2>/dev/null)"
        if [ "$bid" = \#(shq(oldBundleID)) ]; then /bin/rm -rf "$OLD_APP"; log "removed $OLD_APP"; else log "left $OLD_APP (unexpected bundle id '$bid')"; fi
    fi
    [ -n "$BACKUP" ] && /bin/rm -rf "$BACKUP"
    log "done"
    cleanup 0
    """#
}

// MARK: - Plan

func planText(_ cfg: BridgeConfig) -> String {
    """
    SuperDictate -> Lexomorph bridge plan (version \(cfg.bridgeVersion), dry-run: \(cfg.dryRun))
    language           : \(cfg.language == .ru ? "ru" : "en")
    embedded archive   : \(cfg.zipPath)
    install target     : \(cfg.newApp)   (bundle id \(newBundleID), version \(cfg.bridgeVersion))
    old app to remove  : \(cfg.oldApp)   (only after the new agent is confirmed running)
    old agent          : \(oldAgentLabel)  plist \(cfg.oldAgentPlist)
    new agent          : \(newAgentLabel)  plist \(cfg.newAgentPlist)
    steps:
      1. ditto -x -k archive into \(cfg.appsDir)/.Lexomorph.bridge.*, verify bundle id/version/codesign/signer
      2. stage + atomic replace \(cfg.newApp) (backup, rollback on failure)
      3. [detached helper] bootout \(oldAgentLabel), remove its plist, write \(cfg.newAgentPlist), bootstrap+kickstart \(newAgentLabel)
      4. [detached helper] after a stable running agent: remove \(cfg.oldApp); otherwise roll back
    never touched: user data, defaults, Keychain, tccutil

    """
}

// MARK: - Run (shared by GUI and dry-run)

/// Performs the install; returns the outcome and (unless dry-run) launches the helper.
func runInstall(cfg: BridgeConfig, run: @escaping Runner) throws {
    let inst = Installer(cfg: cfg, run: run)
    let outcome = try inst.perform()
    let fm = FileManager.default
    let t = dialogTexts(lang: cfg.language, alreadyInstalled: false, version: cfg.bridgeVersion)

    let tag = "\(getpid())-\(UInt32.random(in: 0...UInt32.max))"
    let work = cfg.appsDir + "/.Lexomorph.finish.\(tag)"
    try fm.createDirectory(atPath: work, withIntermediateDirectories: false,
                           attributes: [.posixPermissions: 0o700])
    var handedOff = false
    defer { if !handedOff { try? fm.removeItem(atPath: work) } }

    let plistSrc = work + "/new-agent.plist"
    try agentPlistXML(label: newAgentLabel, executable: cfg.newExecutablePath, logPath: cfg.agentLogPath)
        .write(toFile: plistSrc, atomically: true, encoding: .utf8)
    var backup: String? = nil
    var byBridge = false
    if case .installed(let b) = outcome { backup = b; byBridge = true }
    let params = HelperParams(uid: cfg.uid, appsDir: cfg.appsDir, newApp: cfg.newApp, oldApp: cfg.oldApp,
                              backup: backup, installedByBridge: byBridge, oldPlist: cfg.oldAgentPlist,
                              newPlistDst: cfg.newAgentPlist, newPlistSrc: plistSrc, workDir: work,
                              bridgePID: getpid(), logPath: cfg.bridgeLogPath ?? "",
                              failTitle: t.failureTitle, failMessage: t.failurePrefix.trimmingCharacters(in: .whitespacesAndNewlines))
    let scriptPath = work + "/finish.sh"
    try helperScript(params).write(toFile: scriptPath, atomically: true, encoding: .utf8)
    chmod(scriptPath, 0o700)

    if cfg.dryRun {
        // Dry-run: the new agent plist is written into the target dir for inspection; nothing is started or removed.
        try fm.createDirectory(atPath: cfg.launchAgentsDir, withIntermediateDirectories: true)
        try? fm.removeItem(atPath: cfg.newAgentPlist + ".dryrun")
        try fm.copyItem(atPath: plistSrc, toPath: cfg.newAgentPlist + ".dryrun")
        inst.log("dry-run: wrote \(cfg.newAgentPlist).dryrun; helper script at \(scriptPath) (not executed, no launchctl, no removal)")
        handedOff = true   // keep the script for inspection inside the temp dir
        return
    }

    // Start the helper as its own launchd job so it survives the old agent being booted out.
    let jobPlist = work + "/job.plist"
    try finishJobPlistXML(scriptPath: scriptPath).write(toFile: jobPlist, atomically: true, encoding: .utf8)
    let boot = run("/bin/launchctl", ["bootstrap", "gui/\(cfg.uid)", jobPlist])
    if boot.status != 0 {
        // Fallback: plain detached bash.
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/bash")
        p.arguments = [scriptPath]
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
        p.standardInput = FileHandle.nullDevice
        do { try p.run() } catch {
            inst.rollback(outcome)
            throw BridgeError("Could not start the finishing step: \(boot.output)")
        }
    }
    handedOff = true
}

// MARK: - GUI

func showDialog(_ t: Texts) -> Bool {
    let a = NSAlert()
    a.messageText = t.title
    a.informativeText = t.body
    a.alertStyle = .informational
    a.addButton(withTitle: t.install)
    a.addButton(withTitle: t.notNow)
    NSApp.activate(ignoringOtherApps: true)
    return a.runModal() == .alertFirstButtonReturn
}

func showError(_ t: Texts, _ reason: String) {
    let a = NSAlert()
    a.messageText = t.failureTitle
    a.informativeText = t.failure(reason)
    a.alertStyle = .critical
    a.addButton(withTitle: "OK")
    NSApp.activate(ignoringOtherApps: true)
    a.runModal()
}

func runGUI(cfg: BridgeConfig) -> Never {
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    // Launched by the old agent AND by hand: only one instance asks.
    let me = ProcessInfo.processInfo.processIdentifier
    if NSRunningApplication.runningApplications(withBundleIdentifier: oldBundleID).contains(where: { $0.processIdentifier != me }) {
        exit(0)
    }
    let inst = Installer(cfg: cfg, run: realRun)
    let already = inst.installedLooksCurrent()
    let t = dialogTexts(lang: cfg.language, alreadyInstalled: already, version: cfg.bridgeVersion)
    guard showDialog(t) else { exit(0) }   // "Not now": nothing changed. Always exit 0 (launchd must not respawn).
    do {
        try runInstall(cfg: cfg, run: realRun)
    } catch {
        showError(t, "\(error)")
    }
    exit(0)
}

// MARK: - Self-test

final class TestRun {
    var failures = 0, count = 0
    func check(_ cond: Bool, _ name: String) {
        count += 1
        if cond { print("  ok   \(name)") } else { failures += 1; print("  FAIL \(name)") }
    }
}

func makeFakeApp(at dir: String, bundleID: String, version: String, marker: String = "") throws {
    let fm = FileManager.default
    try fm.createDirectory(atPath: dir + "/Contents/MacOS", withIntermediateDirectories: true)
    let plist: [String: Any] = ["CFBundleIdentifier": bundleID, "CFBundleShortVersionString": version]
    try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        .write(to: URL(fileURLWithPath: dir + "/Contents/Info.plist"))
    let exe = dir + "/Contents/MacOS/" + newExecutable
    try "#!/bin/sh\nexit 0\n".write(toFile: exe, atomically: true, encoding: .utf8)
    chmod(exe, 0o755)
    if !marker.isEmpty { try marker.write(toFile: dir + "/Contents/marker.txt", atomically: true, encoding: .utf8) }
}

func zipApp(_ app: String, to zip: String) {
    _ = realRun("/usr/bin/ditto", ["-c", "-k", "--keepParent", app, zip])
}

func readText(_ p: String) -> String? { try? String(contentsOfFile: p, encoding: .utf8) }

func listTree(_ root: String) -> Set<String> {
    var s = Set<String>()
    if let e = FileManager.default.enumerator(atPath: root) { for case let p as String in e { s.insert(p) } }
    return s
}

func selfTest() -> Int32 {
    let T = TestRun()
    let fm = FileManager.default
    let base = NSTemporaryDirectory() + "lexomorph-bridge-selftest-\(getpid())"
    try? fm.removeItem(atPath: base)
    try! fm.createDirectory(atPath: base, withIntermediateDirectories: true)
    defer { try? fm.removeItem(atPath: base) }

    print("language")
    T.check(chooseLanguage(preferred: ["ru-RU", "en"]) == .ru, "ru-RU -> ru")
    T.check(chooseLanguage(preferred: ["ru"]) == .ru, "ru -> ru")
    T.check(chooseLanguage(preferred: ["en-US", "ru"]) == .en, "en first -> en")
    T.check(chooseLanguage(preferred: ["de"]) == .en, "other -> en")
    T.check(chooseLanguage(preferred: []) == .en, "empty -> en")
    let tx = dialogTexts(lang: .ru, alreadyInstalled: false, version: "0.10.0")
    T.check(tx.install == "Установить Lexomorph" && tx.notNow == "Не сейчас", "ru buttons")
    let te = dialogTexts(lang: .en, alreadyInstalled: false, version: "0.10.0")
    T.check(te.install == "Install Lexomorph" && te.notNow == "Not now" && te.body.contains("0.10.0"), "en buttons")

    print("agent plist")
    let xml = agentPlistXML(label: newAgentLabel, executable: "/Applications/Lexomorph.app/Contents/MacOS/Lexomorph",
                            logPath: "/Users/u/Library/Logs/Lexomorph-agent.launchd.log")
    if let d = try? PropertyListSerialization.propertyList(from: Data(xml.utf8), format: nil) as? [String: Any] {
        T.check(d["Label"] as? String == "com.local.lexomorph.agent", "label")
        T.check(d["ProgramArguments"] as? [String] == ["/Applications/Lexomorph.app/Contents/MacOS/Lexomorph", "--agent"], "program arguments")
        T.check(d["RunAtLoad"] as? Bool == true, "RunAtLoad")
        T.check((d["KeepAlive"] as? [String: Bool])?["SuccessfulExit"] == false, "KeepAlive SuccessfulExit=false")
        T.check(d["ProcessType"] as? String == "Interactive", "ProcessType")
    } else { T.check(false, "plist parses") }

    print("signer parsing")
    T.check(parseSigner("Authority=Aleksei Bykov\nTeamIdentifier=not set\n") == Signer(authority: "Aleksei Bykov", team: ""), "self-signed")
    T.check(parseSigner("Authority=Developer ID\nAuthority=Apple Root\nTeamIdentifier=ABC\n") == Signer(authority: "Developer ID", team: "ABC"), "first authority")

    // Fake codesign: behaviour controlled per test.
    var signatureOK: (String) -> Bool = { _ in true }
    var authorityFor: (String) -> String = { _ in "Test Identity" }
    var calls: [String] = []
    let fake: Runner = { path, args in
        calls.append(path + " " + args.joined(separator: " "))
        if path == "/usr/bin/codesign" {
            if args.first == "--verify" { let ok = signatureOK(args.last!); return (ok ? 0 : 1, ok ? "" : "invalid signature") }
            return (0, "Authority=\(authorityFor(args.last!))\nTeamIdentifier=not set\n")
        }
        return realRun(path, args)
    }
    func mkCfg(_ name: String, zipBundleID: String = newBundleID, zipVersion: String = "0.10.0", dry: Bool = true) -> (BridgeConfig, String) {
        let root = base + "/" + name
        try! fm.createDirectory(atPath: root + "/apps", withIntermediateDirectories: true)
        try! fm.createDirectory(atPath: root + "/agents", withIntermediateDirectories: true)
        let src = root + "/src/Lexomorph.app"
        try! makeFakeApp(at: src, bundleID: zipBundleID, version: zipVersion, marker: "new")
        zipApp(src, to: root + "/Lexomorph.zip")
        let cfg = BridgeConfig(dryRun: dry, appsDir: root + "/apps", launchAgentsDir: root + "/agents", logsDir: nil,
                               uid: 501, home: root + "/home", bridgeVersion: "0.10.0", zipPath: root + "/Lexomorph.zip",
                               ownAppPath: root + "/own.app", language: .en)
        return (cfg, root)
    }

    print("fresh install (dry-run) writes only inside the given dirs")
    do {
        let (cfg, root) = mkCfg("fresh")
        let before = listTree(root)
        signatureOK = { _ in true }; authorityFor = { _ in "Test Identity" }; calls = []
        do { try runInstall(cfg: cfg, run: fake) } catch { T.check(false, "install threw \(error)") }
        let added = listTree(root).subtracting(before)
        T.check(fm.fileExists(atPath: cfg.newApp + "/Contents/Info.plist"), "Lexomorph.app installed")
        T.check(added.allSatisfy { $0.hasPrefix("apps/") || $0.hasPrefix("agents/") }, "all new files under apps/ or agents/")
        T.check(fm.fileExists(atPath: cfg.newAgentPlist + ".dryrun"), "agent plist written (dry-run suffix)")
        T.check(!calls.contains { $0.contains("launchctl") || $0.contains("/usr/bin/open") }, "no launchctl/open in dry-run")
        T.check(!fm.fileExists(atPath: cfg.oldApp) && !fm.fileExists(atPath: cfg.oldAgentPlist), "no old app/plist touched")
        T.check(!listTree(cfg.appsDir).contains { $0.hasPrefix(".Lexomorph.bridge.") || $0.hasPrefix(".Lexomorph.incoming.") }, "temp extraction dirs removed")
        if let script = listTree(cfg.appsDir).first(where: { $0.hasSuffix("finish.sh") }) {
            T.check(realRun("/bin/bash", ["-n", cfg.appsDir + "/" + script]).status == 0, "helper script passes bash -n")
        } else { T.check(false, "helper script written") }
    }

    print("bad signature: nothing installed, existing kept")
    do {
        let (cfg, _) = mkCfg("badsig")
        try! makeFakeApp(at: cfg.newApp, bundleID: newBundleID, version: "0.9.0", marker: "old")
        signatureOK = { _ in false }
        var threw = false
        do { _ = try Installer(cfg: cfg, run: fake).perform() } catch { threw = true }
        T.check(threw, "throws on invalid signature")
        T.check(fm.fileExists(atPath: cfg.newApp + "/Contents/marker.txt"), "existing app untouched")
        T.check(listTree(cfg.appsDir).allSatisfy { !$0.hasPrefix(".Lexomorph.") }, "no leftovers")
    }

    print("wrong bundle id / version / signer")
    do {
        signatureOK = { _ in true }
        let (c1, _) = mkCfg("badid", zipBundleID: "com.example.other")
        var threw = false
        do { _ = try Installer(cfg: c1, run: fake).perform() } catch { threw = true }
        T.check(threw && !fm.fileExists(atPath: c1.newApp), "wrong bundle id rejected, nothing installed")
        let (c2, _) = mkCfg("badver", zipVersion: "0.9.9")
        threw = false
        do { _ = try Installer(cfg: c2, run: fake).perform() } catch { threw = true }
        T.check(threw && !fm.fileExists(atPath: c2.newApp), "wrong version rejected")
        let (c3, _) = mkCfg("badauth")
        authorityFor = { $0.contains("own.app") ? "Bridge Identity" : "Other Identity" }
        threw = false
        do { _ = try Installer(cfg: c3, run: fake).perform() } catch { threw = true }
        T.check(threw && !fm.fileExists(atPath: c3.newApp), "authority mismatch rejected")
        authorityFor = { _ in "Test Identity" }
        let (c4, _) = mkCfg("unsignedown", dry: false)
        authorityFor = { _ in "" }
        threw = false
        do { _ = try Installer(cfg: c4, run: fake).perform() } catch { threw = true }
        T.check(threw && !fm.fileExists(atPath: c4.newApp), "unsigned bridge refused in real mode")
        authorityFor = { _ in "Test Identity" }
    }

    print("replace with backup; rollback when the final check fails")
    do {
        let (cfg, _) = mkCfg("replace")
        try! makeFakeApp(at: cfg.newApp, bundleID: newBundleID, version: "0.9.0", marker: "old")
        signatureOK = { _ in true }
        let out = try? Installer(cfg: cfg, run: fake).perform()
        if case .installed(let b)? = out, let b = b {
            T.check(fm.fileExists(atPath: b + "/Contents/marker.txt"), "backup holds the previous app")
            T.check(fm.fileExists(atPath: cfg.newApp + "/Contents/marker.txt") && (readText(cfg.newApp + "/Contents/marker.txt")) == "new", "new app in place")
        } else { T.check(false, "installed with backup") }

        let (cfg2, _) = mkCfg("rollback")
        try! makeFakeApp(at: cfg2.newApp, bundleID: newBundleID, version: "0.9.0", marker: "old")
        // Final check (the installed path, not the staging dirs) fails.
        signatureOK = { !$0.contains("/.Lexomorph.") && $0 != cfg2.ownAppPath ? false : true }
        var threw = false
        do { _ = try Installer(cfg: cfg2, run: fake).perform() } catch { threw = true }
        T.check(threw, "throws when the installed copy fails verification")
        T.check((readText(cfg2.newApp + "/Contents/marker.txt")) == "old", "previous app restored")
        T.check(listTree(cfg2.appsDir).allSatisfy { !$0.hasPrefix(".Lexomorph.") }, "no leftovers after rollback")
        signatureOK = { _ in true }
    }

    print("idempotency")
    do {
        let (cfg, _) = mkCfg("idem")
        signatureOK = { _ in true }
        _ = try? Installer(cfg: cfg, run: fake).perform()
        try! "keep".write(toFile: cfg.newApp + "/Contents/keep.txt", atomically: true, encoding: .utf8)
        let before = listTree(cfg.appsDir)
        let out = try? Installer(cfg: cfg, run: fake).perform()
        T.check(out == .alreadyInstalled, "second run reports already installed")
        T.check(listTree(cfg.appsDir) == before && fm.fileExists(atPath: cfg.newApp + "/Contents/keep.txt"), "second run changes nothing")
        T.check(Installer(cfg: cfg, run: fake).installedLooksCurrent(), "cheap check says current")
    }

    print("symlink detection")
    do {
        let d = base + "/sym"
        try! fm.createDirectory(atPath: d, withIntermediateDirectories: true)
        T.check(!containsSymlink(d), "no symlink")
        try! fm.createSymbolicLink(atPath: d + "/l", withDestinationPath: "/tmp")
        T.check(containsSymlink(d), "symlink found")
    }

    print("print-plan text")
    do {
        let (cfg, _) = mkCfg("plan")
        let p = planText(cfg)
        T.check(p.contains(newAgentLabel) && p.contains(cfg.newApp) && p.contains("never touched"), "plan lists targets")
    }

    print("helper script behaviour (fake launchctl)")
    func helperScenario(_ name: String, agentWorks: Bool, hadPrevious: Bool) {
        let root = base + "/h-" + name
        let apps = root + "/apps", agents = root + "/agents", work = apps + "/.Lexomorph.finish.t"
        try! fm.createDirectory(atPath: work, withIntermediateDirectories: true)
        try! fm.createDirectory(atPath: agents, withIntermediateDirectories: true)
        try! makeFakeApp(at: apps + "/Lexomorph.app", bundleID: newBundleID, version: "0.10.0", marker: "new")
        try! makeFakeApp(at: apps + "/SuperDictate.app", bundleID: oldBundleID, version: "0.10.0")
        var backup: String? = nil
        if hadPrevious {
            backup = apps + "/.Lexomorph.previous.t"
            try! makeFakeApp(at: backup!, bundleID: newBundleID, version: "0.9.0", marker: "old")
        }
        try! "OLDPLIST".write(toFile: agents + "/" + oldAgentLabel + ".plist", atomically: true, encoding: .utf8)
        try! "NEWPLIST".write(toFile: work + "/new-agent.plist", atomically: true, encoding: .utf8)
        // A live process the fake launchctl reports as the agent pid.
        let sleeper = Process(); sleeper.executableURL = URL(fileURLWithPath: "/bin/sleep"); sleeper.arguments = ["60"]
        try! sleeper.run()
        let lc = root + "/launchctl"
        let callLog = root + "/calls.log"
        let printBody = agentWorks ? "echo \"        pid = \(sleeper.processIdentifier)\"" : "exit 113"
        try! "#!/bin/sh\necho \"$@\" >> \(shq(callLog))\nif [ \"$1\" = print ]; then \(printBody); fi\nexit 0\n"
            .write(toFile: lc, atomically: true, encoding: .utf8)
        chmod(lc, 0o755)
        let params = HelperParams(uid: 501, appsDir: apps, newApp: apps + "/Lexomorph.app", oldApp: apps + "/SuperDictate.app",
                                  backup: backup, installedByBridge: true, oldPlist: agents + "/" + oldAgentLabel + ".plist",
                                  newPlistDst: agents + "/" + newAgentLabel + ".plist", newPlistSrc: work + "/new-agent.plist",
                                  workDir: work, bridgePID: 999999, logPath: root + "/log.txt", failTitle: "t", failMessage: "m",
                                  launchctl: lc, quiet: true, maxWaitSeconds: 3, stableSeconds: 1)
        let sp = root + "/finish.sh"
        try! helperScript(params).write(toFile: sp, atomically: true, encoding: .utf8)
        let r = realRun("/bin/bash", [sp])
        sleeper.terminate()
        let calls = (readText(callLog)) ?? ""
        if agentWorks {
            T.check(r.status == 0, "\(name): exit 0")
            T.check(!fm.fileExists(atPath: apps + "/SuperDictate.app"), "\(name): old app removed after agent confirmed")
            T.check(!fm.fileExists(atPath: agents + "/" + oldAgentLabel + ".plist"), "\(name): old plist removed")
            T.check((readText(agents + "/" + newAgentLabel + ".plist")) == "NEWPLIST", "\(name): new plist installed")
            T.check(backup == nil || !fm.fileExists(atPath: backup!), "\(name): backup removed")
            T.check(calls.contains("bootout gui/501/" + oldAgentLabel) && calls.contains("bootstrap gui/501") && calls.contains("kickstart gui/501/" + newAgentLabel), "\(name): launchctl sequence")
            T.check(!fm.fileExists(atPath: work), "\(name): work dir cleaned")
        } else {
            T.check(r.status == 1, "\(name): exit 1 on failure")
            T.check(fm.fileExists(atPath: apps + "/SuperDictate.app"), "\(name): old app NOT removed")
            T.check((readText(agents + "/" + oldAgentLabel + ".plist")) == "OLDPLIST", "\(name): old plist restored")
            T.check(!fm.fileExists(atPath: agents + "/" + newAgentLabel + ".plist"), "\(name): new plist removed")
            if hadPrevious {
                T.check((readText(apps + "/Lexomorph.app/Contents/marker.txt")) == "old", "\(name): previous Lexomorph restored")
            } else {
                T.check(!fm.fileExists(atPath: apps + "/Lexomorph.app"), "\(name): fresh Lexomorph removed")
            }
        }
    }
    helperScenario("success", agentWorks: true, hadPrevious: true)
    helperScenario("fail-prev", agentWorks: false, hadPrevious: true)
    helperScenario("fail-fresh", agentWorks: false, hadPrevious: false)

    print("\(T.count - T.failures)/\(T.count) passed")
    return T.failures == 0 ? 0 : 1
}

// MARK: - Entry

let args = Array(CommandLine.arguments.dropFirst())
let cfg = configFromEnvironment(arguments: args, env: ProcessInfo.processInfo.environment)

if args.contains("--self-test") {
    exit(selfTest())
} else if args.contains("--print-plan") {
    print(planText(cfg), terminator: "")
    exit(0)
} else if args.contains("--dry-run") {
    do {
        let inst = Installer(cfg: cfg, run: realRun)
        inst.log("dry-run into \(cfg.appsDir) and \(cfg.launchAgentsDir)")
        print(planText(cfg), terminator: "")
        try runInstall(cfg: cfg, run: realRun)
        exit(0)
    } catch {
        print("dry-run failed: \(error)")
        exit(1)
    }
} else {
    runGUI(cfg: cfg)
}
