import Foundation
import Testing
@testable import SakamotoVoiceKit

@Suite struct WatchMirrorTests {
    let date = Date(timeIntervalSinceReferenceDate: 800_000_000)

    @Test func roundTripsAsAPropertyList() throws {
        let message = MirroredMessage(id: "A", date: date, text: "Hello. そうやで。",
                                      runs: [LangRun(lang: "default", text: "Hello."), LangRun(lang: "ja", text: "そうやで。")],
                                      source: .appStream, defaultLang: "ja", rate: 0.4)
        let dictionary = message.dictionary
        // Only property-list types, as WatchConnectivity and userInfo require.
        #expect(PropertyListSerialization.propertyList(dictionary, isValidFor: .binary))
        #expect(MirroredMessage(dictionary: dictionary) == message)
    }

    @Test func refusesWhatIsntAMessage() {
        #expect(MirroredMessage(dictionary: [:]) == nil)
        #expect(MirroredMessage(dictionary: ["kind": "message", "text": "Hi"]) == nil)        // no id
        #expect(MirroredMessage(dictionary: ["kind": "other", "id": "A", "text": "Hi"]) == nil)
        #expect(MirroredMessage(dictionary: ["kind": "message", "id": "A"]) == nil)            // no text
    }

    @Test func fillsInWhatIsMissing() throws {
        let message = try #require(MirroredMessage(dictionary: [
            "kind": "message", "id": "A", "text": "〔ja〕Kyoko. 〔en〕Moira.", "source": "telepathy", "defaultLang": "fr",
        ]))
        #expect(message.runs == [LangRun(lang: "ja", text: "Kyoko."), LangRun(lang: "en", text: "Moira.")])
        #expect(message.source == .text)
        #expect(message.defaultLang == "en")
        #expect(message.rate == 0.5)
        #expect(message.shownText == "Kyoko. Moira.")
    }

    @Test func notificationBodyIsTrimmedAndCut() {
        #expect(MirroredMessage(text: "  〔en〕Hello there.  ").notificationBody() == "Hello there.")
        let long = MirroredMessage(text: String(repeating: "word ", count: 400))
        let body = long.notificationBody(limit: 100)
        #expect(body.count <= 100)
        #expect(body.hasSuffix("word…"))
    }

    @Test func historyIsNewestFirstWithoutDuplicates() {
        let a = MirroredMessage(id: "a", date: date, text: "A")
        let b = MirroredMessage(id: "b", date: date.addingTimeInterval(10), text: "B")
        let c = MirroredMessage(id: "c", date: date.addingTimeInterval(5), text: "C")
        var history: [MirroredMessage] = []
        history = MirroredMessage.inserting(a, into: history, limit: 3)
        history = MirroredMessage.inserting(b, into: history, limit: 3)
        history = MirroredMessage.inserting(c, into: history, limit: 3)    // a late arrival, by its date
        history = MirroredMessage.inserting(b, into: history, limit: 3)    // again, with its notification
        #expect(history.map(\.id) == ["b", "c", "a"])
        let d = MirroredMessage(id: "d", date: date.addingTimeInterval(20), text: "D")
        #expect(MirroredMessage.inserting(d, into: history, limit: 3).map(\.id) == ["d", "b", "c"])
    }

    @Test func onlyFreshMessagesAreReadUnasked() {
        let message = MirroredMessage(date: date, text: "Hi")
        #expect(message.isFresh(at: date.addingTimeInterval(30)))
        #expect(!message.isFresh(at: date.addingTimeInterval(600)))
    }
}
