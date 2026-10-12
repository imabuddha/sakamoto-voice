import CoreAudio
import Foundation
import Synchronization

/// Tapped samples (mono floats), handed from Core Audio's IO thread to the main loop.
final class SampleQueue: Sendable {
    private let samples = Mutex<[Float]>([])
    /// More than this waiting (the main loop stalled) drops the oldest.
    private let limit: Int

    init(limit: Int) {
        self.limit = limit
    }

    /// Mixes the tap's buffers (those after the first `skip`, which belong to the aggregate
    /// device's other members) down to mono and queues them.
    func append(_ input: UnsafePointer<AudioBufferList>, skipping skip: Int) {
        let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
        guard buffers.count > skip else { return }
        var channels = 0
        var frames = Int.max
        for i in skip..<buffers.count {
            let perFrame = max(1, Int(buffers[i].mNumberChannels))
            channels += perFrame
            frames = min(frames, Int(buffers[i].mDataByteSize) / (4 * perFrame))
        }
        guard frames > 0, frames != .max else { return }
        var mono: [Float]
        if channels == 1, let data = buffers[skip].mData {
            mono = Array(UnsafeBufferPointer(start: data.assumingMemoryBound(to: Float.self), count: frames))
        } else {
            mono = [Float](repeating: 0, count: frames)
            for i in skip..<buffers.count {
                guard let data = buffers[i].mData else { continue }
                let perFrame = max(1, Int(buffers[i].mNumberChannels))
                let source = data.assumingMemoryBound(to: Float.self)
                for frame in 0..<frames {
                    for channel in 0..<perFrame { mono[frame] += source[frame * perFrame + channel] }
                }
            }
            let scale = 1 / Float(channels)
            for frame in 0..<frames { mono[frame] *= scale }
        }
        samples.withLock { queued in
            queued += mono
            if queued.count > limit { queued.removeFirst(queued.count - limit) }
        }
    }

    func drain() -> [Float] {
        samples.withLock { queued in
            let out = queued
            queued.removeAll(keepingCapacity: true)
            return out
        }
    }
}

/// A Core Audio process tap on the Claude app's processes, mixed to mono, inside a private
/// aggregate device whose IO callback queues the samples. With `mute`, the tap is
/// CATapMutedWhenTapped: while it's being read, the app is silent on the Mac's speakers.
/// Everything is removed by `stop()` (and, being private, by Core Audio if the process dies).
final class AppTap {
    let sampleRate: Double
    let queue: SampleQueue
    private(set) var processes: [AudioObjectID]
    private let description: CATapDescription
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggregateID = AudioObjectID(kAudioObjectUnknown)
    private var procID: AudioDeviceIOProcID?

    /// - Parameters:
    ///   - processes: the Core Audio process objects to tap.
    ///   - bundleIDs: on macOS 26 and later, bundle IDs to tap as well (also processes that start
    ///     later); nil for none.
    ///   - outputSubdevice: put the default output device in the aggregate device too (for its
    ///     clock), as usual; its input streams, if any, are skipped.
    init(processes: [AudioObjectID], bundleIDs: [String]?, mute: Bool, outputSubdevice: Bool,
         log: (String) -> Void) throws(HAL.Failure) {
        let description = CATapDescription(monoMixdownOfProcesses: processes)
        description.name = "Sakamoto Voice tap"
        description.uuid = UUID()
        description.isPrivate = true
        description.muteBehavior = mute ? .mutedWhenTapped : .unmuted
        if #available(macOS 26.0, *), let bundleIDs, !bundleIDs.isEmpty {
            description.bundleIDs = bundleIDs
            description.isProcessRestoreEnabled = true
        }
        self.description = description
        self.processes = processes

        var tapID = AudioObjectID(kAudioObjectUnknown)
        try HAL.check(AudioHardwareCreateProcessTap(description, &tapID), "creating the process tap")
        let format: AudioStreamBasicDescription
        do throws(HAL.Failure) {
            format = try HAL.value(tapID, kAudioTapPropertyFormat, default: AudioStreamBasicDescription())
            guard format.mFormatID == kAudioFormatLinearPCM, format.mFormatFlags & kAudioFormatFlagIsFloat != 0,
                  format.mBitsPerChannel == 32, format.mSampleRate > 0
            else {
                throw HAL.Failure(what: "the tap's format (\(format.mSampleRate) Hz, \(format.mBitsPerChannel) bits, flags \(format.mFormatFlags))",
                                  status: OSStatus(kAudioHardwareUnsupportedOperationError))
            }
        } catch {
            AudioHardwareDestroyProcessTap(tapID)
            throw error
        }
        self.tapID = tapID
        sampleRate = format.mSampleRate
        queue = SampleQueue(limit: Int(format.mSampleRate * 30))
        log("tap: \(format.mSampleRate) Hz, \(format.mChannelsPerFrame) channel(s), \(processes.count) process(es)")
        do throws(HAL.Failure) {
            var aggregate: [String: Any] = [
                kAudioAggregateDeviceNameKey: "Sakamoto Voice tap",
                kAudioAggregateDeviceUIDKey: UUID().uuidString,
                kAudioAggregateDeviceIsPrivateKey: true,
                kAudioAggregateDeviceIsStackedKey: false,
                kAudioAggregateDeviceTapAutoStartKey: true,
                kAudioAggregateDeviceTapListKey: [[kAudioSubTapDriftCompensationKey: true,
                                                   kAudioSubTapUIDKey: description.uuid.uuidString]],
            ]
            var skip = 0
            if outputSubdevice {
                let (device, uid) = try HAL.defaultOutputDevice()
                aggregate[kAudioAggregateDeviceMainSubDeviceKey] = uid
                aggregate[kAudioAggregateDeviceSubDeviceListKey] = [[kAudioSubDeviceUIDKey: uid]]
                skip = (try? HAL.objects(device, kAudioDevicePropertyStreams, scope: kAudioObjectPropertyScopeInput).count) ?? 0
                log("aggregate: with the output device \(uid) (\(skip) input stream(s) skipped)")
            }
            var aggregateID = AudioObjectID(kAudioObjectUnknown)
            try HAL.check(AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID),
                          "creating the aggregate device")
            self.aggregateID = aggregateID

            let queue = self.queue
            let ioQueue = DispatchQueue(label: "com.pragmaphilia.AppVoiceTap.io", qos: .userInteractive)
            var procID: AudioDeviceIOProcID?
            try HAL.check(AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, ioQueue) { _, input, _, _, _ in
                queue.append(input, skipping: skip)
            }, "creating the IO callback")
            self.procID = procID
        } catch {
            stop()
            throw error
        }
    }

    func start() throws(HAL.Failure) {
        try HAL.check(AudioDeviceStart(aggregateID, procID), "starting the aggregate device")
    }

    /// Taps this set of processes from now on (the Claude app may start a helper for its audio).
    func update(processes: [AudioObjectID]) throws(HAL.Failure) {
        guard Set(processes) != Set(self.processes) else { return }
        description.processes = processes
        var address = HAL.address(kAudioTapPropertyDescription)
        var reference: CATapDescription = description
        let status = withUnsafeMutablePointer(to: &reference) {
            AudioObjectSetPropertyData(tapID, &address, 0, nil, UInt32(MemoryLayout<CATapDescription>.size), $0)
        }
        try HAL.check(status, "updating the tap's processes")
        self.processes = processes
    }

    /// Stops and removes everything; safe to call more than once.
    func stop() {
        if aggregateID != kAudioObjectUnknown {
            if let procID {
                AudioDeviceStop(aggregateID, procID)
                AudioDeviceDestroyIOProcID(aggregateID, procID)
            }
            AudioHardwareDestroyAggregateDevice(aggregateID)
            aggregateID = AudioObjectID(kAudioObjectUnknown)
        }
        procID = nil
        if tapID != kAudioObjectUnknown {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = AudioObjectID(kAudioObjectUnknown)
        }
    }

    deinit { stop() }
}
