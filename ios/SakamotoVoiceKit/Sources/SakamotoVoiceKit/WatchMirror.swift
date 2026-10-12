import Foundation

/// A message the phone mirrors to its Apple Watch app, over WatchConnectivity (as a property-list
/// dictionary) and in the local notification it posts for the watch (as the notification's
/// `userInfo`), so the watch can show it and read it in its own voices.
///
///     {"kind": "message", "v": 1, "id": "…", "date": 781234567.0, "text": "Hello. そうやで。",
///      "runs": [{"lang": "default", "text": "Hello."}, {"lang": "ja", "text": "そうやで。"}],
///      "source": "text", "defaultLang": "en", "rate": 0.5}
///
/// `runs` are as the phone got them from the Mac (markers already applied); `defaultLang` ("en"
/// or "ja") is the phone's Default Voice for Other Text, for "default" runs, and `rate` its
/// speech rate (AVSpeechUtterance's, 0 to 1).
public struct MirroredMessage: Codable, Equatable, Identifiable, Sendable {
    public enum Source: String, Codable, Sendable {
        /// Text the phone read in its own voices.
        case text
        /// Audio the Mac rendered in its voices.
        case macAudio
        /// The Claude app's own voice, streamed to the phone.
        case appStream
    }

    public static let kind = "message"
    public static let formatVersion = 1
    /// The notification category the phone posts with and the watch shows (with its Speak action).
    public static let notificationCategory = "com.pragmaphilia.SakamotoVoice.message"
    public static let speakAction = "speak"
    /// The notification's title.
    public static let notificationTitle = "Miss Sakamoto"
    /// The longest notification body; the watch app shows (and reads) the whole text.
    public static let notificationBodyLimit = 1_000

    public var id: String
    public var date: Date
    public var text: String
    public var runs: [LangRun]
    public var source: Source
    public var defaultLang: String
    public var rate: Float

    public init(id: String = UUID().uuidString, date: Date = Date(), text: String, runs: [LangRun]? = nil,
                source: Source = .text, defaultLang: String = "en", rate: Float = 0.5) {
        self.id = id
        self.date = date
        self.text = text
        self.runs = runs ?? VoiceMarkers.runs(in: text)
        self.source = source
        self.defaultLang = defaultLang == "ja" ? "ja" : "en"
        self.rate = rate
    }

    /// Whether "default" runs are read in the Japanese voice.
    public var defaultIsJapanese: Bool { defaultLang == "ja" }

    /// The text for the screen and the notification: without markers, trimmed.
    public var shownText: String { VoiceMarkers.strip(text) }

    /// The notification's body: the shown text, cut at `limit` characters with an ellipsis.
    public func notificationBody(limit: Int = MirroredMessage.notificationBodyLimit) -> String {
        let shown = shownText
        guard shown.count > limit, limit > 1 else { return shown }
        return String(shown.prefix(limit - 1)).trimmingCharacters(in: .whitespacesAndNewlines) + "…"
    }

    // MARK: - As a property list

    /// Property-list types only, for WatchConnectivity and a notification's userInfo.
    public var dictionary: [String: Any] {
        [
            "kind": Self.kind,
            "v": Self.formatVersion,
            "id": id,
            "date": date.timeIntervalSinceReferenceDate,
            "text": text,
            "runs": runs.map { ["lang": $0.lang, "text": $0.text] },
            "source": source.rawValue,
            "defaultLang": defaultLang,
            "rate": Double(rate),
        ]
    }

    /// A message from a dictionary made by `dictionary`; nil when it isn't one. Missing runs are
    /// made from the text (with its markers); an unknown source is `text`.
    public init?(dictionary: [String: Any]) {
        guard dictionary["kind"] as? String == Self.kind,
              let id = dictionary["id"] as? String, !id.isEmpty,
              let text = dictionary["text"] as? String
        else { return nil }
        let date = (dictionary["date"] as? Double).map(Date.init(timeIntervalSinceReferenceDate:)) ?? Date()
        let runs = (dictionary["runs"] as? [[String: String]])?.compactMap { run -> LangRun? in
            guard let text = run["text"] else { return nil }
            return LangRun(lang: run["lang"] ?? LangRun.phoneDefault, text: text)
        }
        let source = (dictionary["source"] as? String).flatMap(Source.init(rawValue:)) ?? .text
        let rate = (dictionary["rate"] as? Double).map(Float.init) ?? 0.5
        self.init(id: id, date: date, text: text, runs: runs?.isEmpty == false ? runs : nil, source: source,
                  defaultLang: dictionary["defaultLang"] as? String ?? "en", rate: rate)
    }

    // MARK: - The watch's list

    /// `history` (newest first) with `message` in its place by date, unless it's there already
    /// (a message can come twice: by WatchConnectivity and with its notification), and no longer
    /// than `limit`.
    public static func inserting(_ message: MirroredMessage, into history: [MirroredMessage],
                                 limit: Int) -> [MirroredMessage] {
        guard !history.contains(where: { $0.id == message.id }) else { return history }
        var list = history
        let index = list.firstIndex { $0.date < message.date } ?? list.endIndex
        list.insert(message, at: index)
        return Array(list.prefix(max(0, limit)))
    }

    /// Whether a message that has just arrived is fresh enough to read aloud unasked: one queued
    /// for a while (the watch was out of reach) is only listed.
    public func isFresh(at now: Date = Date(), within seconds: TimeInterval = 120) -> Bool {
        now.timeIntervalSince(date) <= seconds
    }
}
