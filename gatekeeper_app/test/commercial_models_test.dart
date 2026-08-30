import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/commercial_models.dart';

void main() {
  test('background session success means armed, not physical door confirmed',
      () {
    expect(doorStateFromNative({'state': 'QUEUED'}), DoorState.authorizing);
    expect(doorStateFromNative({'state': 'RUNNING'}), DoorState.authorizing);
    expect(
        doorStateFromNative({'state': 'RETRY_PENDING'}), DoorState.authorizing);
    expect(doorStateFromNative({'state': 'SUCCEEDED'}), DoorState.armed);
    expect(
        doorStateFromNative({'state': 'PROOF_UNCERTAIN'}), DoorState.unknown);
    expect(doorStateFromNative({'state': 'FAILED'}), DoorState.failed);
    for (final state in <String>[
      'QUEUED',
      'RUNNING',
      'RETRY_PENDING',
      'SUCCEEDED',
      'PROOF_UNCERTAIN',
      'FAILED',
      'DISABLED',
    ]) {
      expect(doorStateFromNative({'state': state}), isNot(DoorState.confirmed));
    }
  });

  test('manual open result separates command execution from proof uncertainty',
      () {
    final executed = ManualOpenOutcome.fromNative(<Object?, Object?>{
      'accepted': true,
      'reason': 'OPENED',
      'latencyMs': 1846,
      'sessionId': 'opaque-session',
    });
    final inconsistent = ManualOpenOutcome.fromNative(<Object?, Object?>{
      'accepted': true,
      'reason': 'RESULT_PENDING',
    });
    final uncertain = ManualOpenOutcome.fromNative(<Object?, Object?>{
      'accepted': false,
      'reason': 'PROOF_UNCERTAIN',
    });
    final failed = ManualOpenOutcome.fromNative(<Object?, Object?>{
      'accepted': false,
      'reason': 'TARGET_UNAVAILABLE',
    });

    expect(executed.state, ManualOpenState.commandExecuted);
    expect(executed.commandExecuted, isTrue);
    expect(executed.latencyMs, 1846);
    expect(inconsistent.state, ManualOpenState.outcomeUnknown);
    expect(uncertain.state, ManualOpenState.outcomeUnknown);
    expect(failed.state, ManualOpenState.failed);
  });

  test('enrollment expiration is truthful', () {
    expect(enrollmentStateFromWire('approved', aclExpiresAtEpoch: 0),
        EnrollmentState.expired);
    expect(enrollmentStateFromWire('approved', aclExpiresAtEpoch: 4102444800),
        EnrollmentState.approved);
    expect(enrollmentStateFromWire('ready_to_enroll'),
        EnrollmentState.readyToEnroll);
    expect(enrollmentStateFromWire('revoked'), EnrollmentState.revoked);
  });
}
