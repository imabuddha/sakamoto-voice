import Foundation
import Testing
@testable import SakamotoVoiceKit

@Suite struct PairingTests {
    @Test func generatedCodesAreSixDigits() {
        for _ in 0..<200 {
            let code = PairingCode.generate()
            #expect(code.count == 6)
            #expect(code.allSatisfy(\.isASCII) && code.allSatisfy(\.isNumber))
            #expect(PairingCode.isValid(code))
        }
    }

    @Test func generatedCodesVary() {
        #expect(Set((0..<50).map { _ in PairingCode.generate() }).count > 40)
    }

    @Test func normalizeAndDisplay() {
        #expect(PairingCode.normalize("123 456") == "123456")
        #expect(PairingCode.normalize("123-456\n") == "123456")
        #expect(PairingCode.display("123456") == "123 456")
        #expect(PairingCode.display("12") == "12")
    }

    @Test func validity() {
        #expect(PairingCode.isValid("123 456"))
        #expect(PairingCode.isValid("123-456"))
        #expect(!PairingCode.isValid("12345"))
        #expect(!PairingCode.isValid("1234567"))
        #expect(!PairingCode.isValid("12345a"))
        #expect(!PairingCode.isValid("１２３４５６"))   // full-width digits aren't typed on a Mac
    }

    @Test func matching() {
        #expect(PairingCode.matches("123456", expected: "123456"))
        #expect(PairingCode.matches("123 456", expected: "123456"))
        #expect(!PairingCode.matches("123457", expected: "123456"))
        #expect(!PairingCode.matches("12345", expected: "123456"))
        #expect(!PairingCode.matches("", expected: ""))
        #expect(!PairingCode.matches("123456", expected: ""))
    }

    @Test func gateAcceptsTheRightCode() {
        var gate = TokenGate()
        #expect(gate.check("123456", expected: "123456") == .accepted)
        #expect(gate.check("000000", expected: "123456") == .rejected)
        #expect(gate.check("123456", expected: "123456") == .accepted)
    }

    @Test func gateLocksOutAfterRepeatedGuesses() {
        var gate = TokenGate(maxFailures: 3, window: 60, lockout: 60)
        let t0 = Date(timeIntervalSinceReferenceDate: 0)
        #expect(gate.check("1", expected: "123456", now: t0) == .rejected)
        #expect(gate.check("2", expected: "123456", now: t0 + 1) == .rejected)
        #expect(gate.check("3", expected: "123456", now: t0 + 2) == .rejected)
        // Locked: even the right code is refused.
        #expect(gate.check("123456", expected: "123456", now: t0 + 10) == .lockedOut)
        #expect(gate.check("123456", expected: "123456", now: t0 + 61) == .lockedOut)
        // The lockout ends a minute after the third failure.
        #expect(gate.check("123456", expected: "123456", now: t0 + 63) == .accepted)
        #expect(gate.check("4", expected: "123456", now: t0 + 64) == .rejected)
    }

    @Test func oldFailuresAgeOut() {
        var gate = TokenGate(maxFailures: 3, window: 60, lockout: 60)
        let t0 = Date(timeIntervalSinceReferenceDate: 0)
        #expect(gate.check("1", expected: "123456", now: t0) == .rejected)
        #expect(gate.check("2", expected: "123456", now: t0 + 30) == .rejected)
        #expect(gate.check("3", expected: "123456", now: t0 + 70) == .rejected)  // the first aged out
        #expect(gate.check("123456", expected: "123456", now: t0 + 71) == .accepted)
    }
}
