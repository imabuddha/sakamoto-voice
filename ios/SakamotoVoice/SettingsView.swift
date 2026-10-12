import AVFoundation
import SakamotoVoiceKit
import SwiftUI

struct SettingsView: View {
    @Bindable var model: AppModel
    @Environment(\.dismiss) private var dismiss

    private var settings: Settings { model.settings }

    var body: some View {
        @Bindable var settings = model.settings
        NavigationStack {
            Form {
                pairing
                voices(settings)
                claudesVoice(settings)
                appleWatch(settings)
                stayingAwake(settings)
                Section {
                    Toggle("Keep Screen On", isOn: $settings.keepScreenOn)
                } footer: {
                    Text("While the app is open, the screen doesn't dim or lock: for a phone on a stand.")
                }
                about
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .onChange(of: settings.keepAlivePolicy) { model.evaluateKeepAlive() }
            .onChange(of: settings.keepScreenOn) { model.evaluateKeepAlive() }
            .onChange(of: settings.voicePolicy) { model.voicePolicyChanged() }
            .onChange(of: settings.mirrorToWatch) { model.mirrorChanged() }
        }
    }

    // MARK: - Sections

    private var pairing: some View {
        Section {
            HStack {
                Text(PairingCode.display(settings.pairingCode))
                    .font(.system(.largeTitle, design: .monospaced).weight(.semibold))
                    .textSelection(.enabled)
                Spacer()
                Button("New Code") { model.newPairingCode() }
            }
            if let ping = model.lastPing {
                Label {
                    Text("The Mac checked in at \(ping.formatted(date: .omitted, time: .shortened)).")
                } icon: {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                }
            }
        } header: {
            Text("Pairing Code")
        } footer: {
            Text("On the Mac, run sakamoto pair \(settings.pairingCode). Messages without this code are refused; a new code unpairs the Mac.")
        }
    }

    private func voices(_ settings: Settings) -> some View {
        @Bindable var settings = settings
        return Section {
            VStack(alignment: .leading) {
                Text("Default Voice for Other Text")
                Picker("Default Voice for Other Text", selection: $settings.defaultVoice) {
                    Text("English").tag(DefaultVoice.english)
                    Text("Japanese").tag(DefaultVoice.japanese)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
            }
            Picker("English", selection: $settings.englishVoiceID) {
                Text("Automatic (\(Voices.defaultEnglish.map(Voices.label) ?? "System"))").tag("")
                ForEach(Voices.installed("en"), id: \.identifier) { voice in
                    Text(Voices.label(voice)).tag(voice.identifier)
                }
            }
            Picker("Japanese", selection: $settings.japaneseVoiceID) {
                Text("Automatic (\(Voices.defaultJapanese.map(Voices.label) ?? "System"))").tag("")
                ForEach(Voices.installed("ja"), id: \.identifier) { voice in
                    Text(Voices.label(voice)).tag(voice.identifier)
                }
            }
            VStack(alignment: .leading) {
                Text("Rate")
                HStack {
                    Image(systemName: "tortoise")
                    Slider(value: $settings.rate,
                           in: AVSpeechUtteranceMinimumSpeechRate...AVSpeechUtteranceMaximumSpeechRate)
                    Image(systemName: "hare")
                }
                .foregroundStyle(.secondary)
            }
            Button("Reset Rate") { settings.rate = AVSpeechUtteranceDefaultSpeechRate }
                .disabled(settings.rate == AVSpeechUtteranceDefaultSpeechRate)
            Button("Preview", systemImage: "play.fill") { model.preview() }
        } header: {
            Text("Voices")
        } footer: {
            Text("""
                Japanese script is always read in the Japanese voice; the default voice reads the rest, \
                except where the Mac's 〔en〕 or 〔ja〕 markers choose a voice. \
                Siri voices aren't available to apps, so they aren't listed. For better voices, download \
                Enhanced or Premium ones in Settings → Accessibility → Spoken Content → Voices. Audio the \
                Mac sends (phone_mode "audio") is in the Mac's own voice instead.
                """)
        }
    }

    private func claudesVoice(_ settings: Settings) -> some View {
        @Bindable var settings = settings
        return Section {
            Picker("Claude's Voice", selection: $settings.voicePolicy) {
                Text("Claude's Voice").tag(VoicePolicy.stream)
                Text("Text on Cellular").tag(VoicePolicy.textOnCellular)
                Text("Text Only").tag(VoicePolicy.textOnly)
            }
            .pickerStyle(.inline)
            .labelsHidden()
        } header: {
            Text("Claude's Voice")
        } footer: {
            Text(voiceFooter)
        }
    }

    private var voiceFooter: String {
        var text = """
            When the Mac streams the Claude app's own voice (output app-phone or app-both), it uses \
            about 170 MB of data an hour. With Text on Cellular, the voice is streamed on Wi-Fi, and \
            on cellular data (or a Personal Hotspot) the Mac sends only the text, which the phone \
            reads in its own voices. The Mac learns the choice from the phone's answers, so a change \
            can take one more response to reach it.
            """
        if let onCellular = model.onCellular {
            let network = onCellular ? "On cellular data" : "On Wi-Fi"
            text += model.voiceWant == .stream ? " \(network) now: the voice is streamed."
                : " \(network) now: the Mac sends the text."
        }
        return text
    }

    /// Only with a paired watch; the switch only once the watch app is installed.
    @ViewBuilder
    private func appleWatch(_ settings: Settings) -> some View {
        @Bindable var settings = settings
        if model.watch.isPaired {
            Section {
                if model.watch.isWatchAppInstalled {
                    Toggle("Mirror to Apple Watch", isOn: $settings.mirrorToWatch)
                } else {
                    Text("Install Sakamoto Voice on the watch: in the Watch app on this iPhone, under Available Apps.")
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("Apple Watch")
            } footer: {
                Text(watchFooter)
            }
        }
    }

    private var watchFooter: String {
        guard model.watch.isWatchAppInstalled else {
            return "Then each message can also appear on the watch, which can read it aloud."
        }
        var text = """
            Each message also goes to the watch app, which lists it and can read it aloud. While this \
            app isn't on screen, a notification shows it on the watch too, with Speak. iOS sends a \
            notification to the watch only while the phone is locked or its screen is off and the \
            watch is on your wrist and unlocked.
            """
        if settings.mirrorToWatch && model.watch.notificationsAllowed == false {
            text += " Notifications are off for Sakamoto Voice: turn them on in Settings → Notifications."
        }
        return text
    }

    private func stayingAwake(_ settings: Settings) -> some View {
        @Bindable var settings = settings
        return Section {
            Toggle("Stay Awake in the Background", isOn: $settings.stayAwake)
            if settings.stayAwake {
                Toggle("Only Between These Times", isOn: $settings.useSchedule)
                if settings.useSchedule {
                    DatePicker("From", selection: minuteBinding($settings.scheduleStart),
                               displayedComponents: .hourAndMinute)
                    DatePicker("Until", selection: minuteBinding($settings.scheduleEnd),
                               displayedComponents: .hourAndMinute)
                }
            }
        } header: {
            Text("Staying Awake")
        } footer: {
            Text(awakeFooter)
        }
    }

    private var awakeFooter: String {
        var text = """
            Plays a near-silent sound so iOS keeps the app running with the screen locked or another \
            app in front. It uses more battery; keep the phone on its charger.
            """
        if settings.stayAwake && settings.useSchedule {
            text += " Outside these times the app speaks only while it's open; after the end time, open it again to wake it."
        } else if !settings.stayAwake {
            text += " While this is off, the app speaks only while it's open."
        }
        return text
    }

    private var about: some View {
        Section("About") {
            LabeledContent("Version", value: "\(AppModel.version) (\(AppModel.build))")
            LabeledContent("Listening") {
                switch model.serverState {
                case .listening(let port): Text("Port \(String(port))")
                case .starting: Text("Starting…")
                case .failed(let error): Text(error).foregroundStyle(.red)
                case .stopped: Text("Stopped")
                }
            }
            LabeledContent("In the Background", value: model.keepAlive.isRunning ? "Awake" : "Asleep")
        }
    }

    /// A minutes-after-midnight setting as a time today, for DatePicker.
    private func minuteBinding(_ minutes: Binding<Int>) -> Binding<Date> {
        Binding {
            let m = minutes.wrappedValue
            return Calendar.current.date(bySettingHour: m / 60, minute: m % 60, second: 0, of: Date()) ?? Date()
        } set: { date in
            minutes.wrappedValue = DailySchedule.minuteOfDay(date, calendar: .current)
        }
    }
}
