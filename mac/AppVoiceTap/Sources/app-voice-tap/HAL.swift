import CoreAudio
import Darwin
import Foundation

/// Small helpers for Core Audio's object properties.
enum HAL {
    struct Failure: Error, CustomStringConvertible {
        let what: String
        let status: OSStatus

        var description: String { "\(what) failed (\(HAL.fourCC(status)))" }
    }

    static func check(_ status: OSStatus, _ what: String) throws(Failure) {
        guard status == noErr else { throw Failure(what: what, status: status) }
    }

    /// An OSStatus as its four characters when it has them ('who?'), else as a number.
    static func fourCC(_ status: OSStatus) -> String {
        let bytes = withUnsafeBytes(of: UInt32(bitPattern: status).bigEndian) { Array($0) }
        if bytes.allSatisfy({ (0x20...0x7E).contains($0) }) {
            return "'" + String(decoding: bytes, as: UTF8.self) + "'"
        }
        return String(status)
    }

    static func address(_ selector: AudioObjectPropertySelector,
                        _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
        AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
    }

    /// A property holding a plain value (a number, an ID, a format).
    static func value<T: BitwiseCopyable>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector,
                                          scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal,
                                          default value: T) throws(Failure) -> T {
        var address = address(selector, scope)
        var size = UInt32(MemoryLayout<T>.size)
        var result = value
        let status = withUnsafeMutableBytes(of: &result) { bytes in
            AudioObjectGetPropertyData(object, &address, 0, nil, &size, bytes.baseAddress!)
        }
        try check(status, "reading a property")
        return result
    }

    static func objects(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector,
                        scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) throws(Failure) -> [AudioObjectID] {
        var address = address(selector, scope)
        var size: UInt32 = 0
        try check(AudioObjectGetPropertyDataSize(object, &address, 0, nil, &size), "sizing a list")
        var list = [AudioObjectID](repeating: kAudioObjectUnknown, count: Int(size) / MemoryLayout<AudioObjectID>.size)
        try check(AudioObjectGetPropertyData(object, &address, 0, nil, &size, &list), "reading a list")
        return Array(list.prefix(Int(size) / MemoryLayout<AudioObjectID>.size))
    }

    static func string(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
        var address = address(selector)
        var size = UInt32(MemoryLayout<CFString?>.size)
        var result: Unmanaged<CFString>?
        let status = withUnsafeMutablePointer(to: &result) {
            AudioObjectGetPropertyData(object, &address, 0, nil, &size, $0)
        }
        guard status == noErr, let result else { return nil }
        return result.takeRetainedValue() as String
    }

    /// The system's default output device and its UID.
    static func defaultOutputDevice() throws(Failure) -> (AudioObjectID, String) {
        let device = try value(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDefaultSystemOutputDevice,
                               default: AudioObjectID(kAudioObjectUnknown))
        guard device != kAudioObjectUnknown, let uid = string(device, kAudioDevicePropertyDeviceUID) else {
            throw Failure(what: "finding the default output device", status: OSStatus(kAudioHardwareBadDeviceError))
        }
        return (device, uid)
    }

    /// A process Core Audio knows (one that has used audio).
    struct Process: Sendable {
        let object: AudioObjectID
        let pid: pid_t
        let bundleID: String
        let path: String
        let isPlaying: Bool
    }

    static func processes() -> [Process] {
        guard let list = try? objects(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyProcessObjectList) else {
            return []
        }
        return list.map { object in
            let pid = (try? value(object, kAudioProcessPropertyPID, default: pid_t(-1))) ?? -1
            let playing = (try? value(object, kAudioProcessPropertyIsRunningOutput, default: UInt32(0))) ?? 0
            return Process(object: object, pid: pid, bundleID: string(object, kAudioProcessPropertyBundleID) ?? "",
                           path: executablePath(pid), isPlaying: playing != 0)
        }
    }

    static func executablePath(_ pid: pid_t) -> String {
        guard pid > 0 else { return "" }
        var buffer = [UInt8](repeating: 0, count: 4 * Int(MAXPATHLEN))
        let length = proc_pidpath(pid, &buffer, UInt32(buffer.count))
        return length > 0 ? String(decoding: buffer.prefix(Int(length)), as: UTF8.self) : ""
    }
}
