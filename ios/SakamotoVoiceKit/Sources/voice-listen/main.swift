// voice-listen: a stand-in phone on the Mac. It advertises _sakamotovoice._tcp like the iPhone
// app and prints what arrives, so the Mac side (speak.py pair, phone-test, output phone,
// app-voice-tap) can be tried without a phone.
//
//     swift run voice-listen [code] [--save DIR] [--text]
//
// The code is 6 digits (a random one if none is given). With --save, each stream is also written
// to DIR as a WAV file, to hear what the phone would have played. With --text, it answers as a
// phone that wants the text, not the Claude app's voice (as on cellular data): it declines streams.

import Foundation
import SakamotoVoiceKit

setvbuf(stdout, nil, _IOLBF, 0)      // a line at a time, also into a file or a pipe
var arguments = Array(CommandLine.arguments.dropFirst())
var saveDirectory: URL?
if let i = arguments.firstIndex(of: "--save"), i + 1 < arguments.count {
    saveDirectory = URL(fileURLWithPath: arguments[i + 1], isDirectory: true)
    arguments.removeSubrange(i...(i + 1))
}
let wantsText = arguments.contains("--text")
arguments.removeAll { $0 == "--text" }
let code = arguments.first.map(PairingCode.normalize) ?? PairingCode.generate()
guard PairingCode.isValid(code) else {
    FileHandle.standardError.write(Data("voice-listen: the code must be 6 digits\n".utf8))
    exit(2)
}

@Sendable func stamp() -> String {
    let formatter = DateFormatter()
    formatter.dateFormat = "HH:mm:ss"
    return formatter.string(from: Date())
}

/// The stream arriving now (touched only on the server's queue).
final class StreamLog: @unchecked Sendable {
    var info: StreamInfo?
    var audio = Data()
    var started: Date?
}
let current = StreamLog()
let save = saveDirectory

print("voice-listen: pairing code \(PairingCode.display(code)) (on the Mac: speak.py pair \(code))"
      + (wantsText ? "; wants the text, declining streams" : ""))
let server = VoiceServer(token: code, version: "voice-listen", serviceName: "voice-listen on \(ProcessInfo.processInfo.hostName)",
                         voice: { wantsText ? .text : .stream }) { incoming in
    switch incoming {
    case .text(let text, let runs):
        print("\(stamp()) text, \(runs.count) runs:")
        for run in runs { print("  [\(run.lang)] \(run.text)") }
        if runs.isEmpty { print("  \(text)") }
    case .audio(let data, let format, let text):
        print("\(stamp()) audio: \(data.count) bytes of \(format); text: \(text)")
    case .ping:
        print("\(stamp()) ping")
    case .stop:
        print("\(stamp()) stop")
    case .streamStart(let info):
        current.info = info
        current.audio = Data()
        current.started = nil
        print("\(stamp()) stream \(info.id): \(info.sampleRate) Hz, \(info.channels) channel(s); text: \(info.text)")
    case .streamAudio(let id, let data):
        guard id == current.info?.id else { return }
        if current.started == nil {
            current.started = Date()
            print("\(stamp()) stream \(id): audio began")
        }
        current.audio.append(data)
    case .streamEnd(let id):
        guard let info = current.info, info.id == id else { return }
        let seconds = Double(current.audio.count) / Double(info.bytesPerFrame * info.sampleRate)
        print("\(stamp()) stream \(id) ended: \(current.audio.count) bytes, \(String(format: "%.1f", seconds)) s of audio")
        if let save, !current.audio.isEmpty {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyyMMdd-HHmmss"
            let url = save.appendingPathComponent("stream-\(formatter.string(from: Date()))-\(id).wav")
            do {
                try FileManager.default.createDirectory(at: save, withIntermediateDirectories: true)
                try WAV.pcm16(current.audio, sampleRate: info.sampleRate, channels: info.channels).write(to: url)
                print("  saved \(url.path)")
            } catch {
                print("  not saved: \(error)")
            }
        }
        current.info = nil
    }
}
server.onStateChange { state in print("\(stamp()) \(state)") }
server.start()
dispatchMain()
