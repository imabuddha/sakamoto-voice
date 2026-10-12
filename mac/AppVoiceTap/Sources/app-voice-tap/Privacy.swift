import Darwin
import Foundation
import Synchronization

/// The System Audio Recording permission (TCC's kTCCServiceAudioCapture). There's no public API to
/// look at or ask for it, so this uses TCC's own functions, as audio-capture tools commonly do,
/// and says "unknown" when they aren't there.
enum AudioCapturePermission {
    enum Status: String {
        case granted
        case denied
        case notDetermined = "not determined"
        case unknown
    }

    private static var service: CFString { "kTCCServiceAudioCapture" as CFString }
    nonisolated(unsafe) private static let tcc = dlopen("/System/Library/PrivateFrameworks/TCC.framework/Versions/A/TCC", RTLD_NOW)

    static func status() -> Status {
        guard let tcc, let symbol = dlsym(tcc, "TCCAccessPreflight") else { return .unknown }
        typealias Preflight = @convention(c) (CFString, CFDictionary?) -> Int
        switch unsafeBitCast(symbol, to: Preflight.self)(service, nil) {
        case 0: return .granted
        case 1: return .denied
        case 2: return .notDetermined
        default: return .unknown
        }
    }

    /// Asks (macOS shows its prompt the first time) and waits for the answer; nil when it couldn't ask.
    static func request(timeout: Double = 600) -> Bool? {
        guard let tcc, let symbol = dlsym(tcc, "TCCAccessRequest") else { return nil }
        typealias Request = @convention(c) (CFString, CFDictionary?, @convention(block) @escaping (Bool) -> Void) -> Void
        let answer = Mutex<Bool?>(nil)
        let done = DispatchSemaphore(value: 0)
        unsafeBitCast(symbol, to: Request.self)(service, nil) { granted in
            answer.withLock { $0 = granted }
            done.signal()
        }
        guard done.wait(timeout: .now() + timeout) == .success else { return nil }
        return answer.withLock { $0 }
    }
}

/// macOS's privacy checks ask about the "responsible" process: for a command started by an app
/// (the Claude app runs Claude Code's hooks), that app, not the command. Re-launching with the
/// responsibility disclaimed (as Chromium does for its helpers) makes app-voice-tap responsible for
/// itself, so the permission is asked for, granted to, and listed as app-voice-tap, whoever starts
/// it. The private function may be missing; then it runs as it is.
enum Responsibility {
    static let childVariable = "APP_VOICE_TAP_DISCLAIMED"

    /// Runs this same command again, disclaimed, and returns its exit status; nil when it can't
    /// (or this already is the re-launched one).
    static func relaunchDisclaimed() -> Int32? {
        guard ProcessInfo.processInfo.environment[childVariable] == nil,
              let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "responsibility_spawnattrs_setdisclaim"),
              let executable = Bundle.main.executablePath
        else { return nil }
        typealias Disclaim = @convention(c) (UnsafeMutablePointer<posix_spawnattr_t?>, Int32) -> Int32
        var attributes: posix_spawnattr_t?
        posix_spawnattr_init(&attributes)
        defer { posix_spawnattr_destroy(&attributes) }
        guard unsafeBitCast(symbol, to: Disclaim.self)(&attributes, 1) == 0 else { return nil }

        let arguments = [executable] + CommandLine.arguments.dropFirst()
        var environment = ProcessInfo.processInfo.environment
        environment[childVariable] = "1"
        let argv = arguments.map { strdup($0) } + [nil]
        let envp = environment.map { strdup("\($0.key)=\($0.value)") } + [nil]
        defer {
            argv.forEach { free($0) }
            envp.forEach { free($0) }
        }
        var pid: pid_t = 0
        guard posix_spawn(&pid, executable, nil, &attributes, argv, envp) == 0 else { return nil }

        // Pass on a request to stop (the child is in the same process group, so a group signal
        // reaches it anyway).
        var sources: [DispatchSourceSignal] = []
        for sig in [SIGTERM, SIGINT, SIGHUP] {
            signal(sig, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .global())
            source.setEventHandler { kill(pid, sig) }
            source.resume()
            sources.append(source)
        }
        var status: Int32 = 0
        while waitpid(pid, &status, 0) == -1, errno == EINTR {}
        sources.forEach { $0.cancel() }
        let signalled = status & 0x7F
        return signalled == 0 ? (status >> 8) & 0xFF : 128 + signalled
    }
}
