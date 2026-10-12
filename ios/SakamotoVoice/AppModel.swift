import AVFoundation
import Observation
import SakamotoVoiceKit
import SwiftUI
import UIKit

/// A message as the screen shows it.
struct ShownMessage: Identifiable, Equatable {
    enum Source: Equatable {
        /// Text, spoken here in the phone's voices.
        case text
        /// Audio the Mac rendered in its voices.
        case macAudio
        /// The Claude app's own voice, streamed live.
        case appStream
    }

    let id = UUID()
    let date: Date
    let text: String
    let source: Source
}

/// Ties the receiver, the speaker, the keep-alive, and the settings together.
@MainActor @Observable
final class AppModel {
    static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    static let historyLength = 5

    let settings = Settings()
    let speaker = Speaker()
    let keepAlive = KeepAlive()

    /// Newest first.
    private(set) var messages: [ShownMessage] = []
    private(set) var serverState: VoiceServer.State = .stopped
    /// When a ping last arrived (the Mac pairing or testing).
    private(set) var lastPing: Date?
    private(set) var isActive = true

    @ObservationIgnored private var server: VoiceServer!
    @ObservationIgnored private var last: Incoming?
    @ObservationIgnored private var scheduleTimer: Timer?
    @ObservationIgnored private var wasSuspendable = false
    /// The stream arriving now, and whether its text is on screen yet (it appears with the first
    /// audio, so a stream that brings none, followed by the text, doesn't show it twice).
    @ObservationIgnored private var stream: StreamInfo?
    @ObservationIgnored private var streamShown = false

    init() {
        KeepAlive.configureSession()
        // In order, on the main queue: a stream's audio must follow its start.
        server = VoiceServer(token: settings.pairingCode, version: Self.version) { [weak self] incoming in
            DispatchQueue.main.async {
                MainActor.assumeIsolated { self?.receive(incoming) }
            }
        }
        speaker.stream.onFinished = { [weak self] audio, info in
            // Repeat plays the stream again, as a WAV.
            self?.last = .audio(WAV.pcm16(audio, sampleRate: info.sampleRate, channels: info.channels),
                                format: "wav", text: info.text)
        }
        server.onStateChange { [weak self] state in
            DispatchQueue.main.async {
                MainActor.assumeIsolated { self?.serverState = state }
            }
        }
        server.start()
        evaluateKeepAlive()
        // Re-check the schedule every half minute (a timer runs in the background while awake).
        scheduleTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.evaluateKeepAlive() }
        }
    }

    // MARK: - Messages

    func receive(_ incoming: Incoming) {
        switch incoming {
        case .ping:
            lastPing = Date()
            return
        case .stop:
            stream = nil
            speaker.stop()
            return
        case .streamStart(let info):
            stream = info
            streamShown = false
            speaker.startStream(info)
            return
        case .streamAudio(let id, let audio):
            guard let stream, stream.id == id else { return }
            if !streamShown {
                streamShown = true
                show(stream.text, source: .appStream)
            }
            speaker.stream.feed(audio)
            return
        case .streamEnd(let id):
            guard stream?.id == id else { return }
            stream = nil
            speaker.stream.end()
            return
        case .text(let text, _):
            stream = nil
            show(text, source: .text)
        case .audio(_, _, let text):
            stream = nil
            show(text, source: .macAudio)
        }
        last = incoming
        perform(incoming)
    }

    private func show(_ text: String, source: ShownMessage.Source) {
        messages.insert(ShownMessage(date: Date(), text: text, source: source), at: 0)
        if messages.count > Self.historyLength {
            messages.removeLast(messages.count - Self.historyLength)
        }
    }

    private func perform(_ incoming: Incoming) {
        try? AVAudioSession.sharedInstance().setActive(true)
        switch incoming {
        case .text(_, let runs):
            speaker.speak(runs, englishVoice: Voices.english(settings.englishVoiceID),
                          japaneseVoice: Voices.japanese(settings.japaneseVoiceID),
                          defaultIsJapanese: settings.defaultVoice.isJapanese, rate: settings.rate)
        case .audio(let data, let format, _):
            speaker.play(data, format: format)
        case .ping, .stop, .streamStart, .streamAudio, .streamEnd:
            break
        }
    }

    func stop() {
        stream = nil
        speaker.stop()
    }

    func repeatLast() {
        guard let last else { return }
        stream = nil
        perform(last)
    }

    var canRepeat: Bool { last != nil }

    /// A sample line in the chosen voices, from Settings: the English in the default voice.
    func preview() {
        let text = "Good heavens, Miss Sakamoto, you can talk! そうやで。"
        stream = nil
        perform(.text(text, runs: LanguageSplitter.runs(in: text, other: LangRun.phoneDefault)))
    }

    // MARK: - Pairing

    func newPairingCode() {
        settings.pairingCode = PairingCode.generate()
        server.setToken(settings.pairingCode)
    }

    // MARK: - Staying awake

    var isAwakeInBackground: Bool { keepAlive.isRunning }

    func evaluateKeepAlive() {
        keepAlive.setWanted(settings.keepAlivePolicy.isAwake(at: Date()))
        updateIdleTimer()
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        switch phase {
        case .active:
            isActive = true
            // Without the keep-alive the app was suspended; its listener may be dead.
            if wasSuspendable { server.restart() }
            wasSuspendable = false
            evaluateKeepAlive()
        case .background:
            isActive = false
            wasSuspendable = !keepAlive.isRunning
        default:
            isActive = false
        }
        updateIdleTimer()
    }

    private func updateIdleTimer() {
        UIApplication.shared.isIdleTimerDisabled = isActive && settings.keepScreenOn
    }

    /// The next time the schedule starts or ends, for the Settings footer.
    var nextScheduleChange: Date? {
        settings.useSchedule ? settings.schedule.nextChange(after: Date()) : nil
    }
}
