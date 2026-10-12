import Foundation

// The pure parts of a stream (see `VoiceProtocol`): recognizing its header line, cutting its audio
// into whole frames, the phone's jitter buffer, and WAV files of 16-bit PCM.

/// Looks for a stream's header line at the start of a connection.
public enum StreamHeaderScan {
    public enum Result: Equatable, Sendable {
        /// No newline yet; read more.
        case needMore
        /// Not a stream: read the connection whole, as an ordinary message.
        case notAStream
        /// A stream's header, and the bytes that came after its newline (the start of the audio).
        case stream(VoiceMessage, rest: Data)
    }

    /// Scans `buffer` (everything read so far) for the first newline, searching from `offset`
    /// (where the last scan stopped, so a slow trickle isn't searched again and again).
    public static func scan(_ buffer: Data, from offset: Int = 0) -> Result {
        let start = buffer.startIndex + min(max(offset, 0), buffer.count)
        guard let newline = buffer[start...].firstIndex(of: 0x0A) else {
            return buffer.count > VoiceProtocol.maxStreamHeaderBytes ? .notAStream : .needMore
        }
        guard newline - buffer.startIndex <= VoiceProtocol.maxStreamHeaderBytes,
              let message = try? JSONDecoder().decode(VoiceMessage.self, from: Data(buffer[..<newline])),
              message.kind == .stream
        else { return .notAStream }
        return .stream(message, rest: Data(buffer[(newline + 1)...]))
    }
}

/// Cuts a byte stream into whole frames, keeping a partial frame for the next chunk (TCP may split
/// a sample anywhere).
public struct PCMFramer: Sendable {
    public let bytesPerFrame: Int
    private var partial = Data()

    public init(bytesPerFrame: Int) {
        self.bytesPerFrame = max(1, bytesPerFrame)
    }

    /// The bytes held back, less than a frame.
    public var pendingBytes: Int { partial.count }

    /// The whole frames in what has arrived so far (with any partial frame from before in front).
    public mutating func frames(from data: Data) -> Data {
        var bytes = partial
        bytes.append(data)
        let whole = bytes.count - bytes.count % bytesPerFrame
        partial = Data(bytes[(bytes.startIndex + whole)...])
        return Data(bytes[..<(bytes.startIndex + whole)])
    }
}

/// 16-bit little-endian PCM bytes and samples.
public enum PCM16 {
    public static func samples(_ data: Data) -> [Int16] {
        let count = data.count / 2
        var out = [Int16](repeating: 0, count: count)
        out.withUnsafeMutableBytes { dest in
            _ = data.prefix(count * 2).copyBytes(to: dest)
        }
        return out.map { Int16(littleEndian: $0) }
    }

    public static func data(_ samples: [Int16]) -> Data {
        let little = samples.map(\.littleEndian)
        return little.withUnsafeBytes { Data($0) }
    }
}

/// The phone's playout plan for a stream. Audio waits until `prebuffer` has gathered (or the
/// stream has ended), then goes out in chunks of `chunk`; once everything handed out has played
/// and less than a chunk is waiting while the stream goes on (an underrun: the network fell
/// behind), it gathers `prebuffer` again. Pure bookkeeping: the player schedules the chunks it
/// returns and reports each one as played.
///
/// Samples are interleaved Int16, `channels` to a frame; counts are in frames.
public struct JitterBuffer: Sendable {
    public enum State: Equatable, Sendable {
        case buffering, playing, finished
    }

    public let channels: Int
    public let prebufferFrames: Int
    public let chunkFrames: Int
    public private(set) var state: State = .buffering
    /// Handed out and not yet played.
    public private(set) var queuedFrames = 0
    public private(set) var underruns = 0
    private var pending: [Int16] = []
    private var ended = false

    /// - Parameters:
    ///   - prebuffer: seconds gathered before playing starts (and after an underrun).
    ///   - chunk: seconds per scheduled chunk once playing.
    public init(sampleRate: Int, channels: Int = 1, prebuffer: Double = 0.25, chunk: Double = 0.02) {
        self.channels = max(1, channels)
        prebufferFrames = max(1, Int(Double(sampleRate) * prebuffer))
        chunkFrames = max(1, Int(Double(sampleRate) * chunk))
    }

    public var pendingFrames: Int { pending.count / channels }

    /// New audio arrived; returns the chunks to schedule now.
    public mutating func append(_ samples: [Int16]) -> [[Int16]] {
        guard state != .finished, !ended else { return [] }
        pending += samples.prefix(samples.count - samples.count % channels)
        return pump()
    }

    /// A chunk of `frames` finished playing; returns any chunks to schedule now.
    public mutating func played(frames: Int) -> [[Int16]] {
        guard state != .finished else { return [] }
        queuedFrames = max(0, queuedFrames - frames)
        if state == .playing, queuedFrames == 0, !ended {
            underruns += 1
            state = .buffering
        }
        return pump()
    }

    /// The sender closed the stream; returns the rest to schedule.
    public mutating func end() -> [[Int16]] {
        guard state != .finished else { return [] }
        ended = true
        return pump()
    }

    private mutating func pump() -> [[Int16]] {
        var out: [[Int16]] = []
        switch state {
        case .buffering:
            if pendingFrames >= prebufferFrames || (ended && pendingFrames > 0) {
                state = .playing
                out = release(all: true)
            }
        case .playing:
            out = release(all: ended)
        case .finished:
            break
        }
        if ended, pending.isEmpty, queuedFrames == 0 {
            state = .finished
        }
        return out
    }

    /// Hands out the waiting audio in chunks: all of it, or only whole chunks.
    private mutating func release(all: Bool) -> [[Int16]] {
        let chunkSamples = chunkFrames * channels
        var chunks: [[Int16]] = []
        var at = 0
        while pending.count - at >= chunkSamples || (all && at < pending.count) {
            let end = min(at + chunkSamples, pending.count)
            chunks.append(Array(pending[at..<end]))
            queuedFrames += (end - at) / channels
            at = end
        }
        pending.removeFirst(at)
        return chunks
    }
}

/// WAV files of 16-bit PCM.
public enum WAV {
    /// A WAV of these samples (16-bit little-endian, interleaved).
    public static func pcm16(_ samples: Data, sampleRate: Int, channels: Int = 1) -> Data {
        var data = Data(capacity: 44 + samples.count)
        func append<T: FixedWidthInteger>(_ value: T) {
            withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) }
        }
        let blockAlign = 2 * channels
        data.append(contentsOf: Array("RIFF".utf8))
        append(UInt32(36 + samples.count))
        data.append(contentsOf: Array("WAVE".utf8))
        data.append(contentsOf: Array("fmt ".utf8))
        append(UInt32(16))                       // the fmt chunk's size
        append(UInt16(1))                        // PCM
        append(UInt16(channels))
        append(UInt32(sampleRate))
        append(UInt32(sampleRate * blockAlign))  // bytes per second
        append(UInt16(blockAlign))               // bytes per frame
        append(UInt16(16))                       // bits per sample
        data.append(contentsOf: Array("data".utf8))
        append(UInt32(samples.count))
        data.append(samples)
        return data
    }
}
