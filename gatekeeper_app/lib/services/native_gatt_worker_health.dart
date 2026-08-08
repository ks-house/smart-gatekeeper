import 'package:flutter/services.dart';

class NativeGattWorkerHealth {
  const NativeGattWorkerHealth({
    required this.featureEnabled,
    required this.featureStatus,
    required this.bleOwner,
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
    this.lastSession,
  });

  final bool featureEnabled;
  final String featureStatus;
  final String bleOwner;
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
  final Map<Object?, Object?>? lastSession;

  factory NativeGattWorkerHealth.fromMap(Map<Object?, Object?> value) {
    return NativeGattWorkerHealth(
      featureEnabled: value['featureEnabled'] == true,
      featureStatus: value['featureStatus']?.toString() ?? 'unavailable',
      bleOwner: value['bleOwner']?.toString() ?? 'legacy',
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
      lastSession: (value['lastSession'] as Map?)?.cast<Object?, Object?>(),
    );
  }
}

/// Read-only native bridge. It cannot toggle ownership, mutate credentials, or access keys.
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
}
