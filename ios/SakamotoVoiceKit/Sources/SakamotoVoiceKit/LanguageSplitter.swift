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

    public static func runs(in text: String, other: String = "en") -> [LangRun] {
        var raw: [(String, String.UnicodeScalarView)] = []
        var current = String.UnicodeScalarView()
        var inJapanese = false
        for scalar in text.unicodeScalars {
            if inJapanese {
                if continuesJapanese(scalar) {
                    current.append(scalar)
                    continue
                }
                raw.append(("ja", current))
                current = String.UnicodeScalarView()
                inJapanese = false
            }
            if isJapaneseScript(scalar) {
                if !current.isEmpty { raw.append((other, current)) }
                current = String.UnicodeScalarView([scalar])
                inJapanese = true
            } else {
                current.append(scalar)
            }
        }
        if !current.isEmpty { raw.append((inJapanese ? "ja" : other, current)) }

        return raw.compactMap { lang, scalars in
            let text = String(scalars)
            guard !text.trimmingCharacters(in: ignorable).isEmpty else { return nil }
            return LangRun(lang: lang, text: text.trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }
}
