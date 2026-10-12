import Foundation
import Testing
@testable import SakamotoVoiceKit

@Suite struct MessageTests {
    func decode(_ json: String) throws -> VoiceMessage {
        try MessageDecoder.decode(Data(json.utf8))
    }

    @Test func textWithRunsFromTheMac() throws {
        let message = try decode("""
            {"token": "123456", "kind": "text", "text": "Hello. そうやで。",
             "lang_runs": [{"lang": "en", "text": "Hello."}, {"lang": "ja", "text": "そうやで。"}]}
            """)
        #expect(message.token == "123456")
        #expect(message.kind == .text)
        let incoming = try MessageDecoder.validate(message)
        #expect(incoming == .text("Hello. そうやで。", runs: [LangRun(lang: "en", text: "Hello."),
                                                            LangRun(lang: "ja", text: "そうやで。")]))
    }

    @Test func textWithoutRunsIsSplitHere() throws {
        let incoming = try MessageDecoder.validate(decode(#"{"token": "1", "kind": "text", "text": "Hi 囲碁"}"#))
        #expect(incoming == .text("Hi 囲碁", runs: [LangRun(lang: "default", text: "Hi"), LangRun(lang: "ja", text: "囲碁")]))
    }

    @Test func defaultRunsFromTheMacPassThrough() throws {
        let incoming = try MessageDecoder.validate(decode("""
            {"token": "1", "kind": "text", "text": "Hi 囲碁 there",
             "lang_runs": [{"lang": "default", "text": "Hi"}, {"lang": "ja", "text": "囲碁"}, {"lang": "en", "text": "there"}]}
            """))
        #expect(incoming == .text("Hi 囲碁 there", runs: [LangRun(lang: "default", text: "Hi"),
                                                       LangRun(lang: "ja", text: "囲碁"),
                                                       LangRun(lang: "en", text: "there")]))
    }

    @Test func emptyRunsFallBackToSplitting() throws {
        let incoming = try MessageDecoder.validate(decode(#"{"token": "1", "kind": "text", "text": "Hi", "lang_runs": [{"lang": "en", "text": "  "}]}"#))
        #expect(incoming == .text("Hi", runs: [LangRun(lang: "default", text: "Hi")]))
    }

    @Test func runsWithoutTextAreShownJoined() throws {
        let incoming = try MessageDecoder.validate(decode(#"{"token": "1", "kind": "text", "lang_runs": [{"lang": "en", "text": "A"}, {"lang": "ja", "text": "い"}]}"#))
        #expect(incoming == .text("A い", runs: [LangRun(lang: "en", text: "A"), LangRun(lang: "ja", text: "い")]))
    }

    @Test func blankTextIsRefused() throws {
        #expect(throws: MessageError.noText) {
            try MessageDecoder.validate(decode(#"{"token": "1", "kind": "text", "text": " . "}"#))
        }
    }

    @Test func audio() throws {
        let b64 = Data("RIFFxxxx".utf8).base64EncodedString()
        let incoming = try MessageDecoder.validate(decode(#"{"token": "1", "kind": "audio", "audio_b64": "\#(b64)", "format": "M4A", "text": " Hello "}"#))
        #expect(incoming == .audio(Data("RIFFxxxx".utf8), format: "m4a", text: "Hello"))
    }

    @Test func audioDefaultsToM4AAndNoText() throws {
        let b64 = Data([1, 2, 3]).base64EncodedString()
        let incoming = try MessageDecoder.validate(decode(#"{"token": "1", "kind": "audio", "audio_b64": "\#(b64)"}"#))
        #expect(incoming == .audio(Data([1, 2, 3]), format: "m4a", text: ""))
    }

    @Test(arguments: [#"{"token": "1", "kind": "audio"}"#,
                      #"{"token": "1", "kind": "audio", "audio_b64": "!!!"}"#,
                      #"{"token": "1", "kind": "audio", "audio_b64": ""}"#])
    func badAudioIsRefused(json: String) throws {
        #expect(throws: MessageError.badAudio) { try MessageDecoder.validate(decode(json)) }
    }

    @Test func pingAndStop() throws {
        #expect(try MessageDecoder.validate(decode(#"{"token": "1", "kind": "ping"}"#)) == .ping)
        #expect(try MessageDecoder.validate(decode(#"{"token": "1", "kind": "stop"}"#)) == .stop)
    }

    @Test(arguments: ["", "not json", #"{"kind": "text", "text": "no token"}"#,
                      #"{"token": "1", "kind": "sing", "text": "x"}"#, #"["token"]"#])
    func malformed(json: String) {
        #expect(throws: MessageError.malformed) { try MessageDecoder.decode(Data(json.utf8)) }
    }

    @Test func tooLarge() {
        let data = Data(count: VoiceProtocol.maxMessageBytes + 1)
        #expect(throws: MessageError.tooLarge) { try MessageDecoder.decode(data) }
    }

    @Test func unknownFieldsAreIgnored() throws {
        let message = try decode(#"{"token": "1", "kind": "ping", "from": "Mac", "v": 2}"#)
        #expect(message.kind == .ping)
    }

    @Test func ackIsOneSortedJSONLine() throws {
        let data = Ack.failure(.badToken, version: "0.1.0").encoded()
        #expect(String(decoding: data, as: UTF8.self)
                == #"{"app":"Sakamoto Voice","error":"bad token","ok":false,"version":"0.1.0"}"# + "\n")
        let ok = try JSONDecoder().decode(Ack.self, from: Ack.success(version: "1").encoded())
        #expect(ok.ok && ok.error == nil)
    }

    @Test func ackSaysWhatThePhoneWants() throws {
        let data = Ack.success(version: "1.0", voice: .stream).encoded()
        #expect(String(decoding: data, as: UTF8.self)
                == #"{"app":"Sakamoto Voice","ok":true,"version":"1.0","voice":"stream"}"# + "\n")
        let text = try JSONDecoder().decode(Ack.self, from: Ack.success(version: "1.0", voice: .text).encoded())
        #expect(text.voice == .text && text.want == nil)
    }

    @Test func aDeclinedStreamIsNotAnError() throws {
        let data = Ack.wantsText(version: "1.0").encoded()
        #expect(String(decoding: data, as: UTF8.self)
                == #"{"app":"Sakamoto Voice","ok":false,"version":"1.0","voice":"text","want":"text"}"# + "\n")
        let ack = try JSONDecoder().decode(Ack.self, from: data)
        #expect(!ack.ok && ack.error == nil && ack.want == .text)
    }

    @Test func anOldPhonesAckHasNoVoice() throws {
        let ack = try JSONDecoder().decode(Ack.self, from: Data(#"{"app":"Sakamoto Voice","ok":true,"version":"0.3.1"}"#.utf8))
        #expect(ack.ok && ack.voice == nil && ack.want == nil)
    }

    @Test(arguments: [false, true])
    func explicitRunsIgnoreThePhonesDefault(defaultIsJapanese: Bool) {
        #expect(LangRun(lang: "ja", text: "").isJapanese(byDefault: defaultIsJapanese))
        #expect(LangRun(lang: "ja-JP", text: "").isJapanese(byDefault: defaultIsJapanese))
        #expect(LangRun(lang: "JA", text: "").isJapanese(byDefault: defaultIsJapanese))
        #expect(!LangRun(lang: "en", text: "").isJapanese(byDefault: defaultIsJapanese))
        #expect(!LangRun(lang: "fr", text: "").isJapanese(byDefault: defaultIsJapanese))
    }

    @Test func defaultRunsFollowThePhonesDefault() {
        #expect(!LangRun(lang: "default", text: "").isJapanese(byDefault: false))
        #expect(LangRun(lang: "default", text: "").isJapanese(byDefault: true))
        #expect(LangRun(lang: "Default", text: "").isJapanese(byDefault: true))
        #expect(LangRun(lang: "", text: "").isJapanese(byDefault: true))
        #expect(!LangRun(lang: "", text: "").isJapanese(byDefault: false))
    }
}
