import Foundation

/// A daily span of time, by minutes after midnight. An end before the start wraps past midnight
/// (22:00 to 07:00); a start equal to the end is the whole day.
public struct DailySchedule: Codable, Equatable, Sendable {
    public static let minutesPerDay = 24 * 60

    public var startMinute: Int
    public var endMinute: Int

    public init(startMinute: Int, endMinute: Int) {
        self.startMinute = Self.wrap(startMinute)
        self.endMinute = Self.wrap(endMinute)
    }

    public init(start: (hour: Int, minute: Int), end: (hour: Int, minute: Int)) {
        self.init(startMinute: start.hour * 60 + start.minute, endMinute: end.hour * 60 + end.minute)
    }

    static func wrap(_ minute: Int) -> Int {
        ((minute % minutesPerDay) + minutesPerDay) % minutesPerDay
    }

    public static func minuteOfDay(_ date: Date, calendar: Calendar) -> Int {
        let parts = calendar.dateComponents([.hour, .minute], from: date)
        return (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
    }

    public func contains(minuteOfDay minute: Int) -> Bool {
        let m = Self.wrap(minute)
        if startMinute == endMinute { return true }
        if startMinute < endMinute { return m >= startMinute && m < endMinute }
        return m >= startMinute || m < endMinute
    }

    public func contains(_ date: Date, calendar: Calendar = .current) -> Bool {
        contains(minuteOfDay: Self.minuteOfDay(date, calendar: calendar))
    }

    /// The next start or end after `date`; nil for a whole-day schedule, which never changes.
    public func nextChange(after date: Date, calendar: Calendar = .current) -> Date? {
        guard startMinute != endMinute else { return nil }
        return [startMinute, endMinute].compactMap { minute in
            calendar.nextDate(after: date,
                              matching: DateComponents(hour: minute / 60, minute: minute % 60, second: 0),
                              matchingPolicy: .nextTime)
        }.min()
    }
}

/// Whether the app keeps itself running in the background (the silent keep-alive sound): when
/// "Stay awake" is on, and, with the schedule on, only inside its hours.
public struct KeepAlivePolicy: Equatable, Sendable {
    public var stayAwake: Bool
    public var useSchedule: Bool
    public var schedule: DailySchedule

    public init(stayAwake: Bool, useSchedule: Bool, schedule: DailySchedule) {
        self.stayAwake = stayAwake
        self.useSchedule = useSchedule
        self.schedule = schedule
    }

    public func isAwake(at date: Date, calendar: Calendar = .current) -> Bool {
        guard stayAwake else { return false }
        return !useSchedule || schedule.contains(date, calendar: calendar)
    }
}
