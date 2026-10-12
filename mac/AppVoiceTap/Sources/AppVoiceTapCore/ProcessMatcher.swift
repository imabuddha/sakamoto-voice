import Foundation

/// Which processes belong to the Claude app: those running from inside its bundle (its helpers,
/// such as the audio service, live in Contents/Frameworks) and those whose bundle ID is one of
/// the app's or starts with one and a dot (com.anthropic.claudefordesktop.helper).
public struct ProcessMatcher: Equatable, Sendable {
    public let appPath: String
    public let bundleIDs: [String]

    public init(appPath: String, bundleIDs: [String]) {
        var path = (appPath as NSString).standardizingPath
        while path.count > 1, path.hasSuffix("/") { path.removeLast() }
        self.appPath = path
        self.bundleIDs = bundleIDs.filter { !$0.isEmpty }
    }

    public func matches(bundleID: String?, path: String?) -> Bool {
        if let bundleID, !bundleID.isEmpty,
           bundleIDs.contains(where: { bundleID == $0 || bundleID.hasPrefix($0 + ".") }) {
            return true
        }
        if let path, !appPath.isEmpty, path.hasPrefix(appPath + "/") {
            return true
        }
        return false
    }

    /// The bundle IDs to name in a tap: the configured ones, the helpers' (".helper", as Electron
    /// names them), and any others seen on matching processes.
    public func tapBundleIDs(seen: [String]) -> [String] {
        var ids: [String] = []
        for id in bundleIDs + bundleIDs.map({ $0 + ".helper" }) + seen where !id.isEmpty && !ids.contains(id) {
            ids.append(id)
        }
        return ids
    }
}
