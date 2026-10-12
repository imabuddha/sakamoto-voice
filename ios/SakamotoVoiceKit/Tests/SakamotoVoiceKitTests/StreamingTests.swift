import Foundation
import Testing
@testable import SakamotoVoiceKit

@Suite struct StreamHeaderTests {
    @Test func theMacsHeaderIsOneSortedLine() throws {
        let header = VoiceMessage.streamHeader(token: "123456", text: "Hi 囲碁 / you")
        let line = String(decoding: header, as: UTF8.self)
        #expect(line == #"{"channels":1,"format":"pcm16","kind":"stream","rate":24000,"text":"Hi 囲碁 / you","token":"123456"}"# + "\n")
        #expect(line.filter { $0 == "\n" }.count == 1)
    }

    @Test func noTextIsLeftOut() {
        let line = String(decoding: VoiceMessage.streamHeader(token: "1", text: ""), as: UTF8.self)
        #expect(!line.contains("text"))
    }

    @Test func newlinesInTheTextAreEscaped() {
        let header = VoiceMessage.streamHeader(token: "1", text: "one\ntwo")
        #expect(header.filter { $0 == 0x0A }.count == 1)
        #expect(header.last == 0x0A)
    }

    @Test func scanFindsAStreamAndTheAudioAfterIt() throws {
        var buffer = VoiceMessage.streamHeader(token: "123456", text: "Hello", rate: 16_000)
        buffer.append(contentsOf: [1, 0, 2])
        guard case .stream(let message, let rest) = StreamHeaderScan.scan(buffer) else {
            Issue.record("not a stream")
            return
        }
        #expect(message.kind == .stream && message.token == "123456" && message.rate == 16_000)
        #expect(rest == Data([1, 0, 2]))
        #expect(try MessageDecoder.validateStream(message) == StreamInfo(id: 0, sampleRate: 16_000, channels: 1, text: "Hello"))
    }

    @Test func scanWaitsForTheNewline() {
        let header = VoiceMessage.streamHeader(token: "1")
        #expect(StreamHeaderScan.scan(header.dropLast()) == .needMore)
        #expect(StreamHeaderScan.scan(Data()) == .needMore)
        // The newline is found when it arrives, even past where the last scan stopped.
        #expect(StreamHeaderScan.scan(header, from: header.count - 1) != .needMore)
    }

    @Test(arguments: [#"{"token": "1", "kind": "text", "text": "Hi"}"# + "\n",
                      "{\n  \"token\": \"1\",\n  \"kind\": \"stream\"\n}",
                      "not json\n",
                      #"{"token": "1", "kind": "ping"}"# + "\n" + "more"])
    func ordinaryMessagesAreNotStreams(text: String) {
        #expect(StreamHeaderScan.scan(Data(text.utf8)) == .notAStream)
    }

    @Test func aHugeMessageWithoutANewlineIsNotAStream() {
        let big = Data(repeating: 0x41, count: VoiceProtocol.maxStreamHeaderBytes + 1)
        #expect(StreamHeaderScan.scan(big) == .notAStream)
    }

    @Test func scanWorksOnASlice() throws {
        let whole = Data([9, 9]) + VoiceMessage.streamHeader(token: "1") + Data([5, 0])
        let slice = whole[2...]
        guard case .stream(_, let rest) = StreamHeaderScan.scan(slice) else {
            Issue.record("not a stream")
            return
        }
        #expect(rest == Data([5, 0]))
    }

    @Test(arguments: [#"{"token": "1", "kind": "stream", "format": "mp3"}"#,
                      #"{"token": "1", "kind": "stream", "rate": 4000}"#,
                      #"{"token": "1", "kind": "stream", "rate": 200000}"#,
                      #"{"token": "1", "kind": "stream", "channels": 3}"#,
                      #"{"token": "1", "kind": "stream", "channels": 0}"#,
                      #"{"token": "1", "kind": "text", "text": "x"}"#])
    func badHeadersAreRefused(json: String) throws {
        let message = try MessageDecoder.decode(Data(json.utf8))
        #expect(throws: MessageError.badStream) { try MessageDecoder.validateStream(message) }
    }

    @Test func headerDefaults() throws {
        let message = try MessageDecoder.decode(Data(#"{"token": "1", "kind": "stream", "text": "  Hi  "}"#.utf8))
        #expect(try MessageDecoder.validateStream(message) == StreamInfo(id: 0, sampleRate: 24_000, channels: 1, text: "Hi"))
        let stereo = try MessageDecoder.decode(Data(#"{"token": "1", "kind": "stream", "format": "PCM16", "channels": 2, "rate": 48000}"#.utf8))
        #expect(try MessageDecoder.validateStream(stereo).bytesPerFrame == 4)
    }

    @Test func aStreamReadWholeIsRefused() throws {
        let message = try MessageDecoder.decode(Data(#"{"token": "1", "kind": "stream"}"#.utf8))
        #expect(throws: MessageError.badStream) { try MessageDecoder.validate(message) }
        #expect(MessageError.badStream.code == "bad stream")
    }
}

@Suite struct PCMFramerTests {
    @Test func keepsPartialFrames() {
        var framer = PCMFramer(bytesPerFrame: 2)
        #expect(framer.frames(from: Data([1])) == Data())
        #expect(framer.pendingBytes == 1)
        #expect(framer.frames(from: Data([2, 3, 4, 5])) == Data([1, 2, 3, 4]))
        #expect(framer.pendingBytes == 1)
        #expect(framer.frames(from: Data([6])) == Data([5, 6]))
        #expect(framer.pendingBytes == 0)
    }

    @Test func stereoFrames() {
        var framer = PCMFramer(bytesPerFrame: 4)
        #expect(framer.frames(from: Data([1, 2, 3, 4, 5, 6])) == Data([1, 2, 3, 4]))
        #expect(framer.frames(from: Data([7, 8, 9])) == Data([5, 6, 7, 8]))
    }

    @Test func anyChunkingGivesTheSameBytes() {
        let bytes = Data((0..<1001).map { UInt8(truncatingIfNeeded: $0 &* 7) })
        for size in [1, 3, 7, 64, 1001] {
            var framer = PCMFramer(bytesPerFrame: 2)
            var out = Data()
            var at = 0
            while at < bytes.count {
                out.append(framer.frames(from: bytes[at..<min(at + size, bytes.count)]))
                at += size
            }
            #expect(out == bytes.prefix(1000))
            #expect(framer.pendingBytes == 1)
        }
    }
}

@Suite struct PCM16Tests {
    @Test func roundTrip() {
        let samples: [Int16] = [0, 1, -1, .max, .min, 12_345]
        let data = PCM16.data(samples)
        #expect(data == Data([0, 0, 1, 0, 0xFF, 0xFF, 0xFF, 0x7F, 0x00, 0x80, 0x39, 0x30]))
        #expect(PCM16.samples(data) == samples)
        #expect(PCM16.samples(data + Data([7])) == samples)   // an odd byte is ignored
    }

    @Test func wavHeader() {
        let wav = WAV.pcm16(PCM16.data([1, 2, 3, 4]), sampleRate: 24_000, channels: 2)
        #expect(wav.count == 44 + 8)
        #expect(String(decoding: wav.prefix(4), as: UTF8.self) == "RIFF")
        #expect(wav[22] == 2)                                 // channels
        #expect(wav.subdata(in: 24..<28) == Data([0xC0, 0x5D, 0, 0]))   // 24000
        #expect(wav.subdata(in: 28..<32) == Data([0x00, 0x77, 0x01, 0]))   // 96000 bytes a second
        #expect(wav[32] == 4)                                 // bytes per frame
        #expect(wav.suffix(8) == PCM16.data([1, 2, 3, 4]))
    }
}

@Suite struct JitterBufferTests {
    /// 1000 frames a second: 250 frames of prebuffer and chunks of 20.
    func buffer(channels: Int = 1) -> JitterBuffer {
        JitterBuffer(sampleRate: 1000, channels: channels, prebuffer: 0.25, chunk: 0.02)
    }

    func frames(_ n: Int, channels: Int = 1) -> [Int16] {
        (0..<n * channels).map { Int16(truncatingIfNeeded: $0) }
    }

    @Test func waitsForThePrebuffer() {
        var jitter = buffer()
        #expect(jitter.append(frames(100)).isEmpty)
        #expect(jitter.append(frames(100)).isEmpty)
        #expect(jitter.state == .buffering)
        let chunks = jitter.append(frames(60))
        #expect(jitter.state == .playing)
        #expect(chunks.map(\.count) == Array(repeating: 20, count: 13))   // all 260 frames go out
        #expect(jitter.queuedFrames == 260)
        #expect(jitter.pendingFrames == 0)
    }

    @Test func thenWholeChunksAsTheyArrive() {
        var jitter = buffer()
        _ = jitter.append(frames(250))
        #expect(jitter.append(frames(15)).isEmpty)          // less than a chunk waits
        #expect(jitter.append(frames(30)).map(\.count) == [20, 20])
        #expect(jitter.pendingFrames == 5)
        #expect(jitter.queuedFrames == 290)
    }

    @Test func keepsTheSamplesInOrder() {
        var jitter = buffer()
        let input = frames(400)
        var out: [Int16] = []
        var at = 0
        while at < input.count {
            for chunk in jitter.append(Array(input[at..<min(at + 33, input.count)])) { out += chunk }
            at += 33
        }
        for chunk in jitter.end() { out += chunk }
        #expect(out == input)
    }

    @Test func anUnderrunBuffersAgain() {
        var jitter = buffer()
        let first = jitter.append(frames(250))
        _ = jitter.append(frames(10))                        // waits, less than a chunk
        for chunk in first.dropLast() { #expect(jitter.played(frames: chunk.count).isEmpty) }
        #expect(jitter.state == .playing)
        #expect(jitter.played(frames: first.last!.count).isEmpty)
        #expect(jitter.state == .buffering)
        #expect(jitter.underruns == 1)
        #expect(jitter.append(frames(200)).isEmpty)          // 210 waiting
        #expect(jitter.append(frames(40)).count == 13)       // 250 again: playing
        #expect(jitter.state == .playing)
    }

    @Test func theEndFlushesAShortStream() {
        var jitter = buffer()
        #expect(jitter.append(frames(30)).isEmpty)
        let rest = jitter.end()
        #expect(rest.map(\.count) == [20, 10])
        #expect(jitter.state == .playing)
        _ = jitter.played(frames: 20)
        #expect(jitter.state == .playing)
        _ = jitter.played(frames: 10)
        #expect(jitter.state == .finished)
        #expect(jitter.underruns == 0)
    }

    @Test func theEndFlushesThePartialChunk() {
        var jitter = buffer()
        _ = jitter.append(frames(255))                       // 13 chunks, the last of 15
        #expect(jitter.append(frames(7)).isEmpty)
        #expect(jitter.end().map(\.count) == [7])
        #expect(jitter.append(frames(50)).isEmpty)           // nothing after the end
    }

    @Test func anEmptyStreamFinishesAtOnce() {
        var jitter = buffer()
        #expect(jitter.end().isEmpty)
        #expect(jitter.state == .finished)
    }

    @Test func stereoCountsFrames() {
        var jitter = buffer(channels: 2)
        let chunks = jitter.append(frames(250, channels: 2))
        #expect(chunks.first?.count == 40)                   // 20 frames of 2 samples
        #expect(jitter.queuedFrames == 250)
        _ = jitter.append([1])                               // half a frame is dropped
        #expect(jitter.pendingFrames == 0)
    }
}
