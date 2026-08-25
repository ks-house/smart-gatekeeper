import 'package:flutter/services.dart';

class NativeGattWorkerHealth {
  const NativeGattWorkerHealth({
    required this.featureEnabled,
    required this.featureStatus,
    required this.bleOwner,
    required this.localBootstrapAllowed,
    required this.credentialProvisioned,
    required this.localConsentValid,
    required this.healthy,
    required this.lastReasonCode,
    required this.lastTargetReasonCode,
    required this.lastTargetReasonName,
    required this.lastTransportReason,
    required this.lastRetryAfterMs,
    required this.lastScheduledRetryDelayMs,
    required this.lastLatencyMs,
    required this.updateManagerIndependent,
    required this.networkRequired,
    this.handsFreeReady = false,
    this.wakeRegistered = false,
    this.wakeRegistrationStatus = 'not_registered',
    this.initialWorkExpedited = false,
    this.maxPresenceAgeMs,
    this.lastPresenceToDispatchMs,
    this.lastPresenceToArmedMs,
    this.lastSession,
  });

  final bool featureEnabled;
  final String featureStatus;
  final String bleOwner;
  final bool localBootstrapAllowed;
  final bool credentialProvisioned;
  final bool localConsentValid;
  final bool healthy;
  final String? lastReasonCode;
  final int? lastTargetReasonCode;
  final String? lastTargetReasonName;
  final String? lastTransportReason;
  final int? lastRetryAfterMs;
  final int? lastScheduledRetryDelayMs;
  final int? lastLatencyMs;
  final bool updateManagerIndependent;
  final bool networkRequired;
  final bool handsFreeReady;
  final bool wakeRegistered;
  final String wakeRegistrationStatus;
  final bool initialWorkExpedited;
  final int? maxPresenceAgeMs;
  final int? lastPresenceToDispatchMs;
  final int? lastPresenceToArmedMs;
  final Map<Object?, Object?>? lastSession;

  factory NativeGattWorkerHealth.fromMap(Map<Object?, Object?> value) {
    return NativeGattWorkerHealth(
      featureEnabled: value['featureEnabled'] == true,
      featureStatus: value['featureStatus']?.toString() ?? 'unavailable',
      bleOwner: value['bleOwner']?.toString() ?? 'legacy',
      localBootstrapAllowed: value['localBootstrapAllowed'] == true,
      credentialProvisioned: value['credentialProvisioned'] == true,
      localConsentValid: value['localConsentValid'] == true,
      healthy: value['healthy'] != false,
      lastReasonCode: value['lastReasonCode']?.toString(),
      lastTargetReasonCode: (value['lastTargetReasonCode'] as num?)?.toInt(),
      lastTargetReasonName: value['lastTargetReasonName']?.toString(),
      lastTransportReason: value['lastTransportReason']?.toString(),
      lastRetryAfterMs: (value['lastRetryAfterMs'] as num?)?.toInt(),
      lastScheduledRetryDelayMs:
          (value['lastScheduledRetryDelayMs'] as num?)?.toInt(),
      lastLatencyMs: (value['lastLatencyMs'] as num?)?.toInt(),
      updateManagerIndependent: value['updateManagerIndependent'] == true,
      networkRequired: value['networkRequired'] == true,
      handsFreeReady: value['handsFreeReady'] == true,
      wakeRegistered: value['wakeRegistered'] == true,
      wakeRegistrationStatus:
          value['wakeRegistrationStatus']?.toString() ?? 'not_registered',
      initialWorkExpedited: value['initialWorkExpedited'] == true,
      maxPresenceAgeMs: (value['maxPresenceAgeMs'] as num?)?.toInt(),
      lastPresenceToDispatchMs:
          (value['lastPresenceToDispatchMs'] as num?)?.toInt(),
      lastPresenceToArmedMs:
          (value['lastPresenceToArmedMs'] as num?)?.toInt(),
      lastSession: (value['lastSession'] as Map?)?.cast<Object?, Object?>(),
    );
  }
}

/// Native GATT control bridge. It exposes no private key or raw peer locator.
class NativeGattWorkerHealthBridge {
  static const MethodChannel _channel = MethodChannel(
    'com.kshouse.gatekeeper_app/ble_gatt_worker_health',
  );

  Future<NativeGattWorkerHealth> read() async {
    final raw = await _channel.invokeMethod<Map<Object?, Object?>>('getHealth');
    return NativeGattWorkerHealth.fromMap(raw ?? const <Object?, Object?>{});
  }

  Future<Map<Object?, Object?>> triggerLocalGattRetry() async {
    try {
      final res = await _channel
          .invokeMethod<Map<Object?, Object?>>('triggerLocalGattRetry');
      return res ??
          const <Object?, Object?>{
            'accepted': false,
            'reason': 'NATIVE_UNAVAILABLE'
          };
    } catch (_) {
      return const <Object?, Object?>{
        'accepted': false,
        'reason': 'NATIVE_UNAVAILABLE'
      };
    }
  }

  /// Executes manual open immediately and completes only after the Target
  /// returns a terminal authenticated result.
  Future<Map<Object?, Object?>> triggerLocalGattOpen() async {
    try {
      final res = await _channel
          .invokeMethod<Map<Object?, Object?>>('triggerLocalGattOpen');
      return res ??
          const <Object?, Object?>{
            'accepted': false,
            'reason': 'NATIVE_UNAVAILABLE'
          };
    } catch (_) {
      return const <Object?, Object?>{
        'accepted': false,
        'reason': 'NATIVE_UNAVAILABLE'
      };
    }
  }

  Future<Map<Object?, Object?>> setLocalGattEnabled(bool enabled) async {
    try {
      final res = await _channel.invokeMethod<Map<Object?, Object?>>(
        'setLocalGattEnabled',
        <String, Object?>{'enabled': enabled},
      );
      return res ??
          const <Object?, Object?>{
            'accepted': false,
            'reason': 'NATIVE_UNAVAILABLE'
          };
    } catch (_) {
      return const <Object?, Object?>{
        'accepted': false,
        'reason': 'NATIVE_UNAVAILABLE'
      };
    }
  }

  Future<Map<Object?, Object?>> prepareLocalGattEnrollment() async {
    try {
      final res = await _channel.invokeMethod<Map<Object?, Object?>>(
        'prepareLocalGattEnrollment',
      );
      return res ??
          const <Object?, Object?>{
            'accepted': false,
            'reason': 'NATIVE_UNAVAILABLE'
          };
    } catch (_) {
      return const <Object?, Object?>{
        'accepted': false,
        'reason': 'NATIVE_UNAVAILABLE'
      };
    }
  }
}
