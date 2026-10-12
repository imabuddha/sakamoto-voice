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
            LabeledContent("Version", value: AppModel.version)
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
