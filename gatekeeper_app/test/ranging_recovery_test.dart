import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/ranging_recovery.dart';

void main() {
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
