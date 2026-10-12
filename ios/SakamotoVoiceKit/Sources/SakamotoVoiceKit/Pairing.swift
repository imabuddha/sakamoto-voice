import Foundation

/// The 6-digit code the phone shows and the Mac sends as `token`.
public enum PairingCode {
    public static let length = 6

    public static func generate() -> String {
        var rng = SystemRandomNumberGenerator()
        return generate(using: &rng)
    }

    public static func generate<G: RandomNumberGenerator>(using rng: inout G) -> String {
        String((0..<length).map { _ in Character(String(Int.random(in: 0...9, using: &rng))) })
    }

    /// Only the digits, so "123 456" and "123-456" are "123456".
    public static func normalize(_ code: String) -> String {
        String(code.unicodeScalars.filter { ("0"..."9").contains($0) }.map(Character.init))
    }

    public static func isValid(_ code: String) -> Bool {
        let digits = normalize(code)
        return digits.count == length && digits == code.filter { !$0.isWhitespace && $0 != "-" }
    }

    /// "123 456", for reading off the screen.
    public static func display(_ code: String) -> String {
        let digits = normalize(code)
        guard digits.count == length else { return digits }
        return "\(digits.prefix(3)) \(digits.suffix(3))"
    }

    /// Compares in time that doesn't depend on where the codes differ. An empty expected code
    /// matches nothing.
    public static func matches(_ given: String, expected: String) -> Bool {
        let a = Array(normalize(given).utf8)
        let b = Array(normalize(expected).utf8)
        guard !b.isEmpty, a.count == b.count else { return false }
        var difference: UInt8 = 0
        for (x, y) in zip(a, b) {
            difference |= x ^ y
        }
        return difference == 0
    }
}

/// Throttles guessing: a 6-digit code is a million tries, quick on a local network without this.
/// After `maxFailures` wrong codes within `window` seconds, every message is refused for
/// `lockout` seconds (the right code too, so a guesser learns nothing while locked out).
public struct TokenGate: Sendable {
    public enum Verdict: Equatable, Sendable {
        case accepted, rejected, lockedOut
    }

    public var maxFailures: Int
    public var window: TimeInterval
    public var lockout: TimeInterval
    private var failures: [Date] = []
    private var lockedUntil: Date?

    public init(maxFailures: Int = 10, window: TimeInterval = 60, lockout: TimeInterval = 60) {
        self.maxFailures = maxFailures
        self.window = window
        self.lockout = lockout
    }

    public mutating func check(_ token: String, expected: String, now: Date = Date()) -> Verdict {
        if let until = lockedUntil {
            if now < until { return .lockedOut }
            lockedUntil = nil
            failures.removeAll()
        }
        if PairingCode.matches(token, expected: expected) {
            return .accepted
        }
        failures = failures.filter { now.timeIntervalSince($0) < window } + [now]
        if failures.count >= maxFailures {
            lockedUntil = now.addingTimeInterval(lockout)
        }
        return .rejected
    }
}
