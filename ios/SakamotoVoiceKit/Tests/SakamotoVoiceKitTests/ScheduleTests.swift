import Foundation
import Testing
@testable import SakamotoVoiceKit

@Suite struct ScheduleTests {
    let calendar: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "Asia/Tokyo")!
        return c
    }()

    func date(_ hour: Int, _ minute: Int, day: Int = 12) -> Date {
        calendar.date(from: DateComponents(year: 2026, month: 10, day: day, hour: hour, minute: minute))!
    }

    @Test func daytimeSpan() {
        let s = DailySchedule(start: (7, 0), end: (23, 0))
        #expect(!s.contains(minuteOfDay: 6 * 60 + 59))
        #expect(s.contains(minuteOfDay: 7 * 60))
        #expect(s.contains(minuteOfDay: 12 * 60))
        #expect(s.contains(minuteOfDay: 22 * 60 + 59))
        #expect(!s.contains(minuteOfDay: 23 * 60))
        #expect(!s.contains(minuteOfDay: 0))
    }

    @Test func overnightSpan() {
        let s = DailySchedule(start: (22, 0), end: (7, 0))
        #expect(s.contains(minuteOfDay: 22 * 60))
        #expect(s.contains(minuteOfDay: 23 * 60 + 59))
        #expect(s.contains(minuteOfDay: 0))
        #expect(s.contains(minuteOfDay: 6 * 60 + 59))
        #expect(!s.contains(minuteOfDay: 7 * 60))
        #expect(!s.contains(minuteOfDay: 12 * 60))
    }

    @Test func equalStartAndEndIsAllDay() {
        let s = DailySchedule(start: (9, 0), end: (9, 0))
        for minute in stride(from: 0, to: 1440, by: 37) {
            #expect(s.contains(minuteOfDay: minute))
        }
        #expect(s.nextChange(after: date(10, 0), calendar: calendar) == nil)
    }

    @Test func minutesWrap() {
        let s = DailySchedule(startMinute: 1440 + 60, endMinute: -60)
        #expect(s.startMinute == 60)
        #expect(s.endMinute == 1380)
    }

    @Test func containsADate() {
        let s = DailySchedule(start: (7, 30), end: (23, 0))
        #expect(!s.contains(date(7, 29), calendar: calendar))
        #expect(s.contains(date(7, 30), calendar: calendar))
    }

    @Test func nextChange() {
        let s = DailySchedule(start: (7, 0), end: (23, 0))
        #expect(s.nextChange(after: date(6, 0), calendar: calendar) == date(7, 0))
        #expect(s.nextChange(after: date(7, 0), calendar: calendar) == date(23, 0))
        #expect(s.nextChange(after: date(12, 0), calendar: calendar) == date(23, 0))
        #expect(s.nextChange(after: date(23, 30), calendar: calendar) == date(7, 0, day: 13))
    }

    @Test func policy() {
        let s = DailySchedule(start: (7, 0), end: (23, 0))
        let off = KeepAlivePolicy(stayAwake: false, useSchedule: true, schedule: s)
        #expect(!off.isAwake(at: date(12, 0), calendar: calendar))
        let always = KeepAlivePolicy(stayAwake: true, useSchedule: false, schedule: s)
        #expect(always.isAwake(at: date(3, 0), calendar: calendar))
        let scheduled = KeepAlivePolicy(stayAwake: true, useSchedule: true, schedule: s)
        #expect(scheduled.isAwake(at: date(12, 0), calendar: calendar))
        #expect(!scheduled.isAwake(at: date(3, 0), calendar: calendar))
    }
}
