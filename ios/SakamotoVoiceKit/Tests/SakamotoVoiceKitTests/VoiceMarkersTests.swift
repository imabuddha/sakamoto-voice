import Testing
@testable import SakamotoVoiceKit

/// The same cases as plugin/tests/test_speak.py's VoiceRunsTests, so the watch reads markers as
/// the Mac does.
@Suite struct VoiceMarkersTests {
    func runs(_ text: String, _ defaultLang: String = "ja") -> [[String]] {
        VoiceMarkers.runs(in: text, defaultLang: defaultLang).map { [$0.lang, $0.text] }
    }

    @Test func thePhoneDefaultLeavesUnmarkedTextToTheSpeaker() {
        #expect(runs("The word 囲碁 means Go.", "default")
                == [["default", "The word"], ["ja", "囲碁"], ["default", "means Go."]])
        #expect(VoiceMarkers.runs(in: "Hi 〔en〕there 〔ja〕friend.\n\nBye.").map { [$0.lang, $0.text] }
                == [["default", "Hi"], ["en", "there"], ["ja", "friend."], ["default", "Bye."]])
    }

    @Test func defaultJaReadsEverything() {
        #expect(runs("The word 囲碁 means Go.") == [["ja", "The word 囲碁 means Go."]])
        #expect(runs("Hello.\n\nそうやで。\n\nBye.") == [["ja", "Hello.\n\nそうやで。\n\nBye."]])
    }

    @Test func defaultEnIsByScript() {
        #expect(runs("The word 囲碁 means Go.", "en") == [["en", "The word"], ["ja", "囲碁"], ["en", "means Go."]])
    }

    @Test func aBadDefaultIsTheSpeakers() {
        #expect(runs("Hello", "fr") == [["default", "Hello"]])
        #expect(runs("Hello", "auto") == [["default", "Hello"]])
    }

    @Test func enMarkerSwitchesUntilTheNextMarker() {
        #expect(runs("Kyoko here. 〔en〕Moira here. 〔ja〕Kyoko again.")
                == [["ja", "Kyoko here."], ["en", "Moira here."], ["ja", "Kyoko again."]])
    }

    @Test func japaneseScriptIsAlwaysJa() {
        #expect(runs("〔en〕The word 囲碁 means Go.") == [["en", "The word"], ["ja", "囲碁"], ["en", "means Go."]])
    }

    @Test func jaMarkerWithDefaultEn() {
        #expect(runs("Plain. 〔ja〕Read by Kyoko.", "en") == [["en", "Plain."], ["ja", "Read by Kyoko."]])
    }

    @Test func paragraphEndResetsToTheDefault() {
        #expect(runs("〔en〕One,\nstill one.\n\nTwo.\n \nThree.")
                == [["en", "One,\nstill one."], ["ja", "Two.\n \nThree."]])
        #expect(runs("〔ja〕One.\n\nTwo.", "en") == [["ja", "One."], ["en", "Two."]])
    }

    @Test func markersAreNeverSpoken() {
        for text in ["〔en〕", "〔en〕〔ja〕", "〔ja〕 . ", "〔xx〕", "〔EN〕Hi", "〔 en 〕Hi"] {
            #expect(!VoiceMarkers.runs(in: text).contains { $0.text.contains("〔") || $0.text.contains("〕") },
                    "\(text)")
        }
        #expect(runs("〔EN〕Hi") == [["en", "Hi"]])
        #expect(runs("〔 en 〕Hi") == [["en", "Hi"]])
    }

    @Test func unknownMarkersAreStrippedAndChangeNothing() {
        #expect(runs("〔en〕Hello 〔xx〕there.") == [["en", "Hello there."]])
        #expect(runs("Hello 〔fr〕there.") == [["ja", "Hello there."]])
        #expect(runs("Hello 〔fr〕there.", "default") == [["default", "Hello there."]])
    }

    @Test func bracketedJapaneseIsText() {
        #expect(runs("〔en〕See 〔注〕 below.") == [["en", "See"], ["ja", "〔注〕"], ["en", "below."]])
    }

    @Test func punctuationStaysWithItsNeighbor() {
        #expect(runs("〔en〕Go is 囲碁. 〔ja〕Yes.") == [["en", "Go is"], ["ja", "囲碁. Yes."]])
        #expect(runs("〔en〕.") == [])
    }

    @Test func textEndingInABlankLineKeepsNoExtraNewlines() {
        #expect(runs("Hello.\n\n", "en") == [["en", "Hello."]])
        #expect(runs("", "en") == [])
    }

    @Test func strip() {
        let cases = [
            "〔en〕Hello 〔ja〕囲碁 〔xx〕friend.": "Hello 囲碁 friend.",
            "Say 〔ja〕 hi.": "Say hi.",
            "〔en〕 Line one\n〔ja〕Line two\n\n〔en〕": "Line one\nLine two",
            "See 〔注〕.": "See 〔注〕.",
            "No markers.": "No markers.",
        ]
        for (text, expected) in cases {
            #expect(VoiceMarkers.strip(text) == expected, "\(text)")
        }
    }
}
