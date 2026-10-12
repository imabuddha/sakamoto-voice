import SakamotoVoiceKit
import SwiftUI
import WatchKit

/// Sakamoto Voice on Apple Watch: lists the messages the iPhone app mirrors to it and reads them
/// aloud on the watch.
@main
struct SakamotoVoiceWatchApp: App {
    @WKApplicationDelegateAdaptor private var delegate: WatchAppDelegate
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView(model: .shared)
        }
        .onChange(of: scenePhase) { _, phase in
            WatchModel.shared.scenePhaseChanged(phase)
        }
        // Transfers that arrive while the app is in the background.
        .backgroundTask(.watchConnectivity) {
            await WatchModel.shared.receivePendingTransfers()
        }

        // The notification the phone posts for each message (its Speak action comes with it).
        WKNotificationScene(controller: NotificationController.self, category: MirroredMessage.notificationCategory)
    }
}

/// Sets up the notification delegate and the WatchConnectivity session at launch, before a
/// notification's action or a transfer is delivered.
final class WatchAppDelegate: NSObject, WKApplicationDelegate {
    func applicationDidFinishLaunching() {
        WatchModel.shared.start()
    }
}
