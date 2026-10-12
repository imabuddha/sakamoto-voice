// app-voice-tap: captures the Claude desktop app's audio, live, for the Sakamoto Voice app on an
// iPhone (speak.py's `output app-phone`). See Options.usage, and README.md for the permission.
//
// Two status lines: "ready" once the tap is running (and, with --to, the phone has accepted the
// stream; speak.py presses Read aloud then), and a one-line result at the end. With --stdout they
// go to standard error, since standard output carries the audio; with --to, to standard output.
// Diagnostics always go to standard error.

import AppVoiceTapCore
import CoreAudio
import Foundation
import SakamotoVoiceKit
import Synchronization

setvbuf(stdout, nil, _IOLBF, 0)
// A reader that goes away must end the stream with an error from write, not kill the process
// before it can remove its tap (PipeSink and PhoneSocket also turn SIGPIPE off on their own).
signal(SIGPIPE, SIG_IGN)

func warn(_ line: String) {
    FileHandle.standardError.write(Data("app-voice-tap: \(line)\n".utf8))
}

let options: Options
do {
    options = try Options.parse(Array(CommandLine.arguments.dropFirst()))
} catch {
    warn("\(error)")
    FileHandle.standardError.write(Data((Options.usage + "\n").utf8))
    exit(2)
}

/// Set by SIGTERM, SIGINT, or SIGHUP; the main loop then cleans up and exits.
let stopRequested = Atomic<Int32>(0)

enum Exit {
    static let ok: Int32 = 0
    static let permission: Int32 = 3
    static let phone: Int32 = 4
    static let tap: Int32 = 5
    static let noSound: Int32 = 6
}

// MARK: - --list and --check

func listProcesses() -> Int32 {
    let matcher = ProcessMatcher(appPath: options.appPath, bundleIDs: options.bundleIDs)
    let processes = HAL.processes().sorted { $0.pid < $1.pid }
    print("Processes Core Audio knows (C: the Claude app's, as tapped; P: playing audio now):")
    for process in processes {
        let claude = matcher.matches(bundleID: process.bundleID, path: process.path) ? "C" : " "
        let playing = process.isPlaying ? "P" : " "
        let pid = String(process.pid).padding(toLength: 7, withPad: " ", startingAt: 0)
        let bundle = (process.bundleID.isEmpty ? "-" : process.bundleID).padding(toLength: 44, withPad: " ", startingAt: 0)
        print("\(claude)\(playing) \(pid) \(bundle) \(process.path)")
    }
    return Exit.ok
}

func checkPermission() -> Int32 {
    let status = AudioCapturePermission.status()
    print("System Audio Recording for app-voice-tap: \(status.rawValue).")
    switch status {
    case .granted:
        return Exit.ok
    case .denied:
        print("Turn it on in System Settings → Privacy & Security → Screen & System Audio Recording, "
              + "under System Audio Recording Only (app-voice-tap).")
        return Exit.permission
    case .notDetermined, .unknown:
        print("Asking macOS; answer its prompt (Allow).")
        switch AudioCapturePermission.request() {
        case true?:
            print("Allowed.")
            return Exit.ok
        case false?:
            print("Not allowed. To change that: System Settings → Privacy & Security → Screen & System "
                  + "Audio Recording, under System Audio Recording Only (app-voice-tap).")
            return Exit.permission
        case nil:
            print("Couldn't ask here; macOS asks the first time app-voice-tap taps the Claude app.")
            return Exit.permission
        }
    }
}

// MARK: - Streaming

final class Streamer {
    let options: Options
    let matcher: ProcessMatcher
    var sink: AudioSink?
    var tap: AppTap?
    var gate: StreamGate?
    var resampler: Resampler?

    init(_ options: Options) {
        self.options = options
        matcher = ProcessMatcher(appPath: options.appPath, bundleIDs: options.bundleIDs)
    }

    func note(_ line: String) {
        if options.verbose { warn(line) }
    }

    /// A status line ("ready", the result): on standard output, unless that carries the audio.
    func status(_ line: String) {
        if options.toStdout {
            FileHandle.standardError.write(Data((line + "\n").utf8))
        } else {
            print(line)
        }
    }

    /// Prints the result line and returns the exit status.
    func finish(_ status: Int32, _ line: String) -> Int32 {
        tap?.stop()
        tap = nil
        sink?.close()
        self.status(line)
        return status
    }

    var address: String { "\(options.host):\(options.port)" }
    /// Where the audio goes, for the result line.
    var destination: String { options.toStdout ? "standard output" : address }
    /// What it means when the other end goes away.
    var otherEndClosed: String {
        options.toStdout ? "the reader closed standard output" : "the phone ended the stream (a newer message or Stop)"
    }

    func claudeProcesses() -> [HAL.Process] {
        let me = getpid()
        return HAL.processes().filter { $0.pid != me && matcher.matches(bundleID: $0.bundleID, path: $0.path) }
    }

    func describe(_ processes: [HAL.Process]) -> String {
        processes.map { "\($0.pid) \($0.bundleID.isEmpty ? ($0.path as NSString).lastPathComponent : $0.bundleID)" }
            .joined(separator: ", ")
    }

    /// Bundle IDs can be named in a tap from macOS 26.
    var tapsByBundleID: Bool {
        if #available(macOS 26.0, *) { options.tapByBundleID } else { false }
    }

    func makeTap(_ processes: [HAL.Process]) throws(HAL.Failure) {
        let bundleIDs = tapsByBundleID ? matcher.tapBundleIDs(seen: processes.map(\.bundleID)) : nil
        let tap = try AppTap(processes: processes.map(\.object), bundleIDs: bundleIDs, mute: options.mute,
                             outputSubdevice: options.outputSubdevice, log: note)
        do {
            try tap.start()
        } catch {
            tap.stop()
            throw error
        }
        guard let resampler = Resampler(inputRate: tap.sampleRate, outputRate: Double(options.rate)) else {
            tap.stop()
            throw HAL.Failure(what: "making a converter from \(tap.sampleRate) Hz", status: OSStatus(kAudioHardwareUnspecifiedError))
        }
        self.tap = tap
        self.resampler = resampler
        gate = StreamGate(sampleRate: tap.sampleRate, silenceSeconds: options.silenceSeconds,
                          maxSeconds: options.maxSeconds, thresholdDB: options.thresholdDB)
        note("tapping \(processes.isEmpty ? "by bundle ID" : describe(processes))\(options.mute ? ", muted on the Mac" : "")")
    }

    /// Looks for the Claude app's processes again: the first time one appears, the tap is made;
    /// later ones (such as an audio helper starting) join it.
    func rescan() {
        let found = claudeProcesses()
        guard !found.isEmpty else { return }
        if let tap {
            let before = Set(tap.processes)
            do {
                try tap.update(processes: found.map(\.object))
                if Set(tap.processes) != before { note("now tapping \(describe(found))") }
            } catch {
                warn("\(error)")
            }
        } else {
            do {
                try makeTap(found)
            } catch {
                warn("\(error)")
            }
        }
    }

    /// With --to: connects to the phone, which must accept the stream before anything is tapped.
    /// Nil once it has; else the exit status (the result line printed).
    func connectToPhone() -> Int32? {
        var text = options.text
        if options.textFromStdin {
            text = String(decoding: FileHandle.standardInput.readDataToEndOfFile(), as: UTF8.self)
        }
        do {
            let socket = try PhoneSocket.connect(host: options.host, port: options.port)
            sink = socket
            try socket.send(VoiceMessage.streamHeader(token: options.token, text: text, rate: options.rate))
            let line = try socket.readLine(timeout: 4)
            guard let ack = try? JSONDecoder().decode(Ack.self, from: line) else {
                return finish(Exit.phone, "the phone at \(address) didn't answer properly")
            }
            guard ack.ok else {
                if ack.want == .text {
                    return finish(Exit.phone, "the phone at \(address) wants the text, not the stream (its Claude's Voice setting)")
                }
                return finish(Exit.phone, "the phone at \(address) refused the stream: \(ack.error ?? "?")")
            }
            note("the phone (\(ack.app) \(ack.version)) accepted the stream")
            return nil
        } catch .timeout {
            return finish(Exit.phone, "the phone at \(address) didn't answer the stream (is its app 0.3.0 or later?)")
        } catch {
            return finish(Exit.phone, "the phone at \(address): \(error)")
        }
    }

    func run() -> Int32 {
        for sig in [SIGTERM, SIGINT, SIGHUP] {
            signal(sig, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .global())
            source.setEventHandler { stopRequested.store(sig, ordering: .relaxed) }
            source.resume()
            signalSources.append(source)
        }

        if options.permissionCheck {
            switch AudioCapturePermission.status() {
            case .denied:
                return finish(Exit.permission, "System Audio Recording is off for app-voice-tap: turn it on in System "
                              + "Settings → Privacy & Security → Screen & System Audio Recording")
            case .notDetermined:
                warn("System Audio Recording isn't allowed yet; macOS will ask (or run app-voice-tap --check)")
            case .granted, .unknown:
                break
            }
        }

        if options.toStdout {
            sink = PipeSink()
        } else if let failed = connectToPhone() {
            return failed
        }

        let found = claudeProcesses()
        if !found.isEmpty || tapsByBundleID {
            do {
                try makeTap(found)
            } catch {
                if !found.isEmpty {
                    return finish(Exit.tap, "couldn't tap the Claude app: \(error)")
                }
                note("no tap yet (\(error)); waiting for the Claude app to use audio")
            }
        } else {
            note("no Claude app process has used audio yet; tapping when one does")
        }

        status("ready")
        let readyAt = Date()
        var lastScan = readyAt
        var line: (Int32, String)?
        while line == nil {
            if stopRequested.load(ordering: .relaxed) != 0 {
                line = (Exit.ok, "stopped after streaming \(seconds) to \(destination)")
                break
            }
            usleep(20_000)
            if sink?.peerClosed() ?? true {
                line = (Exit.ok, "streamed \(seconds) to \(destination); \(otherEndClosed)")
                break
            }
            let now = Date()
            if now.timeIntervalSince(lastScan) >= (gate?.hasBegun == true ? 1.0 : 0.1) {
                lastScan = now
                rescan()
            }
            if let tap, var gate, let resampler, let sink {
                let samples = tap.queue.drain()
                if !samples.isEmpty {
                    let waiting = !gate.hasBegun
                    let out = gate.process(samples)
                    self.gate = gate
                    if waiting, gate.hasBegun {
                        note(String(format: "sound began %.1f s after ready", now.timeIntervalSince(readyAt)))
                    }
                    if !out.isEmpty {
                        do {
                            try sink.send(PCM16.data(resampler.convert(out)))
                        } catch .closed {
                            line = (Exit.ok, "streamed \(seconds) to \(destination); \(otherEndClosed)")
                        } catch {
                            line = (Exit.phone, "sending to \(options.toStdout ? "standard output" : "the phone at \(address)") "
                                    + "failed after \(seconds): \(error)")
                        }
                    }
                }
                if case .ended(let reason) = gate.state, line == nil {
                    try? sink.send(PCM16.data(resampler.flush()))
                    line = (Exit.ok, reason == .silence
                        ? "streamed \(seconds) to \(destination); the app went quiet"
                        : "streamed \(seconds) to \(destination); stopped at the \(Int(options.maxSeconds)) s limit")
                }
            }
            if line == nil, gate?.hasBegun != true, now.timeIntervalSince(readyAt) > options.waitStart {
                line = (Exit.noSound, "no sound from the Claude app within \(options.waitStart) s"
                        + (tap == nil ? " (none of its processes had used audio)" : ""))
            }
        }
        tap?.stop()
        tap = nil
        if line?.0 == Exit.ok, stopRequested.load(ordering: .relaxed) == 0 {
            sink?.finish(timeout: 2)
        }
        let (status, result) = line ?? (Exit.ok, "done")
        return finish(status, result)
    }

    var seconds: String { String(format: "%.1f s", gate?.sentSeconds ?? 0) }

    private var signalSources: [DispatchSourceSignal] = []
}

// MARK: - Main

switch options.mode {
case .help:
    print(Options.usage)
    exit(Exit.ok)
case .list:
    exit(listProcesses())
case .check, .stream:
    if options.disclaim, let status = Responsibility.relaunchDisclaimed() {
        exit(status)
    }
    exit(options.mode == .check ? checkPermission() : Streamer(options).run())
}
