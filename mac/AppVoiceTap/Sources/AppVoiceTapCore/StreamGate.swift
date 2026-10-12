import Foundation

/// Decides what of the tapped audio goes to the phone. It waits for sound (keeping a short
/// pre-roll so the first syllable isn't clipped), then passes everything on, except that silence is
/// held back until sound follows it: a pause between sentences arrives whole, and the silence after
/// the last sentence is never sent. `silenceSeconds` of continuous silence ends the stream, and so
/// does `maxSeconds` of streaming.
///
/// It works in blocks of 10 ms of mono samples (floats, -1 to 1); what's left over waits for the
/// next call. Time is counted in samples, so it's exact and needs no clock.
public struct StreamGate: Sendable {
    public enum State: Equatable, Sendable {
        case waiting
        case streaming
        case ended(EndReason)
    }

    public enum EndReason: Equatable, Sendable {
        case silence
        case maxDuration
    }

    public let sampleRate: Double
    public let blockFrames: Int
    public let threshold: Float
    private let silenceFrames: Int
    private let maxFrames: Int
    private let preRollFrames: Int

    public private(set) var state: State = .waiting
    /// Frames passed on (or held) since the sound began.
    public private(set) var streamedFrames = 0
    /// Frames actually passed on.
    public private(set) var sentFrames = 0
    private var carry: [Float] = []
    private var preRoll: [Float] = []
    private var held: [Float] = []

    public init(sampleRate: Double, silenceSeconds: Double = 2.5, maxSeconds: Double = 600,
                thresholdDB: Double = -60, preRollSeconds: Double = 0.2) {
        self.sampleRate = sampleRate
        blockFrames = max(1, Int(sampleRate / 100))
        threshold = Float(pow(10, thresholdDB / 20))
        silenceFrames = max(1, Int(sampleRate * silenceSeconds))
        maxFrames = max(1, Int(sampleRate * maxSeconds))
        preRollFrames = max(0, Int(sampleRate * preRollSeconds))
    }

    public var hasBegun: Bool { state != .waiting }
    public var sentSeconds: Double { Double(sentFrames) / sampleRate }

    /// Takes newly tapped samples; returns the samples to send now.
    public mutating func process(_ samples: [Float]) -> [Float] {
        guard !isEnded else { return [] }
        carry += samples
        var out: [Float] = []
        var at = 0
        while carry.count - at >= blockFrames, !isEnded {
            handle(carry[at..<(at + blockFrames)], into: &out)
            at += blockFrames
        }
        carry.removeFirst(isEnded ? carry.count : at)
        sentFrames += out.count
        return out
    }

    private var isEnded: Bool {
        if case .ended = state { true } else { false }
    }

    private func isLoud(_ block: ArraySlice<Float>) -> Bool {
        block.contains { abs($0) > threshold }
    }

    private mutating func handle(_ block: ArraySlice<Float>, into out: inout [Float]) {
        switch state {
        case .waiting:
            if isLoud(block) {
                state = .streaming
                out += preRoll
                out += block
                streamedFrames = block.count
                preRoll = []
            } else {
                preRoll += block
                if preRoll.count > preRollFrames { preRoll.removeFirst(preRoll.count - preRollFrames) }
            }
        case .streaming:
            streamedFrames += block.count
            if isLoud(block) {
                out += held
                out += block
                held = []
            } else {
                held += block
                if held.count >= silenceFrames {
                    held = []
                    state = .ended(.silence)
                    return
                }
            }
            if streamedFrames >= maxFrames {
                held = []
                state = .ended(.maxDuration)
            }
        case .ended:
            break
        }
    }
}
