import AVFoundation
import Observation
import SakamotoVoiceKit

/// Reads a message aloud on the watch with AVSpeechSynthesizer: Japanese runs (Japanese script,
/// 〔ja〕 text, and "default" runs when the phone's default voice is Japanese) in a Japanese voice,
/// the rest in an English one, at the phone's rate.
///
/// The audio session is the ordinary kind (playback, spoken audio, the default route policy), not
/// long-form, so it plays on the watch's own speaker (or connected Bluetooth audio) while the app
/// is in front; watchOS gives background playback only to long-form audio, which needs a
/// Bluetooth route.
@MainActor @Observable
final class WatchSpeaker: NSObject {
    private(set) var isSpeaking = false

    @ObservationIgnored private let synthesizer = AVSpeechSynthesizer()

    override init() {
        super.init()
        synthesizer.delegate = self
        synthesizer.usesApplicationAudioSession = true
    }

    func speak(_ message: MirroredMessage) {
        stop()
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, policy: .default, options: [])
        try? session.setActive(true)
        let english = Self.englishVoice
        let japanese = Self.japaneseVoice
        let rate = min(max(message.rate, AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)
        for run in message.runs {
            let utterance = AVSpeechUtterance(string: run.text)
            utterance.voice = run.isJapanese(byDefault: message.defaultIsJapanese) ? japanese : english
            utterance.rate = rate
            synthesizer.speak(utterance)
        }
        isSpeaking = !message.runs.isEmpty
    }

    func stop() {
        if synthesizer.isSpeaking || synthesizer.isPaused {
            synthesizer.stopSpeaking(at: .immediate)
        }
        isSpeaking = false
    }

    private func refresh() {
        isSpeaking = synthesizer.isSpeaking
        if !isSpeaking {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    /// The voices chosen in the app's Voices section (identifiers; empty: the best installed).
    static let englishChoiceKey = "englishVoiceID", japaneseChoiceKey = "japaneseVoiceID"

    private static func chosen(_ key: String) -> AVSpeechSynthesisVoice? {
        guard let id = UserDefaults.standard.string(forKey: key), !id.isEmpty else { return nil }
        return AVSpeechSynthesisVoice(identifier: id)
    }

    /// The installed voices for a language, best first, for the Voices pickers.
    static func voices(_ prefix: String) -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix(prefix) }
            .filter { !$0.voiceTraits.contains(.isNoveltyVoice) && !$0.voiceTraits.contains(.isPersonalVoice) }
            .sorted { ($0.quality.rawValue, $0.name) > ($1.quality.rawValue, $1.name) }
    }

    /// The chosen English voice, else the best installed one for the watch's own English, else any.
    static var englishVoice: AVSpeechSynthesisVoice? {
        if let voice = chosen(englishChoiceKey) { return voice }
        let current = AVSpeechSynthesisVoice.currentLanguageCode()
        return best(current.hasPrefix("en") ? current : "en") ?? best("en")
            ?? AVSpeechSynthesisVoice(language: "en-US")
    }

    /// The best installed Japanese voice (nil when the watch has none: then the system's default
    /// voice reads Japanese runs).
    static var japaneseVoice: AVSpeechSynthesisVoice? {
        chosen(japaneseChoiceKey) ?? best("ja") ?? AVSpeechSynthesisVoice(language: "ja-JP")
    }

    private static func best(_ prefix: String) -> AVSpeechSynthesisVoice? {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix(prefix) }
            .filter { !$0.voiceTraits.contains(.isNoveltyVoice) && !$0.voiceTraits.contains(.isPersonalVoice) }
            .max { $0.quality.rawValue < $1.quality.rawValue }
    }
}

extension WatchSpeaker: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.refresh() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.refresh() }
    }
}
