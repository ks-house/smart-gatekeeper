import 'dart:async';

import 'package:flutter/services.dart';

enum BleOwnershipMode { legacyScanner, nativeWake, unknown }

/// Privacy-safe projection of the cross-process BLE mode. A native request
/// means OS PendingIntent wake is authoritative; it does not mean a Target is
/// present or a GATT connection is active.
class BleOwnershipState {
  const BleOwnershipState({
    required this.mode,
    required this.nativeRequested,
    required this.legacyLeaseHeld,
  });

  const BleOwnershipState.legacy()
      : mode = BleOwnershipMode.legacyScanner,
        nativeRequested = false,
        legacyLeaseHeld = false;

  const BleOwnershipState.unknown()
      : mode = BleOwnershipMode.unknown,
        nativeRequested = false,
        legacyLeaseHeld = false;

  final BleOwnershipMode mode;
  final bool nativeRequested;
  final bool legacyLeaseHeld;

  bool get nativeWakeAuthoritative =>
      nativeRequested || mode == BleOwnershipMode.nativeWake;

  factory BleOwnershipState.fromMap(Map<Object?, Object?> value) {
    final rawMode = value['mode']?.toString();
    final mode = switch (rawMode) {
      'legacy_scanner' => BleOwnershipMode.legacyScanner,
      'native_wake' => BleOwnershipMode.nativeWake,
      _ => BleOwnershipMode.unknown,
    };
    return BleOwnershipState(
      mode: mode,
      nativeRequested: value['nativeRequested'] == true,
      legacyLeaseHeld: value['legacyLeaseHeld'] == true,
    );
  }
}

/// Recovery policy for a Flutter ranging stream that temporarily loses BLE
/// ownership to the native credential worker.
class RangingRecoveryPolicy {
  static const String nativeGattOwnerExcluded = 'BLE_OWNER_EXCLUDED';
  static const Duration nativeGattLeaseRetryDelay = Duration(seconds: 1);
  static const Duration streamFailureRetryDelay = Duration(seconds: 2);

  static bool isNativeGattOwnerExclusion(Object error) =>
      error is PlatformException && error.code == nativeGattOwnerExcluded;

  /// Native GATT and Flutter scanning intentionally share one BLE owner. The
  /// native credential lease is a temporary transition, not a user-visible
  /// scanner failure; every other initialization failure remains actionable.
  static bool shouldSurfaceAsUserError(Object error) =>
      !isNativeGattOwnerExclusion(error);

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
