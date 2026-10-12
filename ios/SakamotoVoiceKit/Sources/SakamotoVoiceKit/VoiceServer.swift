import Foundation
import Network

/// The receiver: a TCP listener advertised with Bonjour. Each connection carries one JSON message
/// (read until the sender closes its side), which is checked against the pairing code and
/// answered with an `Ack`, or a stream: a header line, answered at once, then live audio until
/// the sender closes (see `VoiceProtocol`). Accepted messages, and a stream's start, audio, and
/// end, go to `handler` in order, on the server's own queue.
public final class VoiceServer: @unchecked Sendable {
    public enum State: Equatable, Sendable {
        case stopped
        case starting
        case listening(port: UInt16)
        case failed(String)
    }

    public typealias Handler = @Sendable (Incoming) -> Void

    private let queue = DispatchQueue(label: "com.pragmaphilia.SakamotoVoice.server")
    private let handler: Handler
    private let version: String
    private let advertise: Bool
    private let serviceName: String?
    private let preferredPort: UInt16?
    private let connectionTimeout: TimeInterval
    private let streamIdleTimeout: TimeInterval

    // The rest is touched only on `queue`.
    private var listener: NWListener?
    private var token: String
    private var gate = TokenGate()
    private var stateHandler: (@Sendable (State) -> Void)?
    private var wanted = false
    private var usePreferredPort = true
    private var generation = 0

    /// - Parameters:
    ///   - token: the pairing code messages must carry.
    ///   - version: the app's version, for acks.
    ///   - advertise: publish `_sakamotovoice._tcp` with Bonjour (off in tests).
    ///   - serviceName: the Bonjour instance name; nil uses the device's name.
    ///   - preferredPort: the port to ask for first; nil for any.
    ///   - connectionTimeout: how long a message may take to arrive.
    ///   - streamIdleTimeout: how long a stream may go without sending anything.
    public init(token: String, version: String, advertise: Bool = true, serviceName: String? = nil,
                preferredPort: UInt16? = VoiceProtocol.preferredPort, connectionTimeout: TimeInterval = 30,
                streamIdleTimeout: TimeInterval = VoiceProtocol.streamIdleTimeout,
                handler: @escaping Handler) {
        self.token = token
        self.version = version
        self.advertise = advertise
        self.serviceName = serviceName
        self.preferredPort = preferredPort
        self.connectionTimeout = connectionTimeout
        self.streamIdleTimeout = streamIdleTimeout
        self.handler = handler
    }

    /// Called on the server's queue whenever the listener's state changes.
    public func onStateChange(_ handler: @escaping @Sendable (State) -> Void) {
        queue.async { self.stateHandler = handler }
    }

    public func setToken(_ token: String) {
        queue.async {
            self.token = token
            self.gate = TokenGate()
        }
    }

    public func start() {
        queue.async {
            self.wanted = true
            if self.listener == nil { self.makeListener() }
        }
    }

    public func stop() {
        queue.async {
            self.wanted = false
            self.tearDown()
            self.report(.stopped)
        }
    }

    /// A fresh listener, for after the app was suspended (its socket may be dead while it still
    /// looks ready).
    public func restart() {
        queue.async {
            self.wanted = true
            self.tearDown()
            self.makeListener()
        }
    }

    // MARK: - Listening

    private func report(_ state: State) {
        stateHandler?(state)
    }

    private func tearDown() {
        generation += 1
        listener?.stateUpdateHandler = nil
        listener?.newConnectionHandler = nil
        listener?.cancel()
        listener = nil
    }

    private func makeListener() {
        report(.starting)
        let parameters = NWParameters.tcp
        parameters.allowLocalEndpointReuse = true
        let listener: NWListener
        do {
            if usePreferredPort, let preferredPort, let port = NWEndpoint.Port(rawValue: preferredPort) {
                listener = try NWListener(using: parameters, on: port)
            } else {
                listener = try NWListener(using: parameters)
            }
        } catch {
            if usePreferredPort {
                usePreferredPort = false
                makeListener()
            } else {
                report(.failed("\(error)"))
                retryLater()
            }
            return
        }
        if advertise {
            listener.service = NWListener.Service(name: serviceName, type: VoiceProtocol.serviceType)
        }
        let current = generation
        listener.stateUpdateHandler = { [weak self, weak listener] state in
            guard let self, current == self.generation else { return }
            switch state {
            case .ready:
                self.report(.listening(port: listener?.port?.rawValue ?? 0))
            case .failed(let error):
                self.report(.failed("\(error)"))
                if case .posix(let code) = error, code == .EADDRINUSE {
                    self.usePreferredPort = false
                }
                self.tearDown()
                self.retryLater()
            case .waiting(let error):
                self.report(.failed("waiting: \(error)"))
            default:
                break
            }
        }
        listener.newConnectionHandler = { [weak self] connection in
            self?.accept(connection)
        }
        self.listener = listener
        listener.start(queue: queue)
    }

    private func retryLater() {
        queue.asyncAfter(deadline: .now() + 2) {
            if self.wanted, self.listener == nil { self.makeListener() }
        }
    }

    // MARK: - Connections

    /// One connection's progress: a message being read whole, or a stream (see `VoiceProtocol`).
    /// Touched only on the server's queue.
    private final class Inbound: @unchecked Sendable {
        let connection: NWConnection
        var buffer = Data()
        /// How far the buffer has been searched for a stream's header line.
        var scanned = 0
        /// Known not to be a stream: read to the end.
        var isMessage = false
        var stream: StreamInfo?
        var framer = PCMFramer(bytesPerFrame: 2)
        var lastActivity = Date()
        var finished = false

        init(_ connection: NWConnection) {
            self.connection = connection
        }
    }

    /// The stream playing now, if any; a newer message ends it.
    private var activeStream: Inbound?
    private var streamCount = 0

    private func accept(_ connection: NWConnection) {
        let inbound = Inbound(connection)
        connection.start(queue: queue)
        queue.asyncAfter(deadline: .now() + connectionTimeout) { [weak self] in
            self?.expire(inbound)
        }
        receive(inbound)
    }

    /// A message must arrive within `connectionTimeout`; a stream may run longer, as long as it
    /// keeps sending.
    private func expire(_ inbound: Inbound) {
        guard !inbound.finished else { return }
        if inbound.stream != nil, Date().timeIntervalSince(inbound.lastActivity) < streamIdleTimeout {
            queue.asyncAfter(deadline: .now() + min(5, streamIdleTimeout)) { [weak self] in
                self?.expire(inbound)
            }
            return
        }
        end(inbound)
    }

    private func receive(_ inbound: Inbound) {
        inbound.connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 16) { [weak self] data, _, isComplete, error in
            guard let self, !inbound.finished else { return }
            if let data, !data.isEmpty {
                inbound.lastActivity = Date()
                self.take(data, inbound)
                if inbound.finished { return }
            }
            if isComplete {
                if inbound.stream != nil {
                    self.end(inbound)
                } else {
                    inbound.finished = true
                    self.reply(on: inbound.connection, self.handle(inbound.buffer))
                }
            } else if error != nil {
                self.end(inbound)
            } else {
                self.receive(inbound)
            }
        }
    }

    private func take(_ data: Data, _ inbound: Inbound) {
        if inbound.stream != nil {
            deliver(data, inbound)
            return
        }
        inbound.buffer.append(data)
        if inbound.buffer.count > VoiceProtocol.maxMessageBytes {
            inbound.finished = true
            reply(on: inbound.connection, .failure(.tooLarge, version: version))
            return
        }
        guard !inbound.isMessage else { return }
        switch StreamHeaderScan.scan(inbound.buffer, from: inbound.scanned) {
        case .needMore:
            inbound.scanned = inbound.buffer.count
        case .notAStream:
            inbound.isMessage = true
        case .stream(let message, let rest):
            inbound.buffer = Data()
            startStream(message, rest: rest, inbound)
        }
    }

    /// Checks a stream's header and answers it at once; the audio follows.
    private func startStream(_ message: VoiceMessage, rest: Data, _ inbound: Inbound, now: Date = Date()) {
        var info: StreamInfo
        do {
            switch gate.check(message.token, expected: token, now: now) {
            case .accepted: break
            case .rejected: throw MessageError.badToken
            case .lockedOut: throw MessageError.lockedOut
            }
            info = try MessageDecoder.validateStream(message)
        } catch {
            inbound.finished = true
            reply(on: inbound.connection, .failure((error as? MessageError) ?? .malformed, version: version))
            return
        }
        endActiveStream()
        streamCount += 1
        info.id = streamCount
        inbound.stream = info
        inbound.framer = PCMFramer(bytesPerFrame: info.bytesPerFrame)
        activeStream = inbound
        handler(.streamStart(info))
        inbound.connection.send(content: Ack.success(version: version).encoded(), completion: .contentProcessed { _ in })
        if !rest.isEmpty { deliver(rest, inbound) }
    }

    private func deliver(_ data: Data, _ inbound: Inbound) {
        guard let stream = inbound.stream else { return }
        let frames = inbound.framer.frames(from: data)
        if !frames.isEmpty { handler(.streamAudio(id: stream.id, frames)) }
    }

    /// Closes a connection; a stream's end is handed on (unless a newer message replaced it).
    private func end(_ inbound: Inbound) {
        guard !inbound.finished else { return }
        inbound.finished = true
        if let stream = inbound.stream {
            if activeStream === inbound { activeStream = nil }
            handler(.streamEnd(id: stream.id))
        }
        inbound.connection.cancel()
    }

    /// A newer message replaces the stream playing now: its connection is closed, which tells the
    /// sender to stop.
    private func endActiveStream() {
        guard let stream = activeStream else { return }
        activeStream = nil
        stream.finished = true
        stream.connection.cancel()
    }

    /// Decodes, checks the pairing code, validates, and hands the message on.
    func handle(_ data: Data, now: Date = Date()) -> Ack {
        let incoming: Incoming
        do {
            let message = try MessageDecoder.decode(data)
            switch gate.check(message.token, expected: token, now: now) {
            case .accepted: break
            case .rejected: return .failure(.badToken, version: version)
            case .lockedOut: return .failure(.lockedOut, version: version)
            }
            incoming = try MessageDecoder.validate(message)
        } catch {
            return .failure(error, version: version)
        }
        if incoming != .ping { endActiveStream() }
        handler(incoming)
        return .success(version: version)
    }

    private func reply(on connection: NWConnection, _ ack: Ack) {
        connection.send(content: ack.encoded(), contentContext: .finalMessage, isComplete: true,
                        completion: .contentProcessed { _ in connection.cancel() })
    }
}
