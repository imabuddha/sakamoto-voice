import Darwin
import Foundation

/// A plain blocking TCP connection to the phone, with timeouts: connect, send the stream's header,
/// read the phone's answer line, send audio, and close. Writes never raise SIGPIPE.
public final class PhoneSocket {
    public enum Failure: Error, Equatable, CustomStringConvertible {
        case resolve(String)
        case connect(String)
        case timeout
        case closed
        case io(String)

        public var description: String {
            switch self {
            case .resolve(let why): "can't find the host: \(why)"
            case .connect(let why): "can't connect: \(why)"
            case .timeout: "timed out"
            case .closed: "the phone closed the connection"
            case .io(let why): why
            }
        }
    }

    private var fd: Int32
    private var readBuffer = Data()

    private init(fd: Int32) {
        self.fd = fd
    }

    deinit { close() }

    /// Connects to the first of the host's addresses that answers within `timeout` seconds each.
    public static func connect(host: String, port: UInt16, timeout: Double = 4) throws(Failure) -> PhoneSocket {
        var hints = addrinfo()
        hints.ai_family = AF_UNSPEC
        hints.ai_socktype = SOCK_STREAM
        hints.ai_protocol = IPPROTO_TCP
        var list: UnsafeMutablePointer<addrinfo>?
        let status = getaddrinfo(host, String(port), &hints, &list)
        guard status == 0, let first = list else {
            throw .resolve(String(cString: gai_strerror(status)))
        }
        defer { freeaddrinfo(list) }
        var lastError = "no address"
        var node: UnsafeMutablePointer<addrinfo>? = first
        while let info = node {
            node = info.pointee.ai_next
            let fd = socket(info.pointee.ai_family, info.pointee.ai_socktype, info.pointee.ai_protocol)
            guard fd >= 0 else {
                lastError = String(cString: strerror(errno))
                continue
            }
            var on: Int32 = 1
            setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &on, socklen_t(MemoryLayout<Int32>.size))
            let flags = fcntl(fd, F_GETFL)
            _ = fcntl(fd, F_SETFL, flags | O_NONBLOCK)
            var result = Darwin.connect(fd, info.pointee.ai_addr, info.pointee.ai_addrlen)
            if result != 0, errno == EINPROGRESS {
                var pfd = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
                if poll(&pfd, 1, Int32(timeout * 1000)) == 1 {
                    var error: Int32 = 0
                    var length = socklen_t(MemoryLayout<Int32>.size)
                    getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &length)
                    result = error == 0 ? 0 : -1
                    errno = error
                } else {
                    result = -1
                    errno = ETIMEDOUT
                }
            }
            if result == 0 {
                _ = fcntl(fd, F_SETFL, flags & ~O_NONBLOCK)
                var send = timeval(tv_sec: 5, tv_usec: 0)
                setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &send, socklen_t(MemoryLayout<timeval>.size))
                return PhoneSocket(fd: fd)
            }
            lastError = String(cString: strerror(errno))
            Darwin.close(fd)
        }
        throw .connect(lastError)
    }

    /// Sends all of `data` (blocking; a stuck phone times out after a few seconds).
    public func send(_ data: Data) throws(Failure) {
        guard fd >= 0 else { throw .closed }
        var failure: Failure?
        data.withUnsafeBytes { raw in
            guard var pointer = raw.baseAddress else { return }
            var left = raw.count
            while left > 0 {
                let sent = Darwin.send(fd, pointer, left, 0)
                if sent < 0 {
                    if errno == EINTR { continue }
                    failure = (errno == EPIPE || errno == ECONNRESET) ? .closed
                        : errno == EAGAIN ? .timeout : .io(String(cString: strerror(errno)))
                    return
                }
                left -= sent
                pointer += sent
            }
        }
        if let failure { throw failure }
    }

    /// One line from the phone (without its newline), waiting at most `timeout` seconds.
    public func readLine(timeout: Double) throws(Failure) -> Data {
        let deadline = Date().addingTimeInterval(timeout)
        while true {
            if let newline = readBuffer.firstIndex(of: 0x0A) {
                let line = Data(readBuffer[..<newline])
                readBuffer = Data(readBuffer[(newline + 1)...])
                return line
            }
            let left = deadline.timeIntervalSinceNow
            guard left > 0 else { throw .timeout }
            switch try waitReadable(timeout: left) {
            case false: throw .timeout
            case true:
                var chunk = [UInt8](repeating: 0, count: 4096)
                let n = recv(fd, &chunk, chunk.count, 0)
                if n == 0 { throw .closed }
                if n < 0 {
                    if errno == EINTR { continue }
                    throw .io(String(cString: strerror(errno)))
                }
                readBuffer.append(contentsOf: chunk[0..<n])
            }
        }
    }

    /// Whether the phone has closed its side (it does when a newer message replaces the stream).
    /// Never waits; bytes it sends meanwhile are ignored.
    public func peerClosed() -> Bool {
        guard fd >= 0 else { return true }
        while (try? waitReadable(timeout: 0)) == true {
            var chunk = [UInt8](repeating: 0, count: 4096)
            let n = recv(fd, &chunk, chunk.count, 0)
            if n == 0 { return true }
            if n < 0 { return errno != EINTR && errno != EAGAIN }
        }
        return false
    }

    /// Closes the sending side (the end of the stream), then waits up to `timeout` seconds for
    /// the phone to close its side, so the last audio isn't cut off by a reset; then closes.
    public func finish(timeout: Double = 2) {
        guard fd >= 0 else { return }
        shutdown(fd, SHUT_WR)
        let deadline = Date().addingTimeInterval(timeout)
        while deadline.timeIntervalSinceNow > 0, (try? waitReadable(timeout: deadline.timeIntervalSinceNow)) == true {
            var chunk = [UInt8](repeating: 0, count: 4096)
            if recv(fd, &chunk, chunk.count, 0) <= 0 { break }
        }
        close()
    }

    public func close() {
        if fd >= 0 {
            Darwin.close(fd)
            fd = -1
        }
    }

    private func waitReadable(timeout: Double) throws(Failure) -> Bool {
        var pfd = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
        let result = poll(&pfd, 1, Int32(max(0, timeout) * 1000))
        if result < 0 {
            if errno == EINTR { return false }
            throw .io(String(cString: strerror(errno)))
        }
        return result > 0
    }
}
