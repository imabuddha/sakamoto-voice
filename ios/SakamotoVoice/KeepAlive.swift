import AVFoundation
import Observation
import SakamotoVoiceKit

/// Keeps the app running in the background: with the `audio` background mode, iOS doesn't suspend
/// an app that is playing sound, so while this is on it loops a second of near silence. That keeps
/// the listener alive with the screen locked or another app in front, at some cost in battery.
///
/// The session mixes with other audio, so music and podcasts play on, and an interruption (a call,
/// an alarm, Siri) is followed by a restart when it ends.
@MainActor @Observable
final class KeepAlive {
    private(set) var isRunning = false
    /// Something else holds the audio (a call, say); we restart when it ends.
    private(set) var isInterrupted = false

    @ObservationIgnored private var player: AVAudioPlayer?
    @ObservationIgnored private var wanted = false
    @ObservationIgnored private var observers: [NSObjectProtocol] = []
    @ObservationIgnored private var retryTask: Task<Void, Never>?

    init() {
        let center = NotificationCenter.default
        let session = AVAudioSession.sharedInstance()
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: session,
                                            queue: .main) { [weak self] note in
            let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            let began = raw.flatMap(AVAudioSession.InterruptionType.init(rawValue:)) == .began
            MainActor.assumeIsolated { self?.interrupted(began: began) }
        })
        observers.append(center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification,
                                            object: session, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.mediaServicesReset() }
        })
    }

    /// The audio session every part of the app uses: playback (speech is heard with the silent
    /// switch on, and keeps going in the background), mixed with other apps' audio.
    static func configureSession() {
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio, options: [.mixWithOthers])
    }

    func setWanted(_ wanted: Bool) {
        self.wanted = wanted
        wanted ? start() : stop()
    }

    private func start() {
        guard !isRunning || !(player?.isPlaying ?? false) else { return }
        Self.configureSession()
        do {
            try AVAudioSession.sharedInstance().setActive(true)
            if player == nil {
                let player = try AVAudioPlayer(data: SilentAudio.wav(), fileTypeHint: AVFileType.wav.rawValue)
                player.numberOfLoops = -1
                player.volume = 1
                player.prepareToPlay()
                self.player = player
            }
            isRunning = player?.play() ?? false
            isInterrupted = false
        } catch {
            isRunning = false
        }
        if !isRunning { retrySoon() }
    }

    private func stop() {
        retryTask?.cancel()
        retryTask = nil
        player?.stop()
        player = nil
        isRunning = false
        isInterrupted = false
    }

    private func interrupted(began: Bool) {
        guard wanted else { return }
        if began {
            isInterrupted = true
            isRunning = false
        } else {
            // Restart whether or not the system suggests resuming: staying awake is the point.
            player = nil
            start()
        }
    }

    private func mediaServicesReset() {
        player = nil
        isRunning = false
        if wanted { start() }
    }

    /// The session can refuse to activate while a call is still ending; try again every few
    /// seconds while staying awake is wanted.
    private func retrySoon() {
        guard wanted, retryTask == nil else { return }
        retryTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            guard let self, !Task.isCancelled else { return }
            self.retryTask = nil
            if self.wanted, !self.isRunning {
                self.player = nil
                self.start()
            }
        }
    }
}
