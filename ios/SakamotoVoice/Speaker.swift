import AVFoundation
import Observation
import SakamotoVoiceKit

/// Speaks text (English, Japanese, and default runs, each in its voice), plays the Mac's
/// rendered audio, and plays live streams (the Claude app's own voice). Anything new interrupts
/// what's playing.
@MainActor @Observable
final class Speaker: NSObject {
    private(set) var isSpeaking = false
    private(set) var isStreaming = false

    /// Speaking, playing, or streaming.
    var isBusy: Bool { isSpeaking || isStreaming }

    @ObservationIgnored let stream = StreamPlayer()
    @ObservationIgnored private let synthesizer = AVSpeechSynthesizer()
    @ObservationIgnored private var player: AVAudioPlayer?

    override init() {
        super.init()
        synthesizer.delegate = self
        // Speech plays through the app's audio session (category playback: it ignores the
        // silent switch and keeps going in the background).
        synthesizer.usesApplicationAudioSession = true
        stream.onChange = { [weak self] in
            guard let self else { return }
            self.isStreaming = self.stream.isPlaying
        }
    }

    /// Gets ready to play a live stream, silencing anything else.
    func startStream(_ info: StreamInfo) {
        stop()
        stream.start(info)
    }

    /// Speaks the runs; "default" runs in the Japanese voice when `defaultIsJapanese`, else the English one.
    func speak(_ runs: [LangRun], englishVoice: AVSpeechSynthesisVoice?, japaneseVoice: AVSpeechSynthesisVoice?,
               defaultIsJapanese: Bool, rate: Float) {
        stop()
        for run in runs {
            let utterance = AVSpeechUtterance(string: run.text)
            utterance.voice = run.isJapanese(byDefault: defaultIsJapanese) ? japaneseVoice : englishVoice
            utterance.rate = min(max(rate, AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)
            synthesizer.speak(utterance)
        }
        isSpeaking = !runs.isEmpty
    }

    /// Plays audio the Mac rendered; false if it can't be decoded.
    @discardableResult
    func play(_ data: Data, format: String) -> Bool {
        stop()
        let hint: String? = switch format {
        case "m4a", "aac", "mp4": AVFileType.m4a.rawValue
        case "wav", "wave": AVFileType.wav.rawValue
        case "aiff", "aif": AVFileType.aiff.rawValue
        case "caf": AVFileType.caf.rawValue
        case "mp3": AVFileType.mp3.rawValue
        default: nil
        }
        guard let player = try? AVAudioPlayer(data: data, fileTypeHint: hint) else { return false }
        player.delegate = self
        self.player = player
        isSpeaking = player.play()
        return isSpeaking
    }

    func stop() {
        if synthesizer.isSpeaking || synthesizer.isPaused {
            synthesizer.stopSpeaking(at: .immediate)
        }
        player?.stop()
        player = nil
        isSpeaking = false
        stream.stop()
    }

    private func refresh() {
        isSpeaking = synthesizer.isSpeaking || (player?.isPlaying ?? false)
    }
}

extension Speaker: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.refresh() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.refresh() }
    }
}

extension Speaker: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.refresh() }
    }
}
