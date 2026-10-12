import Foundation

/// The keep-alive sound: a short mono 16-bit WAV of near silence (a dither of one or two units,
/// about -90 dB) for looping while the app stays awake. Made in code, so there's no asset.
public enum SilentAudio {
    public static func wav(seconds: Double = 1, sampleRate: Int = 22_050, amplitude: Int16 = 1) -> Data {
        let frames = max(1, Int(seconds * Double(sampleRate)))
        var samples = [Int16](repeating: 0, count: frames)
        var seed: UInt32 = 0x5A4D_6F69         // a fixed LCG: the same bytes every time
        for i in 0..<frames {
            seed = seed &* 1_664_525 &+ 1_013_904_223
            samples[i] = (seed >> 31) == 0 ? amplitude : -amplitude
        }
        return WAV.pcm16(PCM16.data(samples), sampleRate: sampleRate)
    }
}
