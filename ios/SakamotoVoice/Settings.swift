import Foundation
import Observation
import SakamotoVoiceKit

/// The voice for text that is neither Japanese script nor marked 〔en〕 or 〔ja〕 by the Mac.
enum DefaultVoice: String, CaseIterable, Identifiable {
    case english = "en", japanese = "ja"

    var id: String { rawValue }
    var isJapanese: Bool { self == .japanese }
}

/// The app's settings, kept in UserDefaults.
@MainActor @Observable
final class Settings {
    private let defaults: UserDefaults

    /// The 6-digit code the Mac must send; kept across launches so the Mac stays paired.
    var pairingCode: String { didSet { defaults.set(pairingCode, forKey: Key.pairingCode) } }
    /// AVSpeechSynthesisVoice identifiers; empty picks the default (Moira, Kyoko).
    var englishVoiceID: String { didSet { defaults.set(englishVoiceID, forKey: Key.englishVoice) } }
    var japaneseVoiceID: String { didSet { defaults.set(japaneseVoiceID, forKey: Key.japaneseVoice) } }
    /// The voice for other text (the Mac's "default" runs, and text it didn't split); English
    /// unless chosen otherwise.
    var defaultVoice: DefaultVoice { didSet { defaults.set(defaultVoice.rawValue, forKey: Key.defaultVoice) } }
    /// AVSpeechUtterance's rate (0 to 1; 0.5 is the voice's normal pace).
    var rate: Float { didSet { defaults.set(rate, forKey: Key.rate) } }
    /// Keep running in the background with the silent keep-alive sound.
    var stayAwake: Bool { didSet { defaults.set(stayAwake, forKey: Key.stayAwake) } }
    /// Stay awake only between these times (minutes after midnight).
    var useSchedule: Bool { didSet { defaults.set(useSchedule, forKey: Key.useSchedule) } }
    var scheduleStart: Int { didSet { defaults.set(scheduleStart, forKey: Key.scheduleStart) } }
    var scheduleEnd: Int { didSet { defaults.set(scheduleEnd, forKey: Key.scheduleEnd) } }
    /// Keep the screen from sleeping while the app is open (the stand).
    var keepScreenOn: Bool { didSet { defaults.set(keepScreenOn, forKey: Key.keepScreenOn) } }

    enum Key {
        static let pairingCode = "pairingCode"
        static let englishVoice = "englishVoice"
        static let japaneseVoice = "japaneseVoice"
        static let defaultVoice = "defaultVoice"
        static let rate = "rate"
        static let stayAwake = "stayAwake"
        static let useSchedule = "useSchedule"
        static let scheduleStart = "scheduleStart"
        static let scheduleEnd = "scheduleEnd"
        static let keepScreenOn = "keepScreenOn"
    }

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        defaults.register(defaults: [
            Key.defaultVoice: DefaultVoice.english.rawValue,
            Key.rate: 0.5,
            Key.stayAwake: true,
            Key.useSchedule: false,
            Key.scheduleStart: 7 * 60,
            Key.scheduleEnd: 23 * 60,
            Key.keepScreenOn: true,
        ])
        var code = defaults.string(forKey: Key.pairingCode) ?? ""
        if !PairingCode.isValid(code) {
            code = PairingCode.generate()
            defaults.set(code, forKey: Key.pairingCode)
        }
        pairingCode = code
        englishVoiceID = defaults.string(forKey: Key.englishVoice) ?? ""
        japaneseVoiceID = defaults.string(forKey: Key.japaneseVoice) ?? ""
        defaultVoice = DefaultVoice(rawValue: defaults.string(forKey: Key.defaultVoice) ?? "") ?? .english
        rate = defaults.float(forKey: Key.rate)
        stayAwake = defaults.bool(forKey: Key.stayAwake)
        useSchedule = defaults.bool(forKey: Key.useSchedule)
        scheduleStart = defaults.integer(forKey: Key.scheduleStart)
        scheduleEnd = defaults.integer(forKey: Key.scheduleEnd)
        keepScreenOn = defaults.bool(forKey: Key.keepScreenOn)
    }

    var schedule: DailySchedule {
        DailySchedule(startMinute: scheduleStart, endMinute: scheduleEnd)
    }

    var keepAlivePolicy: KeepAlivePolicy {
        KeepAlivePolicy(stayAwake: stayAwake, useSchedule: useSchedule, schedule: schedule)
    }
}
