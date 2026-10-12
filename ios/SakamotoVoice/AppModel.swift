import AVFoundation
import Network
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

/// Ties the receiver, the speaker, the keep-alive, the network path, the Apple Watch link, and the
/// settings together.
@MainActor @Observable
final class AppModel {
    static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    static let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0"
    static let historyLength = 5

    let settings = Settings()
    let speaker = Speaker()
    let keepAlive = KeepAlive()
    /// Claude's Voice and the network path, for the receiver's answers (read on its queue).
    let voicePreference = VoicePreference()
    /// The Apple Watch app: each message is mirrored to it.
    let watch = WatchLink()

    /// Newest first.
    private(set) var messages: [ShownMessage] = []
    private(set) var serverState: VoiceServer.State = .stopped
    /// When a ping last arrived (the Mac pairing or testing).
    private(set) var lastPing: Date?
    private(set) var isActive = true
    /// Whether the phone's network path is cellular or otherwise expensive; nil until known.
    private(set) var onCellular: Bool?

    @ObservationIgnored private var server: VoiceServer!
    @ObservationIgnored private var last: Incoming?
    @ObservationIgnored private var scheduleTimer: Timer?
    @ObservationIgnored private var wasSuspendable = false
    /// The stream arriving now, and whether its text is on screen yet (it appears with the first
    /// audio, so a stream that brings none, followed by the text, doesn't show it twice).
    @ObservationIgnored private var stream: StreamInfo?
    @ObservationIgnored private var streamShown = false
    @ObservationIgnored private let pathMonitor = NWPathMonitor()

    init() {
        KeepAlive.configureSession()
        voicePreference.policy = settings.voicePolicy
        // In order, on the main queue: a stream's audio must follow its start. Each answer says
        // what the phone wants now (the setting and the path as they are when it answers).
        server = VoiceServer(token: settings.pairingCode, version: Self.version,
                             voice: { [voicePreference] in voicePreference.want }) { [weak self] incoming in
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
        watch.onSpeak = { [weak self] message in self?.speakMirrored(message) }
        watch.onStateChange = { [weak self] in self?.mirrorChanged() }
        server.start()
        watchThePath()
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
                show(stream.text, source: .appStream, runs: nil)
            }
            speaker.stream.feed(audio)
            return
        case .streamEnd(let id):
            guard stream?.id == id else { return }
            stream = nil
            speaker.stream.end()
            return
        case .text(let text, let runs):
            stream = nil
            show(text, source: .text, runs: runs)
        case .audio(_, _, let text):
            stream = nil
            show(text, source: .macAudio, runs: nil)
        }
        last = incoming
        perform(incoming)
    }

    /// Shows a message, and mirrors it to the watch; `runs` are the Mac's, when it sent them.
    private func show(_ text: String, source: ShownMessage.Source, runs: [LangRun]?) {
        let message = ShownMessage(date: Date(), text: text, source: source)
        messages.insert(message, at: 0)
        if messages.count > Self.historyLength {
            messages.removeLast(messages.count - Self.historyLength)
        }
        mirror(message, runs: runs)
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

    // MARK: - The Apple Watch

    /// Mirroring is on and the watch app is installed.
    var mirrorsToWatch: Bool { settings.mirrorToWatch && watch.isWatchAppInstalled }

    /// To the watch app, and, while this app isn't on screen (so a phone in hand isn't nagged),
    /// as a notification for the watch.
    private func mirror(_ shown: ShownMessage, runs: [LangRun]?) {
        guard mirrorsToWatch, !shown.text.isEmpty else { return }
        let source: MirroredMessage.Source = switch shown.source {
        case .text: .text
        case .macAudio: .macAudio
        case .appStream: .appStream
        }
        let message = MirroredMessage(
            id: shown.id.uuidString, date: shown.date, text: shown.text,
            runs: runs ?? LanguageSplitter.runs(in: shown.text, other: LangRun.phoneDefault), source: source,
            defaultLang: settings.defaultVoice.rawValue, rate: settings.rate)
        watch.send(message)
        if !isActive { watch.notify(message) }
    }

    /// The setting or the watch changed: the first time mirroring is on, ask to notify.
    func mirrorChanged() {
        guard mirrorsToWatch, isActive else { return }
        Task { await watch.requestNotificationsIfNeeded() }
    }

    /// A notification's Speak action, on this phone.
    private func speakMirrored(_ message: MirroredMessage) {
        let incoming = Incoming.text(message.shownText, runs: message.runs)
        last = incoming
        stream = nil
        perform(incoming)
    }

    // MARK: - Claude's voice or the text

    /// What the phone tells the Mac it wants now.
    var voiceWant: VoiceWant { settings.voicePolicy.want(onCellular: onCellular ?? false) }

    func voicePolicyChanged() {
        voicePreference.policy = settings.voicePolicy
    }

    /// Follows the network path (the system's default route), so that "Text on Cellular" asks for
    /// the text while the phone is on cellular data.
    private func watchThePath() {
        pathMonitor.pathUpdateHandler = { [weak self, voicePreference] path in
            let cellular = Self.isCellular(path)
            voicePreference.onCellular = cellular           // at once, for the receiver's next answer
            DispatchQueue.main.async {
                MainActor.assumeIsolated { self?.onCellular = cellular }
            }
        }
        pathMonitor.start(queue: DispatchQueue(label: "com.pragmaphilia.SakamotoVoice.path"))
    }

    /// Cellular data, another path iOS counts as expensive (a Personal Hotspot, say), or Low Data
    /// Mode (the person asked to save data on this network). Through a
    /// VPN such as Tailscale, the path runs over the tunnel's interface, which iOS marks with the
    /// cost and type of the interface the tunnel itself runs over, so a phone on cellular data
    /// still counts as cellular (expected from Network.framework's design; see README.md).
    nonisolated static func isCellular(_ path: NWPath) -> Bool {
        path.isExpensive || path.isConstrained || path.usesInterfaceType(.cellular)
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
            watch.refreshNotificationStatus()
            mirrorChanged()
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
