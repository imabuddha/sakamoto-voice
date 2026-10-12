import Foundation

/// The wire protocol between the Mac (plugin/scripts/speak.py, mac/AppVoiceTap) and the phone.
///
/// One message per TCP connection: the sender writes one JSON object and closes its side for
/// writing; the phone reads to the end, answers with one JSON `Ack` line, and closes. The service
/// is advertised with Bonjour as `_sakamotovoice._tcp`.
///
///     {"token": "123456", "kind": "text", "text": "Hello. そうやで。",
///      "lang_runs": [{"lang": "default", "text": "Hello."}, {"lang": "ja", "text": "そうやで。"}]}
///     {"token": "123456", "kind": "audio", "audio_b64": "...", "format": "m4a", "text": "Hello."}
///     {"token": "123456", "kind": "ping"}      checks the pairing; says nothing
///     {"token": "123456", "kind": "stop"}      silences the phone (and ends a stream)
///
/// **Streams** (0.3.0) carry live audio, such as the Claude app's own voice as it plays on the Mac
/// (`app-voice-tap`). The header is one JSON line, ended by a newline (0x0A), and the audio
/// follows on the same connection:
///
///     {"channels":1,"format":"pcm16","kind":"stream","rate":24000,"text":"Hello.","token":"123456"}\n
///     <raw PCM: 16-bit signed little-endian samples, channels interleaved, `rate` frames a second,
///      until the sender closes its side>
///
/// `format` must be "pcm16"; `rate` (8000 to 96000) defaults to 24000 and `channels` (1 or 2) to 1;
/// `text` is optional, for the screen. The phone answers the header at once with its `Ack` line,
/// so the sender knows before it sends any audio (after a refusal the phone closes). It plays the
/// audio as it arrives, through a short jitter buffer, and closes the connection once the sender
/// has closed its side. A newer text, audio, stream, or stop message ends a stream still running
/// (the phone closes that connection); a ping doesn't. A stream that sends nothing for
/// `streamIdleTimeout` is closed.
///
/// Telling them apart: a connection whose bytes up to the first newline decode as a message of
/// kind "stream" is a stream; anything else is read whole as before (so a one-line message with a
/// newline after it is still an ordinary message). Phones before 0.3.0 never answer a stream's
/// header (they wait for the sender to close), so the sender gives up on them.
///
/// **Voice or text** (1.0). Only the Mac opens connections, so the phone states what it wants in
/// its answers: every answer to a message with the right pairing code carries `"voice"`, either
/// "stream" (stream the Claude app's voice when you can) or "text" (send only the text, to save
/// mobile data), from the phone's Claude's Voice setting and its network path at that moment.
/// Answers that refuse the code (or a message that couldn't be read) don't say. A stream's header
/// that arrives while the phone wants text is declined, which isn't an error: the answer has
/// `"ok": false`, no `error`, and `"want": "text"`, the phone closes the connection, and the
/// sender sends the text instead (an ordinary text message, on a new connection):
///
///     {"app":"Sakamoto Voice","ok":true,"version":"1.0","voice":"stream"}
///     {"app":"Sakamoto Voice","ok":false,"version":"1.0","voice":"text","want":"text"}
///
/// Phones before 1.0 never send `voice`; a sender treats their answers as "stream".
public enum VoiceProtocol {
    public static let serviceType = "_sakamotovoice._tcp"
    /// The port the phone asks for first, so a cached "host:port" on the Mac survives restarts;
    /// any free port when it's taken (Bonjour finds it either way).
    public static let preferredPort: UInt16 = 47811
    /// Audio is base64 in JSON; this is roughly ten minutes of AAC speech.
    public static let maxMessageBytes = 32 * 1024 * 1024
    public static let appName = "Sakamoto Voice"
    /// A stream's only audio format: 16-bit signed little-endian PCM.
    public static let streamFormat = "pcm16"
    public static let defaultStreamRate = 24_000
    /// A header line is looked for only this far into a connection (beyond it, it's a message).
    public static let maxStreamHeaderBytes = 1 << 20
    /// A stream that sends nothing for this long is closed.
    public static let streamIdleTimeout: TimeInterval = 20
}

/// A run of text in one voice. From the Mac (0.2.5 and later), `lang` is "ja" for Japanese script
/// and for text marked 〔ja〕, "en" for text marked 〔en〕, and "default" for everything else, which
/// the phone's own setting (Default Voice for Other Text) assigns. Anything starting with "ja" is
/// spoken by the Japanese voice; "default" (or no tag) by the phone's default voice; anything else
/// by the English one. (Phones before 0.2.5 read "default" in English, their only default.)
public struct LangRun: Codable, Equatable, Sendable {
    /// The tag for text in no particular voice: the phone's setting decides.
    public static let phoneDefault = "default"

    public var lang: String
    public var text: String

    public init(lang: String, text: String) {
        self.lang = lang
        self.text = text
    }

    /// Whether the Japanese voice speaks this run, given the phone's default voice.
    public func isJapanese(byDefault defaultIsJapanese: Bool) -> Bool {
        let lang = lang.lowercased()
        if lang.hasPrefix("ja") { return true }
        if lang == Self.phoneDefault || lang.isEmpty { return defaultIsJapanese }
        return false
    }
}

/// A message as it arrives, before the token check and validation.
public struct VoiceMessage: Codable, Equatable, Sendable {
    public enum Kind: String, Codable, Sendable {
        case text, audio, ping, stop, stream
    }

    public var token: String
    public var kind: Kind
    public var text: String?
    public var langRuns: [LangRun]?
    public var audioB64: String?
    public var format: String?
    /// A stream's frames per second and channels.
    public var rate: Int?
    public var channels: Int?

    public init(token: String, kind: Kind, text: String? = nil, langRuns: [LangRun]? = nil,
                audioB64: String? = nil, format: String? = nil, rate: Int? = nil, channels: Int? = nil) {
        self.token = token
        self.kind = kind
        self.text = text
        self.langRuns = langRuns
        self.audioB64 = audioB64
        self.format = format
        self.rate = rate
        self.channels = channels
    }

    enum CodingKeys: String, CodingKey {
        case token, kind, text, format, rate, channels
        case langRuns = "lang_runs"
        case audioB64 = "audio_b64"
    }

    /// A stream's header line, newline included, as the Mac sends it.
    public static func streamHeader(token: String, text: String? = nil, rate: Int = VoiceProtocol.defaultStreamRate,
                                    channels: Int = 1) -> Data {
        let text = text.flatMap { $0.isEmpty ? nil : $0 }
        let message = VoiceMessage(token: token, kind: .stream, text: text, format: VoiceProtocol.streamFormat,
                                   rate: rate, channels: channels)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        var data = (try? encoder.encode(message)) ?? Data()
        data.append(0x0A)
        return data
    }
}

/// A stream the phone accepted: its number (the server counts them), its format, and its text for
/// the screen (may be empty).
public struct StreamInfo: Equatable, Sendable {
    public var id: Int
    public var sampleRate: Int
    public var channels: Int
    public var text: String

    public init(id: Int, sampleRate: Int, channels: Int, text: String) {
        self.id = id
        self.sampleRate = sampleRate
        self.channels = channels
        self.text = text
    }

    public var bytesPerFrame: Int { 2 * channels }
}

/// A checked message, ready to act on.
public enum Incoming: Equatable, Sendable {
    /// Text to speak, already split into language runs, and the whole text for the screen.
    case text(String, runs: [LangRun])
    /// Audio the Mac rendered (`say -o`), its file type ("m4a", "wav", ...), and its text for the
    /// screen (may be empty).
    case audio(Data, format: String, text: String)
    case ping
    case stop
    /// A stream began (its header was accepted); audio follows.
    case streamStart(StreamInfo)
    /// A stream's audio, in whole frames (16-bit little-endian PCM, channels interleaved).
    case streamAudio(id: Int, Data)
    /// The sender closed the stream (or it failed or went idle). A stream ended by a newer
    /// message gets no `streamEnd`: the newer message replaces it.
    case streamEnd(id: Int)
}

public enum MessageError: Error, Equatable, Sendable {
    case malformed, tooLarge, badToken, lockedOut, noText, badAudio, badStream

    /// The ack's `error` string.
    public var code: String {
        switch self {
        case .malformed: "malformed"
        case .tooLarge: "too large"
        case .badToken: "bad token"
        case .lockedOut: "locked out"
        case .noText: "no text"
        case .badAudio: "bad audio"
        case .badStream: "bad stream"
        }
    }
}

/// What the phone wants from the Mac for the Claude app's voice, as it says in its answers
/// (`"voice"`, and a declined stream's `"want"`).
public enum VoiceWant: String, Codable, Sendable {
    /// Stream the Claude app's voice when it's offered.
    case stream
    /// Send only the text (the phone reads it in its own voices).
    case text
}

/// The phone's answer: one JSON line.
public struct Ack: Codable, Equatable, Sendable {
    public var ok: Bool
    public var error: String?
    public var app: String
    public var version: String
    /// What the phone wants now (1.0 and later; nil when the pairing code was refused).
    public var voice: VoiceWant?
    /// Set when a stream's header is declined because the phone wants the text instead.
    public var want: VoiceWant?

    public init(ok: Bool, error: String? = nil, app: String = VoiceProtocol.appName, version: String,
                voice: VoiceWant? = nil, want: VoiceWant? = nil) {
        self.ok = ok
        self.error = error
        self.app = app
        self.version = version
        self.voice = voice
        self.want = want
    }

    public static func success(version: String, voice: VoiceWant? = nil) -> Ack {
        Ack(ok: true, version: version, voice: voice)
    }

    public static func failure(_ error: MessageError, version: String, voice: VoiceWant? = nil) -> Ack {
        Ack(ok: false, error: error.code, version: version, voice: voice)
    }

    /// A stream's header declined, not an error: the phone wants the text instead.
    public static func wantsText(version: String) -> Ack {
        Ack(ok: false, version: version, voice: .text, want: .text)
    }

    public func encoded() -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        var data = (try? encoder.encode(self)) ?? Data("{\"ok\":false}".utf8)
        data.append(0x0A)
        return data
    }
}

public enum MessageDecoder {
    public static func decode(_ data: Data) throws(MessageError) -> VoiceMessage {
        guard data.count <= VoiceProtocol.maxMessageBytes else { throw .tooLarge }
        do {
            return try JSONDecoder().decode(VoiceMessage.self, from: data)
        } catch {
            throw .malformed
        }
    }

    /// Checks a message's content (not its token) and turns it into something to act on. Text
    /// without runs is split here, by script: Japanese script is "ja" and the rest is left to the
    /// phone's default voice ("default").
    public static func validate(_ message: VoiceMessage) throws(MessageError) -> Incoming {
        switch message.kind {
        case .ping:
            return .ping
        case .stop:
            return .stop
        case .text:
            let text = (message.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            var runs = (message.langRuns ?? []).filter {
                !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
            if runs.isEmpty {
                runs = LanguageSplitter.runs(in: text, other: LangRun.phoneDefault)
            }
            guard !runs.isEmpty else { throw .noText }
            let shown = text.isEmpty ? runs.map(\.text).joined(separator: " ") : text
            return .text(shown, runs: runs)
        case .audio:
            guard let b64 = message.audioB64,
                  let data = Data(base64Encoded: b64, options: .ignoreUnknownCharacters),
                  !data.isEmpty
            else { throw .badAudio }
            let format = (message.format ?? "m4a").lowercased()
            let text = (message.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return .audio(data, format: format, text: text)
        case .stream:
            // A stream's header ends its line, with the audio after it; read whole, it isn't one.
            throw .badStream
        }
    }

    /// Checks a stream's header (not its token). Its id is 0; the server numbers streams.
    public static func validateStream(_ message: VoiceMessage) throws(MessageError) -> StreamInfo {
        guard message.kind == .stream,
              (message.format ?? VoiceProtocol.streamFormat).lowercased() == VoiceProtocol.streamFormat
        else { throw .badStream }
        let rate = message.rate ?? VoiceProtocol.defaultStreamRate
        let channels = message.channels ?? 1
        guard (8_000...96_000).contains(rate), (1...2).contains(channels) else { throw .badStream }
        let text = (message.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return StreamInfo(id: 0, sampleRate: rate, channels: channels, text: text)
    }
}
