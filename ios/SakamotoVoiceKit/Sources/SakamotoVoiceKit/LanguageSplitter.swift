import Foundation

/// Splits text into English and Japanese runs by script, the same way the Mac does
/// (`segments` in plugin/scripts/speak.py): a Japanese run starts at kana, kanji, or a full-width
/// character and continues through more of them, whitespace, Japanese punctuation, and digits;
/// everything else is tagged `other` ("en" by default; LangRun.phoneDefault leaves it to the
/// phone's default voice). Runs with nothing but spaces and punctuation are dropped.
public enum LanguageSplitter {
    static func isJapaneseScript(_ s: Unicode.Scalar) -> Bool {
        switch s.value {
        case 0x3000...0x30FF,      // CJK punctuation, hiragana, katakana
             0x3400...0x9FFF,      // CJK ideographs (and extension A)
             0xF900...0xFAFF,      // CJK compatibility ideographs
             0xFF00...0xFFEF:      // full-width forms
            return true
        default:
            return false
        }
    }

    static func continuesJapanese(_ s: Unicode.Scalar) -> Bool {
        isJapaneseScript(s) || s.properties.isWhitespace || ("0"..."9").contains(s)
    }

    private static let ignorable = CharacterSet(charactersIn: " \n\t.,;:")

    /// A stretch of text and its voice, before tidying.
    struct Span {
        var lang: String
        var text: String
    }

    public static func runs(in text: String, other: String = "en") -> [LangRun] {
        tidy(scriptSpans(text[...], other: other), absorb: false)
    }

    /// Raw spans by script: Japanese script (and what continues it) is "ja"; the rest is `other`.
    static func scriptSpans(_ text: Substring, other: String) -> [Span] {
        var spans: [Span] = []
        var current = String.UnicodeScalarView()
        var inJapanese = false
        for scalar in text.unicodeScalars {
            if inJapanese {
                if continuesJapanese(scalar) {
                    current.append(scalar)
                    continue
                }
                spans.append(Span(lang: "ja", text: String(current)))
                current = String.UnicodeScalarView()
                inJapanese = false
            }
            if isJapaneseScript(scalar) {
                if !current.isEmpty { spans.append(Span(lang: other, text: String(current))) }
                current = String.UnicodeScalarView([scalar])
                inJapanese = true
            } else {
                current.append(scalar)
            }
        }
        if !current.isEmpty { spans.append(Span(lang: inJapanese ? "ja" : other, text: String(current))) }
        return spans
    }

    /// Joins neighboring spans in the same voice, then trims them and drops the ones with nothing
    /// but spaces and punctuation (`tidy` in speak.py). With `absorb`, such a span joins the one
    /// before it instead, so the spans on either side of it can join too.
    static func tidy(_ spans: [Span], absorb: Bool) -> [LangRun] {
        var merged: [Span] = []
        for span in spans {
            if let last = merged.last,
               last.lang == span.lang || (absorb && span.text.trimmingCharacters(in: ignorable).isEmpty) {
                merged[merged.count - 1].text += span.text
            } else {
                merged.append(span)
            }
        }
        return merged.compactMap { span in
            guard !span.text.trimmingCharacters(in: ignorable).isEmpty else { return nil }
            return LangRun(lang: span.lang, text: span.text.trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }
}
