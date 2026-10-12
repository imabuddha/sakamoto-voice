@preconcurrency import AVFoundation

/// Mono float samples at the tap's rate in, 16-bit samples at the stream's rate out, with Core
/// Audio's sample-rate converter (which filters properly, so nothing aliases). It keeps its state
/// between calls, so a stream converts piece by piece without seams.
public final class Resampler {
    public let inputRate: Double
    public let outputRate: Double
    private let inputFormat: AVAudioFormat
    private let outputFormat: AVAudioFormat
    private let converter: AVAudioConverter

    public init?(inputRate: Double, outputRate: Double) {
        guard inputRate > 0, outputRate > 0,
              let input = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: inputRate, channels: 1, interleaved: false),
              let output = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: outputRate, channels: 1, interleaved: true),
              let converter = AVAudioConverter(from: input, to: output)
        else { return nil }
        converter.sampleRateConverterQuality = AVAudioQuality.high.rawValue
        self.inputRate = inputRate
        self.outputRate = outputRate
        inputFormat = input
        outputFormat = output
        self.converter = converter
    }

    /// Converts the next piece of the stream.
    public func convert(_ samples: [Float]) -> [Int16] {
        guard !samples.isEmpty,
              let buffer = AVAudioPCMBuffer(pcmFormat: inputFormat, frameCapacity: AVAudioFrameCount(samples.count))
        else { return [] }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { source in
            buffer.floatChannelData![0].update(from: source.baseAddress!, count: samples.count)
        }
        var given = false
        return run(capacity: samples.count) { _, status in
            if given {
                status.pointee = .noDataNow
                return nil
            }
            given = true
            status.pointee = .haveData
            return buffer
        }
    }

    /// The converter's last few samples, at the end of the stream.
    public func flush() -> [Int16] {
        run(capacity: 0) { _, status in
            status.pointee = .endOfStream
            return nil
        }
    }

    private func run(capacity inputFrames: Int, input: @escaping AVAudioConverterInputBlock) -> [Int16] {
        let capacity = AVAudioFrameCount(Double(inputFrames) * outputRate / inputRate) + 1_024
        var out: [Int16] = []
        while true {
            guard let buffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: capacity) else { break }
            var error: NSError?
            let status = converter.convert(to: buffer, error: &error, withInputFrom: input)
            if let data = buffer.int16ChannelData, buffer.frameLength > 0 {
                out += UnsafeBufferPointer(start: data[0], count: Int(buffer.frameLength))
            }
            // .haveData means the buffer filled up and there may be more.
            guard status == .haveData, buffer.frameLength == capacity else { break }
        }
        return out
    }
}
