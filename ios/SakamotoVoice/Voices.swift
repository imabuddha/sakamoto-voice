import AVFoundation

/// The installed voices the app can use. Siri voices aren't among them: Apple doesn't let other
/// apps use those.
enum Voices {
    /// Installed voices whose language starts with `prefix` ("en", "ja"), best quality first,
    /// without novelty voices (Bells, Bubbles, ...) or Personal Voices.
    static func installed(_ prefix: String) -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix(prefix) }
            .filter { !$0.voiceTraits.contains(.isNoveltyVoice) && !$0.voiceTraits.contains(.isPersonalVoice) }
            .sorted { a, b in
                if a.language != b.language { return a.language < b.language }
                if a.name != b.name { return a.name < b.name }
                return a.quality.rawValue > b.quality.rawValue
            }
    }

    /// The best-quality installed voice with this name (and language, when given).
    static func best(named name: String, language: String? = nil) -> AVSpeechSynthesisVoice? {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { voice in voice.name == name && (language.map { voice.language.hasPrefix($0) } ?? true) }
            .max { $0.quality.rawValue < $1.quality.rawValue }
    }

    static func bestForLanguage(_ language: String) -> AVSpeechSynthesisVoice? {
        installed(language).max { $0.quality.rawValue < $1.quality.rawValue }
    }

    /// Moira (Irish English), the best quality installed; then any Irish voice; then the system's.
    static var defaultEnglish: AVSpeechSynthesisVoice? {
        best(named: "Moira", language: "en") ?? bestForLanguage("en-IE") ?? AVSpeechSynthesisVoice(language: "en-US")
    }

    /// Kyoko, the best quality installed; then any Japanese voice.
    static var defaultJapanese: AVSpeechSynthesisVoice? {
        best(named: "Kyoko", language: "ja") ?? bestForLanguage("ja-JP") ?? AVSpeechSynthesisVoice(language: "ja-JP")
    }

    static func english(_ id: String) -> AVSpeechSynthesisVoice? {
        (id.isEmpty ? nil : AVSpeechSynthesisVoice(identifier: id)) ?? defaultEnglish
    }

    static func japanese(_ id: String) -> AVSpeechSynthesisVoice? {
        (id.isEmpty ? nil : AVSpeechSynthesisVoice(identifier: id)) ?? defaultJapanese
    }

    /// "Moira (Enhanced), Ireland".
    static func label(_ voice: AVSpeechSynthesisVoice) -> String {
        var name = voice.name
        if !name.contains("(") {
            switch voice.quality {
            case .premium: name += " (Premium)"
            case .enhanced: name += " (Enhanced)"
            default: break
            }
        }
        let region = voice.language.split(separator: "-").dropFirst().first.map(String.init)
        if let region, let place = Locale.current.localizedString(forRegionCode: region) {
            return "\(name), \(place)"
        }
        return name
    }
}
