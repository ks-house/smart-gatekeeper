import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/ranging_recovery.dart';

void main() {
  test('projects structured native wake without claiming Target presence', () {
    final state = BleOwnershipState.fromMap(const <Object?, Object?>{
      'schemaVersion': 1,
      'mode': 'native_wake',
      'nativeRequested': true,
      'registrationRequested': true,
      'registrationReconciled': true,
      'registrationStatus': 'registered',
      'legacyLeaseHeld': false,
    });

    expect(state.mode, BleOwnershipMode.nativeWake);
    expect(state.nativeWakeAuthoritative, isTrue);
    expect(state.legacyLeaseHeld, isFalse);
  });

  test(
      'native request remains exclusive but is not operational without evidence',
      () {
    final state = BleOwnershipState.fromMap(const <Object?, Object?>{
      'mode': 'future_native_mode',
      'nativeRequested': true,
    });

    expect(state.mode, BleOwnershipMode.unknown);
    expect(state.nativeWakeAuthoritative, isFalse);
    expect(state.requiresNativeWakeReconciliation, isTrue);
    expect(state.legacyScannerAllowed, isFalse);
  });

  test('registered mode text cannot manufacture reconciliation evidence', () {
    final state = BleOwnershipState.fromMap(const <Object?, Object?>{
      'mode': 'native_wake',
      'nativeRequested': true,
      'registrationRequested': true,
      'registrationReconciled': false,
      'registrationStatus': 'scan_error',
    });

    expect(state.mode, BleOwnershipMode.nativeWake);
    expect(state.nativeWakeAuthoritative, isFalse);
    expect(state.requiresNativeWakeReconciliation, isTrue);
    expect(state.legacyScannerAllowed, isFalse);
  });

  test('projects reconciled registration timestamps without Target identity',
      () {
    final state = BleOwnershipState.fromMap(const <Object?, Object?>{
      'mode': 'native_wake',
      'nativeRequested': true,
      'registrationRequested': true,
      'registrationReconciled': true,
      'registrationStatus': 'registered',
      'registrationAttemptedAtEpochMs': 1000,
      'registrationReconciledAtEpochMs': 1100,
      'lastCallbackAtEpochMs': 1200,
    });

    expect(state.nativeWakeAuthoritative, isTrue);
    expect(state.registrationAttemptedAtEpochMs, 1000);
    expect(state.registrationReconciledAtEpochMs, 1100);
    expect(state.lastCallbackAtEpochMs, 1200);
  });

  test('legacy owner permits the legacy scanner path', () {
    final state = BleOwnershipState.fromMap(const <Object?, Object?>{
      'mode': 'legacy_scanner',
      'nativeRequested': false,
      'legacyLeaseHeld': true,
    });

    expect(state.mode, BleOwnershipMode.legacyScanner);
    expect(state.nativeWakeAuthoritative, isFalse);
    expect(state.legacyScannerAllowed, isTrue);
  });

  test('stale OS registration excludes legacy until native release completes',
      () {
    final state = BleOwnershipState.fromMap(const <Object?, Object?>{
      'mode': 'native_wake_recovery',
      'nativeRequested': false,
      'registrationRequested': true,
      'registrationReconciled': true,
      'registrationStatus': 'registered',
    });

    expect(state.nativeWakeAuthoritative, isFalse);
    expect(state.nativeExclusionRequired, isTrue);
    expect(state.legacyScannerAllowed, isFalse);
    expect(state.requiresNativeWakeReconciliation, isFalse);
    expect(state.requiresNativeWakeRelease, isTrue);
  });

  test('recognizes only the native GATT BLE ownership exclusion', () {
    expect(
      RangingRecoveryPolicy.isNativeGattOwnerExclusion(
        PlatformException(code: 'BLE_OWNER_EXCLUDED'),
      ),
      isTrue,
    );
    expect(
      RangingRecoveryPolicy.isNativeGattOwnerExclusion(
        PlatformException(code: 'OTHER_FAILURE'),
      ),
      isFalse,
    );
    expect(
      RangingRecoveryPolicy.isNativeGattOwnerExclusion(StateError('failure')),
      isFalse,
    );
  });

  test('uses a bounded lease delay and a slower generic error delay', () {
    final ownerError = PlatformException(code: 'BLE_OWNER_EXCLUDED');
    expect(
      RangingRecoveryPolicy.retryDelay(ownerError),
      RangingRecoveryPolicy.nativeGattLeaseRetryDelay,
    );
    expect(
      RangingRecoveryPolicy.retryDelay(StateError('failure')),
      RangingRecoveryPolicy.streamFailureRetryDelay,
    );
    expect(
      RangingRecoveryPolicy.nativeGattLeaseRetryDelay,
      greaterThan(Duration.zero),
    );
  });

  test('native wake reconciliation uses bounded exponential backoff', () {
    expect(
      NativeWakeReconciliationPolicy.retryDelay(1),
      const Duration(seconds: 30),
    );
    expect(
      NativeWakeReconciliationPolicy.retryDelay(2),
      const Duration(minutes: 1),
    );
    expect(
      NativeWakeReconciliationPolicy.retryDelay(3),
      const Duration(minutes: 2),
    );
    expect(
      NativeWakeReconciliationPolicy.retryDelay(100),
      NativeWakeReconciliationPolicy.maxRetryDelay,
    );
  });

  test('native wake reconciliation is single-flight and deadline gated', () {
    final now = DateTime.utc(2026, 9, 1, 1);
    expect(
      NativeWakeReconciliationPolicy.shouldAttempt(
        now: now,
        nextAttemptAt: null,
        inFlight: false,
        consecutiveFailures: 0,
      ),
      isTrue,
    );
    expect(
      NativeWakeReconciliationPolicy.shouldAttempt(
        now: now,
        nextAttemptAt: now.add(const Duration(seconds: 1)),
        inFlight: false,
        consecutiveFailures: 1,
      ),
      isFalse,
    );
    expect(
      NativeWakeReconciliationPolicy.shouldAttempt(
        now: now,
        nextAttemptAt: now.subtract(const Duration(seconds: 1)),
        inFlight: true,
        consecutiveFailures: 1,
      ),
      isFalse,
    );
    expect(
      NativeWakeReconciliationPolicy.shouldAttempt(
        now: now,
        nextAttemptAt: now.subtract(const Duration(seconds: 1)),
        inFlight: false,
        consecutiveFailures: NativeWakeReconciliationPolicy.maxAttempts,
      ),
      isFalse,
    );
  });

  test('surfaces real initialization failures but not a native GATT lease', () {
    expect(
      RangingRecoveryPolicy.shouldSurfaceAsUserError(
        PlatformException(code: 'BLE_OWNER_EXCLUDED'),
      ),
      isFalse,
    );
    expect(
      RangingRecoveryPolicy.shouldSurfaceAsUserError(
        PlatformException(code: 'BLUETOOTH_DISABLED'),
      ),
      isTrue,
    );
    expect(
      RangingRecoveryPolicy.shouldSurfaceAsUserError(
        StateError('scanner unavailable'),
      ),
      isTrue,
    );
  });

  test('coalesces repeated scheduling into one recovery', () async {
    final recovery = SingleFlightDelayedRecovery();
    final invoked = Completer<void>();
    var calls = 0;

    Future<void> callback() async {
      calls++;
      if (!invoked.isCompleted) invoked.complete();
    }

    recovery.schedule(Duration.zero, callback);
    recovery.schedule(Duration.zero, callback);
    recovery.schedule(Duration.zero, callback);
    await invoked.future.timeout(const Duration(seconds: 1));

    expect(calls, 1);
    expect(recovery.isScheduled, isFalse);
  });

  test('cancel prevents a pending recovery', () async {
    final recovery = SingleFlightDelayedRecovery();
    var calls = 0;
    recovery.schedule(const Duration(milliseconds: 20), () async {
      calls++;
    });
    expect(recovery.isScheduled, isTrue);

    recovery.cancel();
    await Future<void>.delayed(const Duration(milliseconds: 40));

    expect(calls, 0);
    expect(recovery.isScheduled, isFalse);
  });
}
