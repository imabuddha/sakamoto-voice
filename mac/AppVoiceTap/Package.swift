// swift-tools-version: 6.0
// AppVoiceTap: `app-voice-tap`, the Mac side of `output app-phone`. It captures only the Claude
// desktop app's audio (a Core Audio process tap, which can also mute the app on the Mac's
// speakers) and streams it live to the Sakamoto Voice app on the phone.
//
//     ../build.sh          # builds it (release) into ../../bin/app-voice-tap, signed
//     swift test           # the unit tests (no audio is captured)
//
// The executable embeds Info.plist (its name, identifier, and the reason macOS shows when it asks
// for System Audio Recording), so macOS's privacy check can name it.

import Foundation
import PackageDescription

let infoPlist = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Info.plist").path

let package = Package(
    name: "AppVoiceTap",
    platforms: [.macOS(.v15)],
    products: [
        .executable(name: "app-voice-tap", targets: ["app-voice-tap"]),
    ],
    dependencies: [
        .package(path: "../../ios/SakamotoVoiceKit"),
    ],
    targets: [
        // The pure parts: options, the silence gate, resampling, process matching, the phone socket.
        .target(name: "AppVoiceTapCore", dependencies: [
            .product(name: "SakamotoVoiceKit", package: "SakamotoVoiceKit"),
        ]),
        // Core Audio, permissions, and the main loop.
        .executableTarget(
            name: "app-voice-tap",
            dependencies: ["AppVoiceTapCore"],
            linkerSettings: [
                .unsafeFlags(["-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist",
                              "-Xlinker", infoPlist]),
            ]
        ),
        .testTarget(name: "AppVoiceTapCoreTests", dependencies: [
            "AppVoiceTapCore",
            .product(name: "SakamotoVoiceKit", package: "SakamotoVoiceKit"),
        ]),
    ]
)
