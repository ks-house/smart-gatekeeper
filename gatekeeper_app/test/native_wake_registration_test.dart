import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/native_wake_registration.dart';

void main() {
  test('requires explicit reconciliation instead of trusting registered alias',
      () {
    final registration = NativeWakeRegistration.fromMap(
      const <Object?, Object?>{
        'status': 'registered',
        'requested': true,
        'reconciled': false,
        'registered': true,
        'nextAction': 'retry',
      },
    );

    expect(registration.status, NativeWakeStatus.reconciling);
    expect(registration.requested, isTrue);
    expect(registration.reconciled, isFalse);
    expect(registration.registered, isFalse);
  });

  test('accepts current successful reconciliation with privacy-safe times', () {
    final registration = NativeWakeRegistration.fromMap(
      const <Object?, Object?>{
        'status': 'registered',
        'requested': true,
        'reconciled': true,
        'registered': true,
        'attemptedAtEpochMs': 1000,
        'reconciledAtEpochMs': 1100,
        'lastCallbackAtEpochMs': 1200,
        'nextAction': 'none',
      },
    );

    expect(registration.status, NativeWakeStatus.registered);
    expect(registration.registered, isTrue);
    expect(registration.attemptedAtEpochMs, 1000);
    expect(registration.reconciledAtEpochMs, 1100);
    expect(registration.lastCallbackAtEpochMs, 1200);
  });

  test('keeps failed requested registration visible as blocked or reconciling',
      () {
    final blocked = NativeWakeRegistration.fromMap(
      const <Object?, Object?>{
        'status': 'missing_permission:android.permission.BLUETOOTH_SCAN',
        'requested': true,
        'reconciled': false,
      },
    );
    final retrying = NativeWakeRegistration.fromMap(
      const <Object?, Object?>{
        'status': 'scan_error',
        'requested': true,
        'reconciled': false,
      },
    );

    expect(blocked.status, NativeWakeStatus.blocked);
    expect(blocked.registered, isFalse);
    expect(retrying.status, NativeWakeStatus.reconciling);
    expect(retrying.registered, isFalse);
  });
}
