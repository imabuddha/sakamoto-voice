import Foundation
import Observation
import SakamotoVoiceKit
import SwiftUI
import UserNotifications
import WatchConnectivity

/// The watch app's state: the messages the phone mirrored (newest first, kept across launches),
/// the one selected for Speak, Auto-speak, and the WatchConnectivity session and notification
/// delegate that bring messages in.
///
/// Messages arrive three ways, and the same one may come twice (its id tells): a live message
/// while this app is reachable (on screen), a queued transfer (delivered at once while the app is
/// frontmost, else whenever watchOS wakes it), and the notification the phone posts while its own
/// app isn't on screen. Auto-speak reads a fresh one aloud while the app is frontmost; nothing can
/// read aloud with the app in the background (watchOS allows background audio only for long-form
/// audio on Bluetooth headphones), so then the notification is the way, with its Speak action.
@MainActor @Observable
final class WatchModel: NSObject {
    static let shared = WatchModel()
    static let historyLength = 10

    private(set) var messages: [MirroredMessage] = []
    /// The message Speak reads; nil for the newest.
    var selectedID: String?
    /// Read a new message aloud as it arrives, while the app is frontmost.
    var autoSpeak: Bool { didSet { defaults.set(autoSpeak, forKey: Key.autoSpeak) } }
    /// On screen, or frontmost with the wrist down (watchOS keeps the app in front for the time
    /// set in Settings → General → Return to Clock, two minutes by default).
    private(set) var isFrontmost = true
    /// Whether the phone is in reach for live messages.
    private(set) var isPhoneReachable = false

    let speaker = WatchSpeaker()

    @ObservationIgnored private let defaults = UserDefaults.standard
    @ObservationIgnored private var started = false

    enum Key {
        static let autoSpeak = "autoSpeak"
        static let messages = "messages"
    }

    override init() {
        defaults.register(defaults: [Key.autoSpeak: true])
        autoSpeak = defaults.bool(forKey: Key.autoSpeak)
        if let data = defaults.data(forKey: Key.messages),
           let saved = try? JSONDecoder().decode([MirroredMessage].self, from: data) {
            messages = saved
        }
        super.init()
    }

    /// Becomes the notification delegate and activates WatchConnectivity (once).
    func start() {
        guard !started else { return }
        started = true
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.setNotificationCategories([Self.category])
        if WCSession.isSupported() {
            WCSession.default.delegate = self
            WCSession.default.activate()
        }
    }

    /// The same category as the phone's, so its Speak action shows with the notification here.
    static var category: UNNotificationCategory {
        UNNotificationCategory(
            identifier: MirroredMessage.notificationCategory,
            actions: [UNNotificationAction(identifier: MirroredMessage.speakAction, title: "Speak",
                                           options: [.foreground])],
            intentIdentifiers: [], options: [])
    }

    var selected: MirroredMessage? {
        messages.first { $0.id == selectedID } ?? messages.first
    }

    // MARK: - Messages

    /// A message from the phone. `speak` reads it whatever Auto-speak says (the Speak action).
    func receive(_ message: MirroredMessage, speak: Bool = false) {
        let isNew = !messages.contains { $0.id == message.id }
        messages = MirroredMessage.inserting(message, into: messages, limit: Self.historyLength)
        save()
        if speak {
            selectedID = message.id
            speaker.speak(message)
        } else if isNew, autoSpeak, isFrontmost, message.isFresh(), messages.first?.id == message.id {
            selectedID = nil
            speaker.speak(message)
        }
    }

    func speakSelected() {
        guard let selected else { return }
        speaker.speak(selected)
    }

    func clear() {
        speaker.stop()
        messages = []
        selectedID = nil
        save()
    }

    private func save() {
        if let data = try? JSONEncoder().encode(messages) {
            defaults.set(data, forKey: Key.messages)
        }
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        isFrontmost = phase != .background
        if phase == .background { speaker.stop() }
    }

    /// For the background task watchOS runs when transfers are waiting: activate, and give the
    /// session a few seconds to hand them over.
    func receivePendingTransfers() async {
        start()
        let session = WCSession.default
        let deadline = Date().addingTimeInterval(5)
        while (session.activationState != .activated || session.hasContentPending), Date() < deadline {
            try? await Task.sleep(for: .milliseconds(200))
        }
    }

    private func reachabilityChanged(_ reachable: Bool) {
        isPhoneReachable = reachable
    }
}

extension WatchModel: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState,
                             error: Error?) {
        let reachable = session.isReachable
        Task { @MainActor in self.reachabilityChanged(reachable) }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        let reachable = session.isReachable
        Task { @MainActor in self.reachabilityChanged(reachable) }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        guard let mirrored = MirroredMessage(dictionary: message) else { return }
        Task { @MainActor in self.receive(mirrored) }
    }

    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        guard let mirrored = MirroredMessage(dictionary: userInfo) else { return }
        Task { @MainActor in self.receive(mirrored) }
    }
}

extension WatchModel: UNUserNotificationCenterDelegate {
    /// The app is on screen or frontmost: the message joins the list (and Auto-speak reads it),
    /// with no banner over it.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        let message = Self.message(in: notification)
        Task { @MainActor in
            if let message { self.receive(message) }
        }
        completionHandler(message == nil ? [.banner, .sound] : [.sound])
    }

    /// Speak (or a tap on the notification) opened the app.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let message = Self.message(in: response.notification)
        let speak = response.actionIdentifier == MirroredMessage.speakAction
        Task { @MainActor in
            if let message {
                self.receive(message, speak: speak)
                self.selectedID = message.id
            }
        }
        completionHandler()
    }

    /// The message a notification carries; from its body when it carries none.
    nonisolated static func message(in notification: UNNotification) -> MirroredMessage? {
        let content = notification.request.content
        guard content.categoryIdentifier == MirroredMessage.notificationCategory else { return nil }
        if let userInfo = content.userInfo as? [String: Any], let message = MirroredMessage(dictionary: userInfo) {
            return message
        }
        return content.body.isEmpty ? nil
            : MirroredMessage(id: notification.request.identifier, date: notification.date, text: content.body)
    }
}
