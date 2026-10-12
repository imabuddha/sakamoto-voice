import Foundation
import Observation
import SakamotoVoiceKit
import UserNotifications
import WatchConnectivity

/// Mirrors messages to the Apple Watch app: each one goes over WatchConnectivity (a live message
/// while the watch app is reachable, else a queued user-info transfer, which watchOS delivers when
/// it can), and, while this app isn't on screen, in a local notification, which iOS forwards to
/// the watch when the phone is locked or its screen is off and the watch is on the wrist and
/// unlocked. The notification carries the message, so its Speak action works on the watch even
/// before the transfer arrives (and here, should iOS show it on the phone).
@MainActor @Observable
final class WatchLink: NSObject {
    /// A watch is paired with this phone.
    private(set) var isPaired = false
    /// The watch app is installed on it.
    private(set) var isWatchAppInstalled = false
    /// Notifications are allowed (nil until asked, or while unknown).
    private(set) var notificationsAllowed: Bool?

    /// The Speak action of a notification shown on this phone.
    @ObservationIgnored var onSpeak: ((MirroredMessage) -> Void)?
    /// The pairing or the watch app's installation changed.
    @ObservationIgnored var onStateChange: (() -> Void)?

    @ObservationIgnored private let session: WCSession? = WCSession.isSupported() ? .default : nil

    override init() {
        super.init()
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.setNotificationCategories([Self.category])
        session?.delegate = self
        session?.activate()
        refreshNotificationStatus()
    }

    /// The category the phone posts with: one Speak action, which opens the app that shows it (the
    /// watch app, on the watch) and reads the message.
    static var category: UNNotificationCategory {
        UNNotificationCategory(
            identifier: MirroredMessage.notificationCategory,
            actions: [UNNotificationAction(identifier: MirroredMessage.speakAction, title: "Speak",
                                           options: [.foreground])],
            intentIdentifiers: [], options: [])
    }

    // MARK: - Sending

    /// Sends the message to the watch app, live when it's reachable, else queued.
    func send(_ message: MirroredMessage) {
        guard let session, session.activationState == .activated, session.isWatchAppInstalled else { return }
        let dictionary = message.dictionary
        if session.isReachable {
            // Should the live message fail (the watch app went to the background), queue it; the
            // watch ignores a message it already has.
            session.sendMessage(dictionary, replyHandler: nil) { _ in
                Self.queue(message)
            }
        } else {
            session.transferUserInfo(dictionary)
        }
    }

    nonisolated private static func queue(_ message: MirroredMessage) {
        let session = WCSession.default
        guard session.activationState == .activated else { return }
        session.transferUserInfo(message.dictionary)
    }

    static let latestNotificationID = "latest"

    /// Posts the message as a notification (shown at once), for the watch. Only the latest stays:
    /// each one replaces the one before (one identifier), so they don't stack up (John, 2026-10-13).
    func notify(_ message: MirroredMessage) {
        guard notificationsAllowed != false else { return }
        let content = UNMutableNotificationContent()
        content.title = MirroredMessage.notificationTitle
        content.body = message.notificationBody()
        content.sound = .default
        content.categoryIdentifier = MirroredMessage.notificationCategory
        content.threadIdentifier = "messages"
        content.userInfo = message.dictionary
        let center = UNUserNotificationCenter.current()
        center.removeAllDeliveredNotifications()
        let request = UNNotificationRequest(identifier: Self.latestNotificationID, content: content, trigger: nil)
        center.add(request) { _ in }
    }

    // MARK: - Permission

    /// Asks for permission to notify, if it hasn't been asked yet (call while the app is on screen).
    func requestNotificationsIfNeeded() async {
        let center = UNUserNotificationCenter.current()
        let status = await center.notificationSettings().authorizationStatus
        if status == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound])
        }
        refreshNotificationStatus()
    }

    func refreshNotificationStatus() {
        Task {
            let status = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
            switch status {
            case .authorized, .provisional, .ephemeral: notificationsAllowed = true
            case .denied: notificationsAllowed = false
            default: notificationsAllowed = nil
            }
        }
    }

    private func update(paired: Bool, installed: Bool) {
        let changed = paired != isPaired || installed != isWatchAppInstalled
        isPaired = paired
        isWatchAppInstalled = installed
        if changed { onStateChange?() }
    }
}

extension WatchLink: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith activationState: WCSessionActivationState,
                             error: Error?) {
        let paired = activationState == .activated && session.isPaired
        let installed = paired && session.isWatchAppInstalled
        Task { @MainActor in self.update(paired: paired, installed: installed) }
    }

    nonisolated func sessionWatchStateDidChange(_ session: WCSession) {
        let paired = session.isPaired
        let installed = paired && session.isWatchAppInstalled
        Task { @MainActor in self.update(paired: paired, installed: installed) }
    }

    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}

    /// Another watch was chosen: start again with it.
    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }
}

extension WatchLink: UNUserNotificationCenterDelegate {
    /// While the app is on screen it shows (and reads) the message itself.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let userInfo = response.notification.request.content.userInfo as? [String: Any] ?? [:]
        let message = MirroredMessage(dictionary: userInfo)
        if response.actionIdentifier == MirroredMessage.speakAction, let message {
            Task { @MainActor in self.onSpeak?(message) }
        }
        completionHandler()
    }
}
