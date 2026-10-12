import Foundation
import Network
import Testing
@testable import SakamotoVoiceKit

/// One second of a 440 Hz sine, as 16-bit PCM at 24 kHz.
let sine: Data = PCM16.data((0..<24_000).map {
    Int16((sin(2 * Double.pi * 440 * Double($0) / 24_000) * 12_000).rounded())
})

/// A client connection that sends and reads bit by bit, like app-voice-tap. After `watchdog`
/// seconds it gives up and closes, so a test that waits for something that never comes fails
/// instead of hanging.
final class StreamClient: @unchecked Sendable {
    let connection: NWConnection
    private let lock = NSLock()
    private var gaveUp = false

    init(port: UInt16, watchdog: Double = 15) {
        connection = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
        connection.start(queue: DispatchQueue(label: "stream client"))
        DispatchQueue.global().asyncAfter(deadline: .now() + watchdog) { [weak self] in
            guard let self else { return }
            self.lock.withLock { self.gaveUp = true }
            self.connection.cancel()
        }
    }

    deinit { connection.cancel() }

    private var timedOut: Bool { lock.withLock { gaveUp } }

    /// Sends bytes; `final` closes the sending side after them.
    func send(_ data: Data, final: Bool = false) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(content: data.isEmpty ? nil : data, contentContext: final ? .finalMessage : .defaultMessage,
                            isComplete: true, completion: .contentProcessed { error in
                if let error { continuation.resume(throwing: error) } else { continuation.resume() }
            })
        }
    }

    /// Reads one line (the phone's ack), or what there is when the phone closes.
    func readLine() async throws -> Data {
        var line = Data()
        while !line.contains(0x0A) {
            let (data, done) = try await receive()
            line.append(data)
            if done { break }
        }
        return line
    }

    /// Reads until the phone closes; true when it did (false when the watchdog closed it).
    func waitForClose() async -> Bool {
        while true {
            guard let (_, done) = try? await receive() else { return !timedOut }
            if done { return !timedOut }
        }
    }

    private func receive() async throws -> (Data, Bool) {
        try await withCheckedThrowingContinuation { continuation in
            connection.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { data, _, isComplete, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: (data ?? Data(), isComplete))
                }
            }
        }
    }
}

/// Streams from a fake sender on the loopback interface into a real server.
@Suite(.serialized) struct VoiceServerStreamTests {
    let network = VoiceServerNetworkTests()

    func server(_ inbox: Inbox, connectionTimeout: TimeInterval = 30,
                idle: TimeInterval = VoiceProtocol.streamIdleTimeout,
                preference: VoicePreference = VoicePreference(policy: .stream)) -> VoiceServer {
        VoiceServer(token: "123456", version: "t", advertise: false, preferredPort: nil,
                    connectionTimeout: connectionTimeout, streamIdleTimeout: idle,
                    voice: { preference.want }) { inbox.add($0) }
    }

    func waitUntil(_ condition: () -> Bool) async {
        let deadline = Date().addingTimeInterval(5)
        while !condition(), Date() < deadline {
            try? await Task.sleep(for: .milliseconds(10))
        }
    }

    func audio(in inbox: Inbox, id: Int) -> Data {
        inbox.all.reduce(into: Data()) { all, incoming in
            if case .streamAudio(id, let data) = incoming { all.append(data) }
        }
    }

    @Test(.timeLimit(.minutes(1))) func aSineArrivesWhole() async throws {
        let inbox = Inbox()
        let server = server(inbox)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let client = StreamClient(port: port)

        try await client.send(VoiceMessage.streamHeader(token: "123 456", text: "Hello 囲碁"))
        let ack = try JSONDecoder().decode(Ack.self, from: try await client.readLine())
        #expect(ack.ok)
        #expect(ack.voice == .stream && ack.want == nil)
        #expect(inbox.all.first == .streamStart(StreamInfo(id: 1, sampleRate: 24_000, channels: 1, text: "Hello 囲碁")))

        // In odd-sized pieces, which split samples, then the sender closes its side.
        var at = 0
        while at < sine.count {
            let end = min(at + 4_801, sine.count)
            try await client.send(sine[at..<end])
            at = end
        }
        try await client.send(Data(), final: true)
        #expect(await client.waitForClose())
        await waitUntil { inbox.all.last == .streamEnd(id: 1) }

        #expect(audio(in: inbox, id: 1) == sine)
        #expect(inbox.all.last == .streamEnd(id: 1))
        for incoming in inbox.all {
            if case .streamAudio(_, let data) = incoming { #expect(data.count % 2 == 0) }   // whole frames
        }
    }

    @Test(.timeLimit(.minutes(1))) func audioInTheSameWriteAsTheHeader() async throws {
        let inbox = Inbox()
        let server = server(inbox)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let client = StreamClient(port: port)
        try await client.send(VoiceMessage.streamHeader(token: "123456") + sine.prefix(1001))
        #expect(try JSONDecoder().decode(Ack.self, from: try await client.readLine()).ok)
        try await client.send(sine.dropFirst(1001), final: true)
        #expect(await client.waitForClose())
        await waitUntil { inbox.all.last == .streamEnd(id: 1) }
        #expect(audio(in: inbox, id: 1) == sine)
    }

    @Test(.timeLimit(.minutes(1))) func aBadTokenIsRefusedBeforeAnyAudio() async throws {
        let inbox = Inbox()
        let server = server(inbox)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let client = StreamClient(port: port)
        try await client.send(VoiceMessage.streamHeader(token: "654321"))
        let ack = try JSONDecoder().decode(Ack.self, from: try await client.readLine())
        #expect(ack.error == "bad token")
        #expect(await client.waitForClose())
        #expect(inbox.all.isEmpty)
    }

    @Test(.timeLimit(.minutes(1))) func aPhoneThatWantsTextDeclinesTheStream() async throws {
        let inbox = Inbox()
        let preference = VoicePreference(policy: .textOnCellular, onCellular: true)
        let server = server(inbox, preference: preference)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let client = StreamClient(port: port)
        try await client.send(VoiceMessage.streamHeader(token: "123456", text: "Hello"))
        let ack = try JSONDecoder().decode(Ack.self, from: try await client.readLine())
        #expect(ack == .wantsText(version: "t"))
        #expect(!ack.ok && ack.error == nil && ack.want == .text && ack.voice == .text)
        #expect(await client.waitForClose())
        #expect(inbox.all.isEmpty)                          // nothing started, nothing shown

        // The text the Mac sends instead is taken, and the answer says the same.
        let reply = try await network.send(Data(#"{"token": "123456", "kind": "text", "text": "Hello"}"#.utf8), port: port)
        #expect(try JSONDecoder().decode(Ack.self, from: reply) == .success(version: "t", voice: .text))
        #expect(inbox.all == [.text("Hello", runs: [LangRun(lang: "default", text: "Hello")])])

        // Back on Wi-Fi, the next stream is accepted.
        preference.onCellular = false
        let again = StreamClient(port: port)
        try await again.send(VoiceMessage.streamHeader(token: "123456"))
        #expect(try JSONDecoder().decode(Ack.self, from: try await again.readLine()) == .success(version: "t", voice: .stream))
        await waitUntil { inbox.all.count == 2 }
        #expect(inbox.all.last == .streamStart(StreamInfo(id: 1, sampleRate: 24_000, channels: 1, text: "")))
    }

    @Test(.timeLimit(.minutes(1))) func aDeclinedStreamLeavesThePlayingOneAlone() async throws {
        let inbox = Inbox()
        let preference = VoicePreference(policy: .stream)
        let server = server(inbox, preference: preference)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let first = StreamClient(port: port)
        try await first.send(VoiceMessage.streamHeader(token: "123456"))
        #expect(try JSONDecoder().decode(Ack.self, from: try await first.readLine()).ok)

        preference.policy = .textOnly
        let second = StreamClient(port: port)
        try await second.send(VoiceMessage.streamHeader(token: "123456"))
        #expect(try JSONDecoder().decode(Ack.self, from: try await second.readLine()).want == .text)
        #expect(await second.waitForClose())

        try await first.send(sine.prefix(4_800), final: true)
        #expect(await first.waitForClose())
        await waitUntil { inbox.all.last == .streamEnd(id: 1) }
        #expect(audio(in: inbox, id: 1).count == 4_800)
        #expect(inbox.all.last == .streamEnd(id: 1))
    }

    @Test(.timeLimit(.minutes(1))) func aBadTokenOnAStreamSaysNothingOfThePreference() async throws {
        let inbox = Inbox()
        let server = server(inbox, preference: VoicePreference(policy: .textOnly))
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let client = StreamClient(port: port)
        try await client.send(VoiceMessage.streamHeader(token: "654321"))
        #expect(try JSONDecoder().decode(Ack.self, from: try await client.readLine()) == .failure(.badToken, version: "t"))
    }

    @Test(.timeLimit(.minutes(1))) func aStopEndsTheStreamAndAPingDoesNot() async throws {
        let inbox = Inbox()
        let server = server(inbox)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let client = StreamClient(port: port)
        try await client.send(VoiceMessage.streamHeader(token: "123456"))
        #expect(try JSONDecoder().decode(Ack.self, from: try await client.readLine()).ok)
        try await client.send(sine.prefix(4_800))
        await waitUntil { audio(in: inbox, id: 1).count == 4_800 }

        _ = try await network.send(Data(#"{"token": "123456", "kind": "ping"}"#.utf8), port: port)
        try await client.send(sine.prefix(4_800))
        await waitUntil { audio(in: inbox, id: 1).count == 9_600 }
        #expect(audio(in: inbox, id: 1).count == 9_600)

        _ = try await network.send(Data(#"{"token": "123456", "kind": "stop"}"#.utf8), port: port)
        #expect(await client.waitForClose())
        #expect(inbox.all.last == .stop)
        #expect(!inbox.all.contains(.streamEnd(id: 1)))     // the stop replaced it
    }

    @Test(.timeLimit(.minutes(1))) func aSecondStreamReplacesTheFirst() async throws {
        let inbox = Inbox()
        let server = server(inbox)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let first = StreamClient(port: port)
        try await first.send(VoiceMessage.streamHeader(token: "123456"))
        _ = try await first.readLine()
        let second = StreamClient(port: port)
        try await second.send(VoiceMessage.streamHeader(token: "123456", rate: 48_000, channels: 2))
        #expect(try JSONDecoder().decode(Ack.self, from: try await second.readLine()).ok)
        #expect(await first.waitForClose())
        #expect(inbox.all.last == .streamStart(StreamInfo(id: 2, sampleRate: 48_000, channels: 2, text: "")))
    }

    @Test(.timeLimit(.minutes(1))) func anIdleStreamIsClosed() async throws {
        let inbox = Inbox()
        let server = server(inbox, connectionTimeout: 0.2, idle: 0.3)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let client = StreamClient(port: port)
        try await client.send(VoiceMessage.streamHeader(token: "123456"))
        _ = try await client.readLine()
        #expect(await client.waitForClose())
        await waitUntil { inbox.all.last == .streamEnd(id: 1) }
        #expect(inbox.all.last == .streamEnd(id: 1))
    }

    @Test(.timeLimit(.minutes(1))) func aOneLineMessageWithANewlineIsStillAMessage() async throws {
        let inbox = Inbox()
        let server = server(inbox)
        defer { server.stop() }
        let port = try await network.waitForPort(server)
        let reply = try await network.send(Data((#"{"token": "123456", "kind": "text", "text": "Hi"}"# + "\n").utf8), port: port)
        #expect(try JSONDecoder().decode(Ack.self, from: reply).ok)
        #expect(inbox.all == [.text("Hi", runs: [LangRun(lang: "default", text: "Hi")])])
    }
}
