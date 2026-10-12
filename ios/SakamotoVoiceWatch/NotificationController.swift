import SakamotoVoiceKit
import SwiftUI
import UserNotifications
import WatchKit

/// The notification's long look on the watch: Miss Sakamoto's avatar and the whole message (the
/// notification's body is cut at 1,000 characters; the message it carries isn't). Its Speak
/// action, from the category, opens the app, which reads the message aloud.
final class NotificationController: WKUserNotificationHostingController<NotificationView> {
    private var text = ""
    private var date: Date?

    override var body: NotificationView {
        NotificationView(text: text, date: date)
    }

    override func didReceive(_ notification: UNNotification) {
        let message = WatchModel.message(in: notification)
        text = message?.shownText ?? notification.request.content.body
        date = message?.date ?? notification.date
        // watchOS reads `body` after this returns.
    }
}

struct NotificationView: View {
    let text: String
    let date: Date?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) {
                Text("👩🏻‍🔬")
                    .accessibilityHidden(true)
                Text(MirroredMessage.notificationTitle)
                    .font(.headline)
                if let date {
                    Spacer(minLength: 0)
                    Text(date, style: .time)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            Text(text)
                .font(.body)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
