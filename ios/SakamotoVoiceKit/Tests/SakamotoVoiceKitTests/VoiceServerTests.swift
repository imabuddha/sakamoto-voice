import Foundation
import Network
import Testing
@testable import SakamotoVoiceKit

/// Collects what a server hands on, across threads.
final class Inbox: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [Incoming] = []

    func add(_ incoming: Incoming) {
        lock.withLock { items.append(incoming) }
    }

    var all: [Incoming] { lock.withLock { items } }
}

@Suite struct VoiceServerHandleTests {
    @Test func acceptsAndHandsOn() throws {
        let inbox = Inbox()
        let server = VoiceServer(token: "123456", version: "t", advertise: false) { inbox.add($0) }
        let ack = server.handle(Data(#"{"token": "123 456", "kind": "text", "text": "Hi"}"#.utf8))
        #expect(ack == .success(version: "t"))
        #expect(inbox.all == [.text("Hi", runs: [LangRun(lang: "default", text: "Hi")])])
    }

    @Test func refusals() {
        let inbox = Inbox()
        let server = VoiceServer(token: "123456", version: "t", advertise: false) { inbox.add($0) }
        #expect(server.handle(Data("nope".utf8)).error == "malformed")
        #expect(server.handle(Data(#"{"token": "654321", "kind": "ping"}"#.utf8)).error == "bad token")
        #expect(server.handle(Data(#"{"token": "123456", "kind": "text", "text": ""}"#.utf8)).error == "no text")
        #expect(inbox.all.isEmpty)
    }

    @Test func locksOutAGuesser() {
        let server = VoiceServer(token: "123456", version: "t", advertise: false) { _ in }
        let t0 = Date()
        for i in 0..<10 {
            #expect(server.handle(Data(#"{"token": "00000\#(i)", "kind": "ping"}"#.utf8), now: t0).error == "bad token")
        }
        #expect(server.handle(Data(#"{"token": "123456", "kind": "ping"}"#.utf8), now: t0).error == "locked out")
    }
}

/// A real listener on the loopback interface (no Bonjour) and a real client.
@Suite(.serialized) struct VoiceServerNetworkTests {
    func waitForPort(_ server: VoiceServer) async throws -> UInt16 {
        let stream = AsyncStream<VoiceServer.State> { continuation in
            server.onStateChange { continuation.yield($0) }
        }
        server.start()
        for await state in stream {
            if case .listening(let port) = state, port != 0 { return port }
        }
        throw CancellationError()
    }

    /// Sends one message the way speak.py does (write, half-close, read the reply to the end).
    func send(_ payload: Data, port: UInt16) async throws -> Data {
        let connection = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
        let queue = DispatchQueue(label: "client")
        connection.start(queue: queue)
        defer { connection.cancel() }
        return try await withCheckedThrowingContinuation { continuation in
            // A failed send fails the receive too, which resumes the continuation.
            connection.send(content: payload, contentContext: .finalMessage, isComplete: true,
                            completion: .contentProcessed { _ in })
            connection.receive(minimumIncompleteLength: 1, maximumLength: 4096) { data, _, _, error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume(returning: data ?? Data())
                }
            }
        }
    }

    @Test(.timeLimit(.minutes(1))) func roundTrip() async throws {
        let inbox = Inbox()
        let server = VoiceServer(token: "123456", version: "t", advertise: false, preferredPort: nil) { inbox.add($0) }
        defer { server.stop() }
        let port = try await waitForPort(server)

        let good = try await send(Data(#"{"token": "123456", "kind": "text", "text": "Hello 囲碁"}"#.utf8), port: port)
        let ack = try JSONDecoder().decode(Ack.self, from: good)
        #expect(ack.ok)
        #expect(ack.app == "Sakamoto Voice")
        #expect(inbox.all == [.text("Hello 囲碁", runs: [LangRun(lang: "default", text: "Hello"), LangRun(lang: "ja", text: "囲碁")])])

        let bad = try await send(Data(#"{"token": "111111", "kind": "text", "text": "Hello"}"#.utf8), port: port)
        #expect(try JSONDecoder().decode(Ack.self, from: bad).error == "bad token")
        #expect(inbox.all.count == 1)
    }

    @Test(.timeLimit(.minutes(1))) func largeAudioArrivesWhole() async throws {
        let inbox = Inbox()
        let server = VoiceServer(token: "123456", version: "t", advertise: false, preferredPort: nil) { inbox.add($0) }
        defer { server.stop() }
        let port = try await waitForPort(server)
        let audio = Data((0..<3_000_000).map { UInt8(truncatingIfNeeded: $0 &* 31) })
        let json = #"{"token": "123456", "kind": "audio", "format": "m4a", "audio_b64": "\#(audio.base64EncodedString())"}"#
        let reply = try await send(Data(json.utf8), port: port)
        #expect(try JSONDecoder().decode(Ack.self, from: reply).ok)
        #expect(inbox.all == [.audio(audio, format: "m4a", text: "")])
    }
}
