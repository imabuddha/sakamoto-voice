import Foundation

/// The voice markers 〔en〕 and 〔ja〕, as the Mac reads them (`voice_runs` and `strip_markers` in
/// plugin/scripts/speak.py). The Mac applies and removes them before it sends anything, so the
/// phone never sees one; these are for text that may still carry them (the Apple Watch's
/// notifications and text that arrives without its runs).
///
/// A marker is the tortoise-shell brackets around 1 to 10 ASCII letters or hyphens, starting with
/// a letter (spaces inside allowed, case ignored). 〔en〕 or 〔ja〕 switches to that voice until the
/// next marker or the end of its paragraph (a blank line), where the default resumes; any other
/// marker (〔xx〕) is dropped and changes nothing. Japanese in the same brackets (〔注〕) is text.
public enum VoiceMarkers {
    static let languages: Set<String> = ["en", "ja"]

    /// The text without its markers, for the screen (the spaces they leave tidied).
    public static func strip(_ text: String) -> String {
        let stripped = text.replacing(/〔\s*[A-Za-z][A-Za-z\-]{0,9}\s*〕/, with: "")
            .replacing(/[ \t]{2,}/, with: " ")
        return stripped.split(separator: "\n", omittingEmptySubsequences: false)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Runs for the voices, with the markers applied and removed. Unmarked text is tagged
    /// `defaultLang` ("en", "ja", or `LangRun.phoneDefault`, which leaves it to the speaker's own
    /// setting); Japanese script is always "ja". A run that is only spaces and punctuation joins
    /// the one before it.
    public static func runs(in text: String, defaultLang: String = LangRun.phoneDefault) -> [LangRun] {
        let base = languages.contains(defaultLang) ? defaultLang : LangRun.phoneDefault
        let full = text + "\n\n"
        // The breaks are found in `full` (so the last paragraph has one too), but each gap is cut
        // at the end of `text`, so the two newlines added here never reach a run.
        let textEnd = full.utf8.index(full.utf8.startIndex, offsetBy: text.utf8.count)
        var spans: [LanguageSplitter.Span] = []
        var position = full.startIndex
        for paragraphBreak in full.matches(of: /\n[ \t]*\n\s*/) {
            let paragraph = full[position..<paragraphBreak.range.lowerBound]
            let gapEnd = min(paragraphBreak.range.upperBound, textEnd)
            let gap = paragraphBreak.range.lowerBound < gapEnd
                ? String(full[paragraphBreak.range.lowerBound..<gapEnd]) : ""
            position = paragraphBreak.range.upperBound
            var lang = base
            var at = paragraph.startIndex
            for marker in paragraph.matches(of: /〔\s*([A-Za-z][A-Za-z\-]{0,9})\s*〕/) {
                spans += LanguageSplitter.scriptSpans(paragraph[at..<marker.range.lowerBound], other: lang)
                let code = marker.output.1.lowercased()
                if languages.contains(code) { lang = code }
                at = marker.range.upperBound
            }
            spans += LanguageSplitter.scriptSpans(paragraph[at...], other: lang)
            if !spans.isEmpty { spans[spans.count - 1].text += gap }   // the break stays with what it ends
        }
        return LanguageSplitter.tidy(spans, absorb: true)
    }
}
