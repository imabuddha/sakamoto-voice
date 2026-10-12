import SwiftUI

/// Sakamoto Voice: speaks Claude's responses, sent from the Mac over the local network.
@main
struct SakamotoVoiceApp: App {
    @State private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView(model: model)
        }
        .onChange(of: scenePhase) { _, phase in
            model.scenePhaseChanged(phase)
        }
    }
}
