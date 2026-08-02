import 'package:flutter/services.dart';

class NativeGattWorkerHealth {
  const NativeGattWorkerHealth({
    required this.featureEnabled,
    required this.featureStatus,
    required this.bleOwner,
    required this.healthy,
    required this.lastReasonCode,
    required this.lastLatencyMs,
    required this.updateManagerIndependent,
    required this.networkRequired,
  });

  final bool featureEnabled;
  final String featureStatus;
  final String bleOwner;
  final bool healthy;
  final String? lastReasonCode;
  final int? lastLatencyMs;
  final bool updateManagerIndependent;
  final bool networkRequired;

  factory NativeGattWorkerHealth.fromMap(Map<Object?, Object?> value) {
    return NativeGattWorkerHealth(
      featureEnabled: value['featureEnabled'] == true,
      featureStatus: value['featureStatus']?.toString() ?? 'unavailable',
      bleOwner: value['bleOwner']?.toString() ?? 'legacy',
      healthy: value['healthy'] != false,
      lastReasonCode: value['lastReasonCode']?.toString(),
      lastLatencyMs: (value['lastLatencyMs'] as num?)?.toInt(),
      updateManagerIndependent: value['updateManagerIndependent'] == true,
      networkRequired: value['networkRequired'] == true,
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
}
