import Darwin
import Foundation

/// Where the tapped audio goes: the phone (`PhoneSocket`, with `--to`) or a pipe (`PipeSink`, with
/// `--stdout`, read by speak.py, which sends it to the phone).
public protocol AudioSink: AnyObject {
    /// Sends all of `data`; `.closed` when the other end has gone away.
    func send(_ data: Data) throws(PhoneSocket.Failure)
    /// Whether the other end has gone away. Never waits.
    func peerClosed() -> Bool
    /// Ends the stream normally (letting the last audio arrive), then closes.
    func finish(timeout: Double)
    func close()
}

extension PhoneSocket: AudioSink {}

/// Raw audio written to a file descriptor (standard output, a pipe). Writes never raise SIGPIPE:
/// when the reader has gone away, `send` throws `.closed`.
public final class PipeSink: AudioSink {
    private var fd: Int32

    public init(fd: Int32 = STDOUT_FILENO) {
        self.fd = fd
        _ = fcntl(fd, F_SETNOSIGPIPE, 1)
    }

    public func send(_ data: Data) throws(PhoneSocket.Failure) {
        guard fd >= 0 else { throw .closed }
        var failure: PhoneSocket.Failure?
        data.withUnsafeBytes { raw in
            guard var pointer = raw.baseAddress else { return }
            var left = raw.count
            while left > 0 {
                let written = write(fd, pointer, left)
                if written < 0 {
                    if errno == EINTR { continue }
                    failure = errno == EPIPE ? .closed : .io(String(cString: strerror(errno)))
                    return
                }
                left -= written
                pointer += written
            }
        }
        if let failure { throw failure }
    }

    /// True once the reader has closed its end (poll reports a hang-up on the writing end).
    public func peerClosed() -> Bool {
        guard fd >= 0 else { return true }
        var pfd = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
        guard poll(&pfd, 1, 0) == 1 else { return false }
        return pfd.revents & Int16(POLLHUP | POLLERR | POLLNVAL) != 0
    }

    /// Nothing to wait for: the reader sees the end when the process exits.
    public func finish(timeout: Double = 0) {}

    /// Stops writing (the descriptor itself stays open; it's standard output).
    public func close() {
        fd = -1
    }
}
