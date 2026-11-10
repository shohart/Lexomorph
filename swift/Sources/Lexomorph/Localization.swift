import Foundation

enum InterfaceLanguage: String, CaseIterable {
    case russian = "ru"
    case english = "en"
}

extension InterfaceLanguage {
    /// English is the base language; Russian is chosen when the system's
    /// first preferred language is Russian. A language the user picked in
    /// the app (stored `interface_language`) always wins over this.
    static func systemDefault(preferredLanguages: [String] = Locale.preferredLanguages) -> InterfaceLanguage {
        guard let first = preferredLanguages.first?.lowercased() else { return .english }
        return (first == "ru" || first.hasPrefix("ru-") || first.hasPrefix("ru_")) ? .russian : .english
    }

    /// Resolved once per process: the system language does not change under a running app.
    static let resolvedSystemDefault: InterfaceLanguage = systemDefault()
}

func localizedText(_ russian: String,
                   _ english: String,
                   language: InterfaceLanguage) -> String {
    language == .russian ? russian : english
}
