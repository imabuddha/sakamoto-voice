// swift-tools-version: 6.0
// SakamotoVoiceKit: the iPhone app's pure parts (the wire protocol, pairing, language runs, the
// stay-awake schedule, and the silent keep-alive sound) and its network receiver, plus
// `voice-listen`, a Mac command-line receiver for trying the Mac side without a phone.
//
//     swift test                      # the unit tests, headless, on the Mac
//     swift run voice-listen 123456   # a stand-in phone on the Mac, with pairing code 123456

import PackageDescription

let package = Package(
    name: "SakamotoVoiceKit",
    platforms: [.iOS(.v18), .macOS(.v15)],
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
