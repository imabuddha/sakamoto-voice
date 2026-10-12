import AVFoundation
import SakamotoVoiceKit
import SwiftUI

/// The latest messages, newest first: a big Speak button for the selected one (the newest unless
/// another is tapped), then the list, then Auto-speak.
struct ContentView: View {
    @Bindable var model: WatchModel

    var body: some View {
        NavigationStack {
            List {
                if model.messages.isEmpty {
                    EmptyState()
                } else {
                    Section {
                        SpeakButton(model: model)
                    }
                    Section {
                        ForEach(model.messages) { message in
                            MessageRow(message: message, isSelected: message.id == model.selected?.id,
                                       isNewest: message.id == model.messages.first?.id)
                                .contentShape(Rectangle())
                                .onTapGesture { model.selectedID = message.id }
                                .accessibilityAddTraits(message.id == model.selected?.id ? .isSelected : [])
                                .accessibilityAction(named: "Speak") {
                                    model.selectedID = message.id
                                    model.speakSelected()
                                }
                        }
                    }
                }
                Section {
                    Toggle("Auto-speak while open", isOn: $model.autoSpeak)
                } footer: {
                    Text("Reads each new message aloud as it arrives while this app is in front.")
                }
                VoicesSection()
                if !model.messages.isEmpty {
                    Section {
                        Button("Clear", role: .destructive) { model.clear() }
                    }
                }
            }
            .navigationTitle("Sakamoto")
        }
    }
}

/// Speak, or Stop while speaking.
private struct SpeakButton: View {
    let model: WatchModel

    var body: some View {
        Button {
            model.speaker.isSpeaking ? model.speaker.stop() : model.speakSelected()
        } label: {
            Label(model.speaker.isSpeaking ? "Stop" : "Speak",
                  systemImage: model.speaker.isSpeaking ? "stop.fill" : "speaker.wave.2.fill")
                .font(.title3.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .tint(model.speaker.isSpeaking ? .red : .accentColor)
        .buttonStyle(.borderedProminent)
        .listRowBackground(Color.clear)
        .listRowInsets(EdgeInsets())
    }
}

private struct MessageRow: View {
    let message: MirroredMessage
    let isSelected: Bool
    let isNewest: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                // Miss Sakamoto's avatar, the woman-scientist emoji.
                Text("👩🏻‍🔬")
                    .accessibilityHidden(true)
                Text(message.date, style: .time)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.caption2)
                        .foregroundStyle(Color.accentColor)
                        .accessibilityHidden(true)
                }
            }
            Text(message.shownText)
                .font(isNewest ? .body : .footnote)
                .foregroundStyle(isNewest ? .primary : .secondary)
                .lineLimit(isSelected ? nil : 4)
        }
        .padding(.vertical, 2)
    }
}

private struct EmptyState: View {
    var body: some View {
        VStack(spacing: 6) {
            Text("👩🏻‍🔬")
                .font(.largeTitle)
                .accessibilityHidden(true)
            Text("No messages yet")
                .font(.headline)
            Text("Messages from Sakamoto Voice on your iPhone appear here.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .listRowBackground(Color.clear)
    }
}

/// The voices the watch reads with: any installed English and Japanese voice (premium and enhanced
/// ones too, such as those downloaded under Accessibility › Live Speech). Until one is chosen, the
/// highest-quality voice installed, listed first.
private struct VoicesSection: View {
    @AppStorage(WatchSpeaker.englishChoiceKey) private var english = ""
    @AppStorage(WatchSpeaker.japaneseChoiceKey) private var japanese = ""

    var body: some View {
        Section {
            picker("English", selection: $english, voices: WatchSpeaker.voices("en"))
            picker("Japanese", selection: $japanese, voices: WatchSpeaker.voices("ja"))
        } header: {
            Text("Voices")
        } footer: {
            Text("Premium and Enhanced voices can be added under Settings › Accessibility › Live Speech.")
        }
    }

    private func picker(_ title: String, selection: Binding<String>, voices: [AVSpeechSynthesisVoice]) -> some View {
        Picker(title, selection: Binding(get: { selection.wrappedValue.isEmpty ? (voices.first?.identifier ?? "") : selection.wrappedValue },
                                         set: { selection.wrappedValue = $0 })) {
            ForEach(voices, id: \.identifier) { voice in
                Text(label(voice)).tag(voice.identifier)
            }
        }
    }

    private func label(_ voice: AVSpeechSynthesisVoice) -> String {
        switch voice.quality {
        case .premium: "\(voice.name) (Premium)"
        case .enhanced: "\(voice.name) (Enhanced)"
        default: voice.name
        }
    }
}
