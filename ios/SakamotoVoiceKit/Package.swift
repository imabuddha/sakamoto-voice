// swift-tools-version: 6.0
// SakamotoVoiceKit: the iPhone app's pure parts (the wire protocol, pairing, language runs and voice
// markers, the stay-awake schedule, the silent keep-alive sound, and the messages it mirrors to the
// Apple Watch) and its network receiver, plus `voice-listen`, a Mac command-line receiver for
// trying the Mac side without a phone. The watch app uses it too (not the receiver: watchOS allows
// apps no listener).
//
//     swift test                      # the unit tests, headless, on the Mac
//     swift run voice-listen 123456   # a stand-in phone on the Mac, with pairing code 123456

import PackageDescription

let package = Package(
    name: "SakamotoVoiceKit",
    platforms: [.iOS(.v18), .watchOS(.v11), .macOS(.v15)],
    products: [
        .library(name: "SakamotoVoiceKit", targets: ["SakamotoVoiceKit"]),
        .executable(name: "voice-listen", targets: ["voice-listen"]),
    ],
    targets: [
        .target(name: "SakamotoVoiceKit"),
        .executableTarget(name: "voice-listen", dependencies: ["SakamotoVoiceKit"]),
        .testTarget(name: "SakamotoVoiceKitTests", dependencies: ["SakamotoVoiceKit"]),
    ]
)
