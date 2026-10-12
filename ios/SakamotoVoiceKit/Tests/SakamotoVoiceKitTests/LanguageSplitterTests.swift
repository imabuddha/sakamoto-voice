import Testing
@testable import SakamotoVoiceKit

/// The same cases as plugin/tests/test_speak.py's SegmentsTests, so the phone splits as the Mac does.
@Suite struct LanguageSplitterTests {
    func runs(_ text: String) -> [[String]] {
        LanguageSplitter.runs(in: text).map { [$0.lang, $0.text] }
    }

    @Test func englishOnly() {
        #expect(runs("Hello there.") == [["en", "Hello there."]])
    }

    @Test func japaneseOnly() {
        #expect(runs("そうやで。") == [["ja", "そうやで。"]])
    }

    @Test func theTestLine() {
        #expect(runs("Good heavens, Miss Sakamoto, you can talk! そうやで。")
                == [["en", "Good heavens, Miss Sakamoto, you can talk!"], ["ja", "そうやで。"]])
    }

    @Test func japaneseInTheMiddle() {
        #expect(runs("The word 囲碁 means Go.") == [["en", "The word"], ["ja", "囲碁"], ["en", "means Go."]])
    }

    @Test func digitsAndSpacesStayInAJapaneseRun() {
        #expect(runs("今日は 10 月 12 日です. Done") == [["ja", "今日は 10 月 12 日です"], ["en", ". Done"]])
    }

    @Test func digitsBeforeJapaneseAreEnglish() {
        #expect(runs("3 時") == [["en", "3"], ["ja", "時"]])
    }

    @Test func punctuationOnlyRunsAreDropped() {
        #expect(runs("「はい」.") == [["ja", "「はい」"]])
        #expect(runs("..., 。") == [["ja", "。"]])
        #expect(runs(" ; ") == [])
        #expect(runs("") == [])
    }

    @Test func fullWidthAndKatakana() {
        #expect(runs("Play ＡＢＣ and カタカナ!") == [["en", "Play"], ["ja", "ＡＢＣ"], ["en", "and"], ["ja", "カタカナ"], ["en", "!"]])
    }

    @Test func newlinesJoinJapaneseRuns() {
        #expect(runs("一\n二\nthree") == [["ja", "一\n二"], ["en", "three"]])
    }

    @Test func otherTextCanBeLeftToThePhonesDefault() {
        #expect(LanguageSplitter.runs(in: "The word 囲碁 means Go.", other: LangRun.phoneDefault).map { [$0.lang, $0.text] }
                == [["default", "The word"], ["ja", "囲碁"], ["default", "means Go."]])
    }
}
