import 'package:flutter/services.dart';

enum TargetDetectionStage {
  waiting,
  detected,
  authenticating,
  armed,
  failed,
  disabled,
}

class TargetDetectionSummary {
  const TargetDetectionSummary({
    required this.source,
    required this.success,
    required this.receivedEpochMs,
    required this.screenInteractive,
    required this.resultCount,
    required this.errorCode,
    this.callbackLatencyMs,
    this.strongestRssi,
  });

  final String source;
  final bool success;
  final int receivedEpochMs;
  final double? callbackLatencyMs;
  final int? strongestRssi;
  final bool screenInteractive;
  final int resultCount;
  final int errorCode;

  DateTime get receivedAt =>
      DateTime.fromMillisecondsSinceEpoch(receivedEpochMs);

  factory TargetDetectionSummary.fromMap(Map<Object?, Object?> value) {
    return TargetDetectionSummary(
      source: value['source']?.toString() ?? 'unknown',
      success: value['success'] == true,
      receivedEpochMs: (value['receivedEpochMs'] as num?)?.toInt() ?? 0,
      callbackLatencyMs: (value['callbackLatencyMs'] as num?)?.toDouble(),
      strongestRssi: (value['strongestRssi'] as num?)?.toInt(),
      screenInteractive: value['screenInteractive'] != false,
      resultCount: (value['resultCount'] as num?)?.toInt() ?? 0,
      errorCode: (value['errorCode'] as num?)?.toInt() ?? 0,
    );
  }
}

class GattPerformanceSummary {
  const GattPerformanceSummary({
    this.connectSetupMs,
    this.negotiationMs,
    this.challengeMs,
    this.signingMs,
    this.proofWriteMs,
    this.resultWaitMs,
    required this.negotiatedMtu,
    required this.mtuStatus,
    required this.highPriorityRequested,
  });

  final int? connectSetupMs;
  final int? negotiationMs;
  final int? challengeMs;
  final int? signingMs;
  final int? proofWriteMs;
  final int? resultWaitMs;
  final int negotiatedMtu;
  final String mtuStatus;
  final bool highPriorityRequested;

  factory GattPerformanceSummary.fromMap(Map<Object?, Object?> value) {
    return GattPerformanceSummary(
      connectSetupMs: (value['connectSetupMs'] as num?)?.toInt(),
      negotiationMs: (value['negotiationMs'] as num?)?.toInt(),
      challengeMs: (value['challengeMs'] as num?)?.toInt(),
      signingMs: (value['signingMs'] as num?)?.toInt(),
      proofWriteMs: (value['proofWriteMs'] as num?)?.toInt(),
      resultWaitMs: (value['resultWaitMs'] as num?)?.toInt(),
      negotiatedMtu: (value['negotiatedMtu'] as num?)?.toInt() ?? 23,
      mtuStatus: value['mtuStatus']?.toString() ?? 'NOT_REQUESTED',
      highPriorityRequested: value['highPriorityRequested'] == true,
    );
  }
}

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
    this.lastActiveAclVersion,
    this.latestDetection,
    this.lastSession,
    this.lastGattPerformance,
    this.currentBlockingReasonCode,
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
  final int? lastActiveAclVersion;
  final TargetDetectionSummary? latestDetection;
  final Map<Object?, Object?>? lastSession;
  final GattPerformanceSummary? lastGattPerformance;
  final String? currentBlockingReasonCode;

  bool get credentialRegistered => credentialProvisioned && localConsentValid;

  bool get targetAclConfirmed =>
      credentialRegistered &&
      lastActiveAclVersion != null &&
      lastActiveAclVersion! > 0;

  TargetDetectionStage get detectionStage => detectionStageAt(DateTime.now());

  TargetDetectionStage detectionStageAt(DateTime now) {
    final detection = latestDetection;
    if (detection == null) return TargetDetectionStage.waiting;
    final ageMs = now.millisecondsSinceEpoch - detection.receivedEpochMs;
    final freshnessMs = maxPresenceAgeMs ?? 45000;
    if (ageMs > freshnessMs) return TargetDetectionStage.waiting;
    if (!detection.success) return TargetDetectionStage.failed;

    final session = lastSession;
    if (session == null) return TargetDetectionStage.detected;
    final updatedEpochMs = (session['updatedEpochMs'] as num?)?.toInt();
    if (updatedEpochMs == null || updatedEpochMs < detection.receivedEpochMs) {
      return TargetDetectionStage.detected;
    }
    switch (session['state']?.toString()) {
      case 'QUEUED':
      case 'RUNNING':
      case 'RETRY_PENDING':
        return TargetDetectionStage.authenticating;
      case 'SUCCEEDED':
        return lastPresenceToArmedMs != null
            ? TargetDetectionStage.armed
            : TargetDetectionStage.detected;
      case 'DISABLED':
        return TargetDetectionStage.disabled;
      case 'FAILED':
      case 'PROOF_UNCERTAIN':
        return TargetDetectionStage.failed;
      default:
        return TargetDetectionStage.detected;
    }
  }

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
      lastPresenceToArmedMs: (value['lastPresenceToArmedMs'] as num?)?.toInt(),
      lastActiveAclVersion: (value['lastActiveAclVersion'] as num?)?.toInt(),
      latestDetection: value['latestDetection'] is Map
          ? TargetDetectionSummary.fromMap(
              (value['latestDetection'] as Map).cast<Object?, Object?>(),
            )
          : null,
      lastSession: (value['lastSession'] as Map?)?.cast<Object?, Object?>(),
      lastGattPerformance: value['lastGattPerformance'] is Map
          ? GattPerformanceSummary.fromMap(
              (value['lastGattPerformance'] as Map).cast<Object?, Object?>(),
            )
          : null,
      currentBlockingReasonCode:
          value['currentBlockingReasonCode']?.toString(),
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
