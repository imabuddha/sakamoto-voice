import Foundation
import Network
import Testing
@testable import AppVoiceTapCore
import SakamotoVoiceKit

@Suite struct OptionsTests {
    @Test func everything() throws {
        let options = try Options.parse(["--to", "Example-iPhone.local:47811", "--token", "123 456", "--mute",
                                         "--max-seconds", "30", "--silence-seconds", "1.5", "--wait-start", "8",
                                         "--rate", "16000", "--threshold-db", "-50", "--text-stdin",
                                         "--bundle-id", "com.example.speech", "--no-bundle-id-tap",
                                         "--no-output-subdevice", "--no-disclaim", "--no-permission-check", "-v"])
        #expect(options.mode == .stream)
        #expect((options.host, options.port, options.token) == ("Example-iPhone.local", 47811, "123456"))
        #expect(options.mute && options.textFromStdin && options.verbose)
        #expect((options.maxSeconds, options.silenceSeconds, options.waitStart) == (30, 1.5, 8))
        #expect((options.rate, options.thresholdDB) == (16_000, -50))
        #expect(options.bundleIDs == ["com.anthropic.claudefordesktop", "com.example.speech"])
        #expect(!options.tapByBundleID && !options.outputSubdevice && !options.disclaim && !options.permissionCheck)
    }

    @Test func defaults() throws {
        let options = try Options.parse(["--to", "10.0.0.5:47811", "--token", "654321"])
        #expect(!options.mute)
        #expect((options.maxSeconds, options.silenceSeconds, options.waitStart) == (600, 2.5, 6))
        #expect(options.rate == 24_000)
        #expect(options.appPath == "/Applications/Claude.app")
        #expect(options.tapByBundleID && options.outputSubdevice && options.disclaim)
        #expect(options.text == nil)
    }

    @Test func checkAndListNeedNoPhone() throws {
        #expect(try Options.parse(["--check"]).mode == .check)
        #expect(try Options.parse(["--list"]).mode == .list)
        #expect(try Options.parse(["--help"]).mode == .help)
    }

    @Test func mistakes() {
        #expect(throws: Options.ParseError.missing("--to HOST:PORT")) { try Options.parse(["--token", "123456"]) }
        #expect(throws: Options.ParseError.missing("--token CODE")) { try Options.parse(["--to", "a:1"]) }
        #expect(throws: Options.ParseError.badValue("--token", "12345")) { try Options.parse(["--token", "12345"]) }
        #expect(throws: Options.ParseError.badValue("--to", "phone")) { try Options.parse(["--to", "phone"]) }
        #expect(throws: Options.ParseError.badValue("--wait-start", "-1")) { try Options.parse(["--wait-start", "-1"]) }
        #expect(throws: Options.ParseError.missing("a value for --rate")) { try Options.parse(["--rate"]) }
        #expect(throws: Options.ParseError.unknown("--loud")) { try Options.parse(["--loud"]) }
    }

    @Test func addresses() {
        #expect(Options.splitAddress("Example-iPhone.local:47811")! == ("Example-iPhone.local", 47811))
        #expect(Options.splitAddress("fe80::1%en0:47811")! == ("fe80::1%en0", 47811))
        #expect(Options.splitAddress("[::1]:9")! == ("::1", 9))
        #expect(Options.splitAddress("host:0") == nil)
        #expect(Options.splitAddress(":47811") == nil)
        #expect(Options.splitAddress("host:http") == nil)
    }
}

@Suite struct StreamGateTests {
    /// 1000 samples a second: blocks of 10, so the arithmetic is easy to follow.
    func gate(silence: Double = 0.5, max: Double = 600) -> StreamGate {
        StreamGate(sampleRate: 1000, silenceSeconds: silence, maxSeconds: max, thresholdDB: -60, preRollSeconds: 0.05)
    }

    let quiet = [Float](repeating: 0, count: 10)
    let loud = [Float](repeating: 0.5, count: 10)

    @Test func silenceBeforeTheSoundIsNotSent() {
        var gate = gate()
        #expect(gate.process(Array(repeating: 0, count: 300)).isEmpty)
        #expect(gate.state == .waiting && !gate.hasBegun)
        #expect(gate.process(Array(repeating: 0.0005, count: 30)).isEmpty)   // below -60 dBFS
    }

    @Test func theSoundBeginsWithAShortPreRoll() {
        var gate = gate()
        _ = gate.process(Array(repeating: 0, count: 200))
        let out = gate.process(loud)
        #expect(gate.state == .streaming)
        #expect(out.count == 50 + 10)                                       // 50 ms of pre-roll
        #expect(out.suffix(10) == loud[...])
        #expect(gate.sentFrames == 60)
    }

    @Test func aPauseIsHeldUntilTheSoundResumes() {
        var gate = gate()
        _ = gate.process(loud)
        #expect(gate.process(quiet + quiet + quiet).isEmpty)                // held
        let out = gate.process(loud)
        #expect(out == quiet + quiet + quiet + loud)                        // the pause arrives whole
    }

    @Test func enoughSilenceEndsItAndIsNeverSent() {
        var gate = gate(silence: 0.5)
        _ = gate.process(loud)
        #expect(gate.process(Array(repeating: 0, count: 490)).isEmpty)
        #expect(gate.state == .streaming)
        #expect(gate.process(quiet + loud).isEmpty)                         // 500 ms: the end
        #expect(gate.state == .ended(.silence))
        #expect(gate.process(loud).isEmpty)
        #expect(gate.sentFrames == 10)
    }

    @Test func theMaximumEndsIt() {
        var gate = gate(max: 0.1)
        var sent = 0
        for _ in 0..<20 { sent += gate.process(loud).count }
        #expect(gate.state == .ended(.maxDuration))
        #expect(sent == 100)
    }

    @Test func partialBlocksWait() {
        var gate = gate()
        #expect(gate.process(Array(repeating: 0.5, count: 7)).isEmpty)       // under a block
        #expect(gate.process(Array(repeating: 0.5, count: 3)).count == 10)
    }

    @Test func blocksAreTenMilliseconds() {
        #expect(StreamGate(sampleRate: 48_000).blockFrames == 480)
        #expect(abs(StreamGate(sampleRate: 48_000, thresholdDB: -60).threshold - 0.001) < 1e-6)
    }
}

@Suite struct ResamplerTests {
    func sine(rate: Double, frequency: Double, seconds: Double, amplitude: Float = 0.5) -> [Float] {
        (0..<Int(rate * seconds)).map { amplitude * Float(sin(2 * Double.pi * frequency * Double($0) / rate)) }
    }

    /// The frequency, from the zero crossings going up.
    func frequency(_ samples: [Int16], rate: Double) -> Double {
        var crossings = 0
        for i in 1..<samples.count where samples[i - 1] < 0 && samples[i] >= 0 { crossings += 1 }
        return Double(crossings) / (Double(samples.count) / rate)
    }

    func convert(_ samples: [Float], from rate: Double, chunk: Int) throws -> [Int16] {
        let resampler = try #require(Resampler(inputRate: rate, outputRate: 24_000))
        var out: [Int16] = []
        var at = 0
        while at < samples.count {
            out += resampler.convert(Array(samples[at..<min(at + chunk, samples.count)]))
            at += chunk
        }
        return out + resampler.flush()
    }

    @Test(arguments: [48_000.0, 44_100.0, 24_000.0])
    func aSineKeepsItsPitchAndLevel(rate: Double) throws {
        let out = try convert(sine(rate: rate, frequency: 1_000, seconds: 1), from: rate, chunk: 512)
        #expect(abs(out.count - 24_000) <= 64)
        #expect(abs(frequency(out, rate: 24_000) - 1_000) <= 3)
        let middle = out[2_000..<22_000]
        let peak = Double(middle.map { abs(Int($0)) }.max() ?? 0) / 32_768
        #expect(abs(peak - 0.5) < 0.02)
    }

    @Test func chunkSizeDoesNotMatter() throws {
        let input = sine(rate: 48_000, frequency: 440, seconds: 0.5)
        let whole = try convert(input, from: 48_000, chunk: input.count)
        let small = try convert(input, from: 48_000, chunk: 37)
        #expect(abs(whole.count - small.count) <= 2)
        let n = min(whole.count, small.count)
        let worst = zip(whole.prefix(n), small.prefix(n)).map { abs(Int($0) - Int($1)) }.max() ?? 0
        #expect(worst <= 2)
    }

    @Test func aboveTheNewNyquistIsFilteredOut() throws {
        // 15 kHz can't be represented at 24 kHz; it must not fold back as a loud 9 kHz.
        let out = try convert(sine(rate: 48_000, frequency: 15_000, seconds: 0.5), from: 48_000, chunk: 480)
        let peak = out.dropFirst(1_000).map { abs(Int($0)) }.max() ?? 0
        #expect(peak < 1_000)
    }

    @Test func clipsInsteadOfWrapping() throws {
        let out = try convert(Array(repeating: 1.5, count: 4_800), from: 48_000, chunk: 480)
        #expect(out.dropFirst(100).dropLast(100).allSatisfy { $0 > 30_000 })
    }
}

@Suite struct ProcessMatcherTests {
    let matcher = ProcessMatcher(appPath: "/Applications/Claude.app/", bundleIDs: ["com.anthropic.claudefordesktop"])

    @Test func theAppAndItsHelpers() {
        #expect(matcher.matches(bundleID: "com.anthropic.claudefordesktop", path: nil))
        #expect(matcher.matches(bundleID: "com.anthropic.claudefordesktop.helper", path: nil))
        #expect(matcher.matches(bundleID: nil,
                                path: "/Applications/Claude.app/Contents/Frameworks/Claude Helper.app/Contents/MacOS/Claude Helper"))
        #expect(matcher.matches(bundleID: "", path: "/Applications/Claude.app/Contents/MacOS/Claude"))
    }

    @Test func othersAreNot() {
        #expect(!matcher.matches(bundleID: "com.anthropic.claudefordesktopx", path: nil))
        #expect(!matcher.matches(bundleID: "com.apple.Music", path: "/System/Applications/Music.app/Contents/MacOS/Music"))
        #expect(!matcher.matches(bundleID: nil, path: "/Applications/Claude.app2/x"))
        #expect(!matcher.matches(bundleID: nil, path: nil))
    }

    @Test func tapBundleIDs() {
        #expect(matcher.tapBundleIDs(seen: ["com.anthropic.claudefordesktop.helper", "com.anthropic.claudefordesktop.other", ""])
                == ["com.anthropic.claudefordesktop", "com.anthropic.claudefordesktop.helper",
                    "com.anthropic.claudefordesktop.other"])
    }
}

/// Collects what the receiver hands on.
final class Inbox: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [Incoming] = []

    func add(_ incoming: Incoming) { lock.withLock { items.append(incoming) } }
    var all: [Incoming] { lock.withLock { items } }

    var audio: Data {
        all.reduce(into: Data()) { data, item in
            if case .streamAudio(_, let chunk) = item { data.append(chunk) }
        }
    }
}

/// app-voice-tap's own sender (PhoneSocket, the header, the resampler) into the phone's real
/// receiver, on the loopback interface.
@Suite(.serialized) struct LoopbackTests {
    func listening(_ inbox: Inbox) async throws -> (VoiceServer, UInt16) {
        let server = VoiceServer(token: "123456", version: "loopback", advertise: false, preferredPort: nil) { inbox.add($0) }
        let states = AsyncStream<VoiceServer.State> { continuation in server.onStateChange { continuation.yield($0) } }
        server.start()
        for await state in states {
            if case .listening(let port) = state, port != 0 { return (server, port) }
        }
        throw CancellationError()
    }

    func waitUntil(_ condition: () -> Bool) async {
        let deadline = Date().addingTimeInterval(5)
        while !condition(), Date() < deadline { try? await Task.sleep(for: .milliseconds(10)) }
    }

    @Test(.timeLimit(.minutes(1))) func aTappedSineReachesThePhone() async throws {
        let inbox = Inbox()
        let (server, port) = try await listening(inbox)
        defer { server.stop() }

        let socket = try PhoneSocket.connect(host: "127.0.0.1", port: port)
        try socket.send(VoiceMessage.streamHeader(token: "123456", text: "Hello", rate: 24_000))
        let ack = try JSONDecoder().decode(Ack.self, from: socket.readLine(timeout: 4))
        #expect(ack.ok)

        // What the tap would deliver: 48 kHz floats, half a second of silence, a second of sine,
        // then silence; through the gate and the resampler, in 10.7 ms pieces as Core Audio gives them.
        let rate = 48_000.0
        let tapped: [Float] = Array(repeating: 0, count: 24_000)
            + (0..<48_000).map { 0.4 * Float(sin(2 * Double.pi * 440 * Double($0) / rate)) }
            + Array(repeating: 0, count: 48_000)
        var gate = StreamGate(sampleRate: rate, silenceSeconds: 0.5)
        let resampler = try #require(Resampler(inputRate: rate, outputRate: 24_000))
        var sent = Data()
        var at = 0
        while at < tapped.count, gate.state != .ended(.silence) {
            let out = gate.process(Array(tapped[at..<min(at + 512, tapped.count)]))
            if !out.isEmpty {
                let pcm = PCM16.data(resampler.convert(out))
                try socket.send(pcm)
                sent.append(pcm)
            }
            #expect(!socket.peerClosed())
            at += 512
        }
        #expect(gate.state == .ended(.silence))
        let tail = PCM16.data(resampler.flush())
        try socket.send(tail)
        sent.append(tail)
        socket.finish()

        await waitUntil { inbox.all.last == .streamEnd(id: 1) }
        #expect(inbox.all.first == .streamStart(StreamInfo(id: 1, sampleRate: 24_000, channels: 1, text: "Hello")))
        #expect(inbox.all.last == .streamEnd(id: 1))
        #expect(inbox.audio == sent)
        // About a second of sound plus the 0.2 s pre-roll, and none of the trailing silence.
        let seconds = Double(sent.count / 2) / 24_000
        #expect(seconds > 1.15 && seconds < 1.3)
    }

    @Test(.timeLimit(.minutes(1))) func aWrongCodeIsRefused() async throws {
        let inbox = Inbox()
        let (server, port) = try await listening(inbox)
        defer { server.stop() }
        let socket = try PhoneSocket.connect(host: "127.0.0.1", port: port)
        try socket.send(VoiceMessage.streamHeader(token: "111111"))
        let ack = try JSONDecoder().decode(Ack.self, from: socket.readLine(timeout: 4))
        #expect(!ack.ok && ack.error == "bad token")
        await waitUntil { socket.peerClosed() }
        #expect(socket.peerClosed())
        #expect(inbox.all.isEmpty)
    }

    @Test(.timeLimit(.minutes(1))) func aStopOnThePhoneIsSeenAsAClose() async throws {
        let inbox = Inbox()
        let (server, port) = try await listening(inbox)
        defer { server.stop() }
        let socket = try PhoneSocket.connect(host: "127.0.0.1", port: port)
        try socket.send(VoiceMessage.streamHeader(token: "123456"))
        #expect(try JSONDecoder().decode(Ack.self, from: socket.readLine(timeout: 4)).ok)
        #expect(!socket.peerClosed())

        let stop = try PhoneSocket.connect(host: "127.0.0.1", port: port)
        try stop.send(Data(#"{"token": "123456", "kind": "stop"}"#.utf8))
        stop.finish()
        await waitUntil { socket.peerClosed() }
        #expect(socket.peerClosed())
        #expect(inbox.all.last == .stop)
    }

    @Test func nobodyListening() {
        #expect(throws: PhoneSocket.Failure.self) {
            _ = try PhoneSocket.connect(host: "127.0.0.1", port: 1, timeout: 1)
        }
        #expect(throws: PhoneSocket.Failure.self) {
            _ = try PhoneSocket.connect(host: "no-such-host.invalid", port: 47811, timeout: 1)
        }
    }
}
