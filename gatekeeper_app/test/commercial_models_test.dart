import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/commercial_models.dart';

void main() {
  test('door success requires durable Target success session', () {
    expect(doorStateFromNative({'state': 'RUNNING'}), DoorState.opening);
    expect(doorStateFromNative({'state': 'SUCCEEDED'}), DoorState.confirmed);
    expect(
        doorStateFromNative({'state': 'PROOF_UNCERTAIN'}), DoorState.unknown);
    expect(doorStateFromNative({'state': 'FAILED'}), DoorState.failed);
  });

  test('enrollment expiration is truthful', () {
    expect(enrollmentStateFromWire('approved', aclExpiresAtEpoch: 0),
        EnrollmentState.expired);
    expect(enrollmentStateFromWire('approved', aclExpiresAtEpoch: 4102444800),
        EnrollmentState.approved);
    expect(enrollmentStateFromWire('revoked'), EnrollmentState.revoked);
  });
}
