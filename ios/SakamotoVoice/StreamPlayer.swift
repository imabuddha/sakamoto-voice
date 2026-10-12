import AVFoundation
import SakamotoVoiceKit

/// Plays a live stream (the Claude app's own voice, from the Mac's app-voice-tap) as it arrives:
/// 16-bit PCM goes through a `JitterBuffer` (a quarter second gathered before playing, and again
/// whenever the network falls behind) into an AVAudioPlayerNode. It keeps what it played (up to
/// ten minutes), so Repeat can play it again.
@MainActor
final class StreamPlayer {
    private(set) var isPlaying = false
    /// Called when `isPlaying` changes.
    var onChange: (() -> Void)?
    /// Called when a stream has played to its end, with all its audio (16-bit PCM).
    var onFinished: ((Data, StreamInfo) -> Void)?

    static let prebuffer = 0.25
    static let maxRecordingSeconds = 600

    private var engine: AVAudioEngine?
    private var node: AVAudioPlayerNode?
    private var format: AVAudioFormat?
    private var jitter: JitterBuffer?
    private var info: StreamInfo?
    private var recording = Data()
    /// Bumped by every start and stop, so callbacks from an earlier stream are ignored.
    private var generation = 0
    private var configurationObserver: NSObjectProtocol?

    var streamID: Int? { info?.id }

    /// Gets ready for a stream; false when the audio engine won't start.
    @discardableResult
    func start(_ info: StreamInfo) -> Bool {
        stop()
        guard let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Double(info.sampleRate),
                                         channels: AVAudioChannelCount(info.channels), interleaved: false)
        else { return false }
        let engine = AVAudioEngine()
        let node = AVAudioPlayerNode()
        engine.attach(node)
        engine.connect(node, to: engine.mainMixerNode, format: format)
        do {
            try AVAudioSession.sharedInstance().setActive(true)
            try engine.start()
        } catch {
            return false
        }
        node.play()
        self.engine = engine
        self.node = node
        self.format = format
        self.info = info
        jitter = JitterBuffer(sampleRate: info.sampleRate, channels: info.channels, prebuffer: Self.prebuffer)
        // A route change (headphones, a call ending) stops the engine; start it again.
        configurationObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.restartEngine() }
        }
        setPlaying(true)
        return true
    }

    /// The stream's next audio (whole frames).
    func feed(_ data: Data) {
        guard jitter != nil else { return }
        if recording.count < Self.maxRecordingSeconds * (info?.sampleRate ?? 0) * (info?.bytesPerFrame ?? 0) {
            recording.append(data)
        }
        schedule(jitter!.append(PCM16.samples(data)))
    }

    /// The sender closed the stream: play out what's left.
    func end() {
        guard jitter != nil, let info else { return }
        schedule(jitter!.end())
        finishIfDone()
        // Should a played-back callback never come (the engine was reset by a route change, say),
        // finish anyway a little after the audio would have ended.
        let generation = self.generation
        let left = Double(jitter?.queuedFrames ?? 0) / Double(info.sampleRate)
        DispatchQueue.main.asyncAfter(deadline: .now() + left + 2) { [weak self] in
            MainActor.assumeIsolated {
                guard let self, generation == self.generation, self.jitter != nil else { return }
                self.finish()
            }
        }
    }

    func stop() {
        generation += 1
        if let configurationObserver { NotificationCenter.default.removeObserver(configurationObserver) }
        configurationObserver = nil
        node?.stop()
        engine?.stop()
        node = nil
        engine = nil
        format = nil
        jitter = nil
        info = nil
        recording = Data()
        setPlaying(false)
    }

    private func setPlaying(_ playing: Bool) {
        guard playing != isPlaying else { return }
        isPlaying = playing
        onChange?()
    }

    private func schedule(_ chunks: [[Int16]]) {
        guard let node, let format else { return }
        let channels = Int(format.channelCount)
        let generation = self.generation
        for chunk in chunks {
            let frames = chunk.count / channels
            guard frames > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)),
                  let destination = buffer.floatChannelData
            else { continue }
            buffer.frameLength = AVAudioFrameCount(frames)
            for channel in 0..<channels {
                let out = destination[channel]
                for frame in 0..<frames {
                    out[frame] = Float(chunk[frame * channels + channel]) / 32_768
                }
            }
            node.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
                DispatchQueue.main.async {
                    MainActor.assumeIsolated { self?.played(frames: frames, generation: generation) }
                }
            }
        }
    }

    private func played(frames: Int, generation: Int) {
        guard generation == self.generation, jitter != nil else { return }
        schedule(jitter!.played(frames: frames))
        finishIfDone()
    }

    private func finishIfDone() {
        if jitter?.state == .finished { finish() }
    }

    private func finish() {
        guard let info else { return }
        let recording = self.recording
        stop()
        if !recording.isEmpty { onFinished?(recording, info) }
    }

    private func restartEngine() {
        guard let engine, let node, !engine.isRunning else { return }
        try? engine.start()
        node.play()
    }
}
