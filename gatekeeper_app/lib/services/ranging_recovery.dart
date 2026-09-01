import 'dart:async';

import 'package:flutter/services.dart';

enum BleOwnershipMode {
  legacyScanner,
  nativeWakeRecovery,
  nativeWake,
  unknown,
}

/// Privacy-safe projection of the cross-process BLE mode.
///
/// [nativeRequested] is only the fail-closed owner selection. It deliberately
/// prevents the legacy scanner from racing the native worker, but it is not
/// proof that Android accepted the PendingIntent scan. Normal native-wake idle
/// therefore requires the registrar's separate reconciliation evidence too.
class BleOwnershipState {
  const BleOwnershipState({
    required this.mode,
    required this.nativeRequested,
    required this.registrationRequested,
    required this.registrationReconciled,
    required this.registrationStatus,
    required this.legacyLeaseHeld,
    this.registrationAttemptedAtEpochMs,
    this.registrationReconciledAtEpochMs,
    this.lastCallbackAtEpochMs,
  });

  const BleOwnershipState.legacy()
      : mode = BleOwnershipMode.legacyScanner,
        nativeRequested = false,
        registrationRequested = false,
        registrationReconciled = false,
        registrationStatus = 'not_registered',
        legacyLeaseHeld = false,
        registrationAttemptedAtEpochMs = null,
        registrationReconciledAtEpochMs = null,
        lastCallbackAtEpochMs = null;

  const BleOwnershipState.unknown()
      : mode = BleOwnershipMode.unknown,
        nativeRequested = false,
        registrationRequested = false,
        registrationReconciled = false,
        registrationStatus = 'unavailable',
        legacyLeaseHeld = false,
        registrationAttemptedAtEpochMs = null,
        registrationReconciledAtEpochMs = null,
        lastCallbackAtEpochMs = null;

  final BleOwnershipMode mode;
  final bool nativeRequested;
  final bool registrationRequested;
  final bool registrationReconciled;
  final String registrationStatus;
  final bool legacyLeaseHeld;
  final int? registrationAttemptedAtEpochMs;
  final int? registrationReconciledAtEpochMs;
  final int? lastCallbackAtEpochMs;

  /// Legacy and native scanners must never run concurrently. A durable native
  /// request or a not-yet-released OS registration remains sufficient to
  /// exclude legacy even while reconciliation/teardown is pending.
  bool get nativeExclusionRequired => nativeRequested || registrationRequested;

  bool get legacyScannerAllowed => !nativeExclusionRequired;

  /// Truthful operational projection: a request marker or mode label alone is
  /// never enough to claim that OS-managed wake is ready.
  bool get nativeWakeAuthoritative =>
      nativeRequested && registrationRequested && registrationReconciled;

  bool get requiresNativeWakeReconciliation =>
      nativeRequested && !nativeWakeAuthoritative;

  bool get requiresNativeWakeRelease =>
      !nativeRequested && registrationRequested;

  factory BleOwnershipState.fromMap(Map<Object?, Object?> value) {
    final rawMode = value['mode']?.toString();
    final mode = switch (rawMode) {
      'legacy_scanner' => BleOwnershipMode.legacyScanner,
      'native_wake_recovery' => BleOwnershipMode.nativeWakeRecovery,
      'native_wake' => BleOwnershipMode.nativeWake,
      _ => BleOwnershipMode.unknown,
    };
    return BleOwnershipState(
      mode: mode,
      nativeRequested: value['nativeRequested'] == true,
      registrationRequested: value['registrationRequested'] == true,
      registrationReconciled: value['registrationReconciled'] == true,
      registrationStatus:
          value['registrationStatus']?.toString() ?? 'unavailable',
      legacyLeaseHeld: value['legacyLeaseHeld'] == true,
      registrationAttemptedAtEpochMs:
          (value['registrationAttemptedAtEpochMs'] as num?)?.toInt(),
      registrationReconciledAtEpochMs:
          (value['registrationReconciledAtEpochMs'] as num?)?.toInt(),
      lastCallbackAtEpochMs: (value['lastCallbackAtEpochMs'] as num?)?.toInt(),
    );
  }
}

/// Bounded retry cadence for native registration reconciliation. The scanner
/// watchdog owns scheduling, so this policy never creates an independent timer
/// and cannot dispatch GATT action-1 work.
class NativeWakeReconciliationPolicy {
  static const int maxAttempts = 3;
  static const Duration firstRetryDelay = Duration(seconds: 30);
  static const Duration maxRetryDelay = Duration(minutes: 5);

  static Duration retryDelay(int consecutiveFailures) {
    if (consecutiveFailures <= 0) return Duration.zero;
    final exponent = (consecutiveFailures - 1).clamp(0, 4);
    final seconds = firstRetryDelay.inSeconds * (1 << exponent);
    return Duration(
      seconds: seconds.clamp(
        firstRetryDelay.inSeconds,
        maxRetryDelay.inSeconds,
      ),
    );
  }

  static bool shouldAttempt({
    required DateTime now,
    required DateTime? nextAttemptAt,
    required bool inFlight,
    required int consecutiveFailures,
  }) =>
      !inFlight &&
      consecutiveFailures < maxAttempts &&
      (nextAttemptAt == null || !now.isBefore(nextAttemptAt));
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
