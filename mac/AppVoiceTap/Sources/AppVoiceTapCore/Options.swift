import Foundation
import SakamotoVoiceKit

/// app-voice-tap's command line.
public struct Options: Equatable, Sendable {
    public enum Mode: Equatable, Sendable {
        /// Tap the Claude app and stream it to the phone (the default).
        case stream
        /// Ask for the System Audio Recording permission now (shows macOS's prompt once).
        case check
        /// List the processes Core Audio knows, marking the Claude app's.
        case list
        case help
    }

    public var mode: Mode = .stream
    public var host = ""
    public var port: UInt16 = 0
    public var token = ""
    /// Silence the Claude app on the Mac's speakers while it's tapped.
    public var mute = false
    public var maxSeconds = 600.0
    /// This much continuous silence after the audio began ends the stream.
    public var silenceSeconds = 2.5
    /// The audio must begin within this many seconds of "ready".
    public var waitStart = 6.0
    /// The stream's frames per second (mono, 16-bit).
    public var rate = VoiceProtocol.defaultStreamRate
    /// Quieter than this is silence.
    public var thresholdDB = -60.0
    /// The response's text, for the phone's screen.
    public var text: String?
    public var textFromStdin = false
    /// Processes running from inside this app bundle are tapped...
    public var appPath = "/Applications/Claude.app"
    /// ...and so are processes with these bundle IDs (or IDs that start with one and a dot).
    public var bundleIDs = ["com.anthropic.claudefordesktop"]
    /// On macOS 26 and later, also name the bundle IDs in the tap, so helper processes that start
    /// later are tapped from their first sound.
    public var tapByBundleID = true
    /// Include the default output device in the aggregate device (for its clock), as is usual.
    public var outputSubdevice = true
    /// Re-launch as a process responsible for itself, so macOS's privacy check names
    /// app-voice-tap rather than whatever app launched it.
    public var disclaim = true
    public var permissionCheck = true
    public var verbose = false

    public init() {}

    public static let usage = """
        app-voice-tap: streams the Claude desktop app's audio, live, to the Sakamoto Voice app on an iPhone.

        Usage:
          app-voice-tap --to HOST:PORT --token CODE [options]
          app-voice-tap --check      ask for the System Audio Recording permission now
          app-voice-tap --list       list the processes Core Audio knows (the Claude app's marked)

        It taps the Claude app's processes, connects to the phone, prints "ready", waits for the app
        to start playing, streams until the app has been silent for a while, and exits.

        Options:
          --mute                 silence the Claude app on the Mac's speakers while tapping
          --max-seconds S        stop after S seconds of streaming (600)
          --silence-seconds S    end after S seconds of continuous silence (2.5)
          --wait-start S         give up when no sound begins within S seconds of "ready" (6)
          --rate HZ              the stream's sample rate, mono 16-bit (24000)
          --threshold-db DB      quieter than DB dBFS is silence (-60)
          --text TEXT            the response's text, for the phone's screen
          --text-stdin           read that text from standard input
          --app PATH             the app whose processes are tapped (/Applications/Claude.app)
          --bundle-id ID         tap processes with this bundle ID too (repeatable; default
                                 com.anthropic.claudefordesktop and its helpers)
          --no-bundle-id-tap     don't name bundle IDs in the tap (macOS 26+), only processes
          --no-output-subdevice  an aggregate device of the tap alone
          --no-disclaim          don't re-launch as its own responsible process
          --no-permission-check  don't look at the permission first
          --verbose              say more on standard error

        Exit status: 0 streamed (or stopped); 2 usage; 3 permission; 4 the phone; 5 the tap;
        6 no sound began in time.
        """

    public enum ParseError: Error, Equatable, CustomStringConvertible {
        case missing(String)
        case badValue(String, String)
        case unknown(String)

        public var description: String {
            switch self {
            case .missing(let what): "missing \(what)"
            case .badValue(let option, let value): "bad value for \(option): \(value)"
            case .unknown(let option): "unknown option \(option)"
            }
        }
    }

    public static func parse(_ arguments: [String]) throws(ParseError) -> Options {
        var options = Options()
        var customBundleIDs: [String] = []
        var i = 0
        func value(_ option: String) throws(ParseError) -> String {
            i += 1
            guard i < arguments.count else { throw .missing("a value for \(option)") }
            return arguments[i]
        }
        func seconds(_ option: String) throws(ParseError) -> Double {
            let text = try value(option)
            guard let number = Double(text), number > 0, number.isFinite else { throw .badValue(option, text) }
            return number
        }
        while i < arguments.count {
            let argument = arguments[i]
            switch argument {
            case "--to":
                let text = try value(argument)
                guard let (host, port) = splitAddress(text) else { throw .badValue(argument, text) }
                options.host = host
                options.port = port
            case "--token":
                let text = try value(argument)
                let code = PairingCode.normalize(text)
                guard PairingCode.isValid(code) else { throw .badValue(argument, text) }
                options.token = code
            case "--mute": options.mute = true
            case "--max-seconds": options.maxSeconds = try seconds(argument)
            case "--silence-seconds": options.silenceSeconds = try seconds(argument)
            case "--wait-start": options.waitStart = try seconds(argument)
            case "--rate":
                let text = try value(argument)
                guard let rate = Int(text), (8_000...96_000).contains(rate) else { throw .badValue(argument, text) }
                options.rate = rate
            case "--threshold-db":
                let text = try value(argument)
                guard let db = Double(text), db < 0 else { throw .badValue(argument, text) }
                options.thresholdDB = db
            case "--text": options.text = try value(argument)
            case "--text-stdin": options.textFromStdin = true
            case "--app": options.appPath = try value(argument)
            case "--bundle-id": customBundleIDs.append(try value(argument))
            case "--no-bundle-id-tap": options.tapByBundleID = false
            case "--no-output-subdevice": options.outputSubdevice = false
            case "--no-disclaim": options.disclaim = false
            case "--no-permission-check": options.permissionCheck = false
            case "--verbose", "-v": options.verbose = true
            case "--check": options.mode = .check
            case "--list": options.mode = .list
            case "--help", "-h": options.mode = .help
            default: throw .unknown(argument)
            }
            i += 1
        }
        if !customBundleIDs.isEmpty { options.bundleIDs += customBundleIDs }
        if options.mode == .stream {
            if options.host.isEmpty { throw .missing("--to HOST:PORT") }
            if options.token.isEmpty { throw .missing("--token CODE") }
        }
        return options
    }

    /// "host:port" (the host may itself contain colons, as an IPv6 address does).
    public static func splitAddress(_ text: String) -> (String, UInt16)? {
        guard let colon = text.lastIndex(of: ":") else { return nil }
        var host = String(text[..<colon])
        if host.hasPrefix("["), host.hasSuffix("]") { host = String(host.dropFirst().dropLast()) }
        guard !host.isEmpty, let port = UInt16(text[text.index(after: colon)...]), port > 0 else { return nil }
        return (host, port)
    }
}
