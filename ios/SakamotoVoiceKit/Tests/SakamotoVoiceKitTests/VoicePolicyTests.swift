import Foundation
import Testing
@testable import SakamotoVoiceKit

@Suite struct VoicePolicyTests {
    @Test func eachSettingOnEachPath() {
        #expect(VoicePolicy.stream.want(onCellular: false) == .stream)
        #expect(VoicePolicy.stream.want(onCellular: true) == .stream)
        #expect(VoicePolicy.textOnCellular.want(onCellular: false) == .stream)
        #expect(VoicePolicy.textOnCellular.want(onCellular: true) == .text)
        #expect(VoicePolicy.textOnly.want(onCellular: false) == .text)
        #expect(VoicePolicy.textOnly.want(onCellular: true) == .text)
    }

    @Test func theDefaultIsTextOnCellular() {
        #expect(VoicePolicy.default == .textOnCellular)
        #expect(VoicePreference().want == .stream)
        #expect(VoicePreference(onCellular: true).want == .text)
    }

    @Test func storedRawValuesAreStable() {
        // UserDefaults keeps these; changing them would reset everyone's choice.
        #expect(VoicePolicy.allCases.map(\.rawValue) == ["stream", "textOnCellular", "textOnly"])
    }

    @Test func thePreferenceFollowsTheSettingAndThePath() {
        let preference = VoicePreference(policy: .stream)
        preference.onCellular = true
        #expect(preference.want == .stream)
        preference.policy = .textOnCellular
        #expect(preference.want == .text)
        preference.onCellular = false
        #expect(preference.want == .stream)
        preference.policy = .textOnly
        #expect(preference.want == .text)
    }

    @Test func thePreferenceIsSafeAcrossThreads() async {
        // The path monitor writes on its queue while the receiver reads on its own.
        let preference = VoicePreference(policy: .textOnly)
        await withTaskGroup(of: Void.self) { group in
            for i in 0..<200 {
                group.addTask {
                    if i.isMultiple(of: 2) { preference.onCellular = true } else { _ = preference.want }
                }
            }
            group.addTask { preference.policy = .textOnCellular }
        }
        #expect(preference.want == .text)
    }
}
