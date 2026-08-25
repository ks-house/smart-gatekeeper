import 'dart:async';

import 'package:flutter/services.dart';

/// Recovery policy for a Flutter ranging stream that temporarily loses BLE
/// ownership to the native credential worker.
class RangingRecoveryPolicy {
  static const String nativeGattOwnerExcluded = 'BLE_OWNER_EXCLUDED';
  static const Duration nativeGattLeaseRetryDelay = Duration(seconds: 1);
  static const Duration streamFailureRetryDelay = Duration(seconds: 2);

  static bool isNativeGattOwnerExclusion(Object error) =>
      error is PlatformException && error.code == nativeGattOwnerExcluded;

  static Duration retryDelay(Object error) => isNativeGattOwnerExclusion(error)
      ? nativeGattLeaseRetryDelay
      : streamFailureRetryDelay;
}

/// Coalesces repeated stream errors into one delayed recovery attempt.
class SingleFlightDelayedRecovery {
  Timer? _timer;

  bool get isScheduled => _timer != null;

  void schedule(
    Duration delay,
    Future<void> Function() recovery,
  ) {
    if (_timer != null) return;
    _timer = Timer(delay, () async {
      _timer = null;
      await recovery();
    });
  }

  void cancel() {
    _timer?.cancel();
    _timer = null;
  }
}
