import Foundation
import Testing
@testable import SakamotoVoiceKit

@Suite struct SilentAudioTests {
    func u32(_ data: Data, _ offset: Int) -> UInt32 {
        data.subdata(in: offset..<offset + 4).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self) }.littleEndian
    }

    func u16(_ data: Data, _ offset: Int) -> UInt16 {
        data.subdata(in: offset..<offset + 2).withUnsafeBytes { $0.loadUnaligned(as: UInt16.self) }.littleEndian
    }

    @Test func header() {
        let wav = SilentAudio.wav(seconds: 1, sampleRate: 22_050)
        #expect(wav.count == 44 + 22_050 * 2)
        #expect(String(decoding: wav.prefix(4), as: UTF8.self) == "RIFF")
        #expect(u32(wav, 4) == UInt32(wav.count - 8))
        #expect(String(decoding: wav.subdata(in: 8..<16), as: UTF8.self) == "WAVEfmt ")
        #expect(u16(wav, 20) == 1)          // PCM
        #expect(u16(wav, 22) == 1)          // mono
        #expect(u32(wav, 24) == 22_050)
        #expect(u16(wav, 34) == 16)
        #expect(String(decoding: wav.subdata(in: 36..<40), as: UTF8.self) == "data")
        #expect(u32(wav, 40) == 22_050 * 2)
    }

    @Test func nearSilentButNotZero() {
        let wav = SilentAudio.wav(seconds: 0.5, amplitude: 1)
        let samples = stride(from: 44, to: wav.count, by: 2).map { Int16(bitPattern: u16(wav, $0)) }
        #expect(samples.allSatisfy { abs($0) == 1 })
        #expect(samples.contains(1) && samples.contains(-1))
    }

    @Test func deterministic() {
        #expect(SilentAudio.wav(seconds: 0.1) == SilentAudio.wav(seconds: 0.1))
    }
}
