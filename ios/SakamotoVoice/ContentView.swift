import SakamotoVoiceKit
import SwiftUI

/// The main screen, for a phone on a stand (sideways or upright): one slim bar with the status and
/// small Stop, Repeat, and Settings buttons, and all the rest for the messages.
struct ContentView: View {
    @Bindable var model: AppModel
    @State private var showingSettings = false

    var body: some View {
        VStack(spacing: 0) {
            TopBar(model: model, showingSettings: $showingSettings)
            Divider()
            if model.messages.isEmpty {
                WaitingView(code: model.settings.pairingCode)
            } else {
                MessageList(messages: model.messages)
            }
        }
        .sheet(isPresented: $showingSettings) {
            SettingsView(model: model)
        }
    }
}

/// Listening or speaking, and awake, as a small dot and labels; then icon-only buttons.
private struct TopBar: View {
    let model: AppModel
    @Binding var showingSettings: Bool

    var body: some View {
        HStack(spacing: 12) {
            status
            Spacer(minLength: 8)
            BarButton(title: "Stop", systemImage: "stop.fill", help: "Stop speaking") {
                model.stop()
            }
            .tint(.red)
            .disabled(!model.speaker.isBusy)
            BarButton(title: "Repeat", systemImage: "arrow.counterclockwise", help: "Say the last message again") {
                model.repeatLast()
            }
            .disabled(!model.canRepeat)
            BarButton(title: "Settings", systemImage: "gearshape", help: "Settings") {
                showingSettings = true
            }
        }
        .font(.footnote)
        .padding(.leading)
        .padding(.trailing, 8)
        .padding(.vertical, 2)
    }

    private var status: some View {
        HStack(spacing: 12) {
            HStack(spacing: 5) {
                Circle()
                    .fill(color)
                    .frame(width: 8, height: 8)
                Text(text)
                    .lineLimit(1)
            }
            .accessibilityElement(children: .combine)
            if model.keepAlive.isRunning {
                // Miss Sakamoto's avatar (the woman-scientist emoji, drawn by iOS): she's on duty.
                HStack(spacing: 4) {
                    Text("👩🏻‍🔬")
                    Text("Awake")
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Awake")
                .help("Keeps listening in the background and with the screen locked")
            } else if model.keepAlive.isInterrupted {
                Label("Paused", systemImage: "phone")
                    .help("Something else has the audio (a call, say); staying awake resumes when it ends")
            }
        }
        .foregroundStyle(.secondary)
    }

    private var color: Color {
        switch model.serverState {
        case .listening: model.speaker.isStreaming ? .purple : model.speaker.isSpeaking ? .blue : .green
        case .starting: .yellow
        case .failed: .red
        case .stopped: .gray
        }
    }

    private var text: String {
        switch model.serverState {
        case .listening: model.speaker.isStreaming ? "Streaming" : model.speaker.isSpeaking ? "Speaking" : "Listening"
        case .starting: "Starting…"
        case .failed(let error): "Not listening: \(error)"
        case .stopped: "Stopped"
        }
    }
}

/// A small icon-only button: its title is the accessibility label, and the tap target is a bit
/// bigger than the icon.
private struct BarButton: View {
    let title: String
    let systemImage: String
    let help: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .labelStyle(.iconOnly)
                .font(.body)
                .frame(width: 40, height: 32)
                .contentShape(Rectangle())
        }
        .buttonStyle(.borderless)
        .help(help)
    }
}

/// Before the first message: how to pair.
private struct WaitingView: View {
    let code: String

    var body: some View {
        ContentUnavailableView {
            Label("Waiting for Miss Sakamoto", systemImage: "waveform")
        } description: {
            VStack(spacing: 12) {
                Text("Pairing code")
                Text(PairingCode.display(code))
                    .font(.system(size: 44, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.primary)
                    .textSelection(.enabled)
                Text("On the Mac, run:\nsakamoto pair \(code)")
                    .font(.callout.monospaced())
                // Which version is installed, at a glance.
                Text("Sakamoto Voice \(AppModel.version) (\(AppModel.build))")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .padding(.top, 8)
            }
        }
        .frame(maxHeight: .infinity)
    }
}

/// The last few messages, newest first and largest, older ones below in a lighter style. Each new
/// message scrolls the list back to the top, so its beginning is in view.
private struct MessageList: View {
    let messages: [ShownMessage]

    private static let top = "top"

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    Color.clear.frame(height: 0).id(Self.top)
                    ForEach(Array(messages.enumerated()), id: \.element.id) { index, message in
                        MessageRow(message: message, isNewest: index == 0)
                        if index < messages.count - 1 { Divider() }
                    }
                }
                .padding(.horizontal)
                .padding(.vertical, 8)
            }
            .onChange(of: messages.first?.id) {
                withAnimation(.easeOut(duration: 0.25)) {
                    proxy.scrollTo(Self.top, anchor: .top)
                }
            }
        }
    }
}

private struct MessageRow: View {
    let message: ShownMessage
    let isNewest: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(message.date, style: .time)
                switch message.source {
                case .text:
                    EmptyView()
                case .macAudio:
                    Image(systemName: "waveform")
                        .accessibilityLabel("Mac voice")
                case .appStream:
                    Image(systemName: "dot.radiowaves.left.and.right")
                        .accessibilityLabel("Claude app voice, streamed")
                }
            }
            .font(.caption2)
            .foregroundStyle(.tertiary)
            Text(message.text.isEmpty ? "(audio)" : message.text)
                .font(isNewest ? .title2 : .body)
                .foregroundStyle(isNewest ? .primary : .secondary)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
