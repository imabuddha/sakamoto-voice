import Foundation

/// The phone's Claude's Voice setting: whether it takes the Claude app's voice streamed from the
/// Mac (about 48 KB/s) or has the Mac send only the text, which it reads in its own voices.
public enum VoicePolicy: String, CaseIterable, Identifiable, Sendable {
    /// Always take the stream when the Mac offers it.
    case stream
    /// The stream on Wi-Fi or a wired network; the text on cellular data or another expensive
    /// path, such as a Personal Hotspot (the default).
    case textOnCellular
    /// Always the text.
    case textOnly

    public static let `default` = VoicePolicy.textOnCellular

    public var id: String { rawValue }

    /// What the phone wants, given whether its network path is cellular (or otherwise expensive).
    public func want(onCellular: Bool) -> VoiceWant {
        switch self {
        case .stream: .stream
        case .textOnCellular: onCellular ? .text : .stream
        case .textOnly: .text
        }
    }
}

/// The setting and the network path, kept together and read from any thread: the receiver asks
/// for `want` each time it answers, so its answer is current at that moment.
public final class VoicePreference: @unchecked Sendable {
    private let lock = NSLock()
    private var _policy: VoicePolicy
    private var _onCellular: Bool

    public init(policy: VoicePolicy = .default, onCellular: Bool = false) {
        _policy = policy
        _onCellular = onCellular
    }

    public var policy: VoicePolicy {
        get { lock.withLock { _policy } }
        set { lock.withLock { _policy = newValue } }
    }

    /// Whether the phone's current network path is cellular or otherwise expensive.
    public var onCellular: Bool {
        get { lock.withLock { _onCellular } }
        set { lock.withLock { _onCellular = newValue } }
    }

    public var want: VoiceWant {
        lock.withLock { _policy.want(onCellular: _onCellular) }
    }
}
