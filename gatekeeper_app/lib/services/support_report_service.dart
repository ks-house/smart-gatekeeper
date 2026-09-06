import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'mobile_identity_service.dart';
import 'native_gatt_worker_health.dart';
import 'field_diagnostics_service.dart';

class SupportReportService {
  SupportReportService({
    NativeGattWorkerHealthBridge? nativeBridge,
    FieldDiagnosticsStore? diagnosticsStore,
  })  : _native = nativeBridge ?? NativeGattWorkerHealthBridge(),
        _diagnosticsStore = diagnosticsStore ?? FieldDiagnosticsStore();

  final NativeGattWorkerHealthBridge _native;
  final FieldDiagnosticsStore _diagnosticsStore;

  Future<Map<String, Object?>> buildMap({
    required MobileIdentityStatus identity,
    required NativeGattWorkerHealth? health,
    bool fullHistory = true,
  }) async {
    final package = await PackageInfo.fromPlatform();
    var currentHealth = health;
    try {
      currentHealth = await _native.read();
    } catch (_) {
      // Preserve the caller's last snapshot if the native bridge is unavailable.
    }
    Map<Object?, Object?> recent = const <Object?, Object?>{};
    try {
      recent = await _native.readRecentDiagnostics();
    } catch (_) {}
    FieldTestMarker? marker;
    try {
      marker = await _diagnosticsStore.readMarker();
    } catch (_) {}
    final since = await _diagnosticsStore.reportSinceEpochMs();
    final sessions = _safeSessions(recent['sessions'])
        .where((item) => (item['updated_epoch_ms'] as int? ?? 0) > since)
        .toList()
      ..sort((a, b) => (b['updated_epoch_ms'] as int? ?? 0)
          .compareTo(a['updated_epoch_ms'] as int? ?? 0));
    final wakeEvents = _safeWakeEvents(recent['wakeEvents'])
        .where((item) => (item['received_epoch_ms'] as int? ?? 0) > since)
        .toList()
      ..sort((a, b) => (b['received_epoch_ms'] as int? ?? 0)
          .compareTo(a['received_epoch_ms'] as int? ?? 0));
    final core = <String, Object?>{
      'app': <String, Object?>{
        'version': package.version,
        'build': package.buildNumber,
        'android_sdk': _safeInt(recent['androidSdk']),
      },
      'identity': <String, Object?>{
        'enrollment_state': identity.enrollmentState.name,
        'access_ready': identity.accessReady,
        'door_count': identity.doorCount,
        'target_synced': identity.targetSynced,
        'acl_version': identity.aclVersion,
      },
      'native': <String, Object?>{
        'healthy': currentHealth?.healthy,
        'hands_free_ready': currentHealth?.handsFreeReady,
        'wake_registered': currentHealth?.wakeRegistered,
        'wake_registration_requested': currentHealth?.wakeRegistrationRequested,
        'wake_registration_reconciled':
            currentHealth?.wakeRegistrationReconciled,
        'wake_registration_status': currentHealth?.wakeRegistrationStatus,
        'wake_registration_attempted_at_epoch_ms':
            currentHealth?.wakeRegistrationAttemptedAtEpochMs,
        'wake_registration_reconciled_at_epoch_ms':
            currentHealth?.wakeRegistrationReconciledAtEpochMs,
        'wake_registration_last_callback_at_epoch_ms':
            currentHealth?.wakeRegistrationLastCallbackAtEpochMs,
        'initial_work_expedited': currentHealth?.initialWorkExpedited,
        'stage': currentHealth?.detectionStage.name,
        'reason': _safeCode(
          currentHealth?.currentBlockingReasonCode ??
              currentHealth?.lastReasonCode,
        ),
        'presence_to_dispatch_ms': currentHealth?.lastPresenceToDispatchMs,
        'presence_to_armed_ms': currentHealth?.lastPresenceToArmedMs,
      },
      'field_test': marker == null
          ? null
          : <String, Object?>{
              ...marker.toJson(),
              'active': marker.isActiveAt(DateTime.now().toUtc()),
            },
      'sessions': sessions.take(fullHistory ? 50 : 10).toList(),
      'wake_events': wakeEvents.take(fullHistory ? 100 : 20).toList(),
    };
    final bundleRef = sha256
        .convert(utf8.encode(jsonEncode(core)))
        .toString()
        .substring(0, 32);
    return <String, Object?>{
      'schema': 'sgk-mobile-support-v2',
      'bundle_ref': bundleRef,
      'created_at': DateTime.now().toUtc().toIso8601String(),
      ...core,
    };
  }

  Future<String> build({
    required MobileIdentityStatus identity,
    required NativeGattWorkerHealth? health,
    bool fullHistory = false,
  }) async {
    return const JsonEncoder.withIndent(' ').convert(
      await buildMap(
          identity: identity, health: health, fullHistory: fullHistory),
    );
  }

  Future<void> clearHistory() => _diagnosticsStore.clearReportHistory();

  List<Map<String, Object?>> _safeSessions(Object? raw) {
    if (raw is! List) return const [];
    return raw.whereType<Map>().take(50).map((item) {
      final rawSessionId = item['sessionId']?.toString() ?? '';
      final targetSessionId = item['targetSessionId']?.toString().toLowerCase();
      final performance = item['gattPerformance'];
      return <String, Object?>{
        'event_ref': rawSessionId.isEmpty
            ? null
            : sha256
                .convert(utf8.encode('support:$rawSessionId'))
                .toString()
                .substring(0, 16),
        'created_epoch_ms': _safeInt(item['createdEpochMs']),
        'updated_epoch_ms': _safeInt(item['updatedEpochMs']),
        'attempt': _safeInt(item['attempt']),
        'state': _safeCode(item['state']),
        'reason_code': _safeCode(item['reasonCode']),
        'target_reason_code': _safeInt(item['targetReasonCode']),
        'target_reason_name': _safeCode(item['targetReasonName']),
        'transport_reason': _safeCode(item['transportReason']),
        'transport_status': _safeInt(item['transportStatus']),
        'retry_after_ms': _safeInt(item['retryAfterMs']),
        'scheduled_retry_delay_ms': _safeInt(item['scheduledRetryDelayMs']),
        'latency_ms': _safeInt(item['latencyMs']),
        'dispatch_started_epoch_ms': _safeInt(item['dispatchStartedEpochMs']),
        'presence_to_dispatch_ms': _safeInt(item['presenceToDispatchMs']),
        'presence_to_armed_ms': _safeInt(item['presenceToArmedMs']),
        'active_acl_version': _safeInt(item['activeAclVersion']),
        'target_session_id': targetSessionId != null &&
                isCanonicalTargetSessionId(targetSessionId)
            ? targetSessionId
            : null,
        'gatt_performance': performance is Map
            ? <String, Object?>{
                'connect_setup_ms': _safeInt(performance['connectSetupMs']),
                'negotiation_ms': _safeInt(performance['negotiationMs']),
                'challenge_ms': _safeInt(performance['challengeMs']),
                'signing_ms': _safeInt(performance['signingMs']),
                'proof_write_ms': _safeInt(performance['proofWriteMs']),
                'result_wait_ms': _safeInt(performance['resultWaitMs']),
                'negotiated_mtu': _safeInt(performance['negotiatedMtu']),
                'mtu_status': _safeCode(performance['mtuStatus']),
                'high_priority_requested':
                    performance['highPriorityRequested'] == true,
              }
            : null,
      };
    }).toList(growable: false);
  }

  List<Map<String, Object?>> _safeWakeEvents(Object? raw) {
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .take(100)
        .map((item) => <String, Object?>{
              'source': _safeCode(item['source']),
              'process_ref': _safeOpaqueRef(item['processRef'], 16),
              'success': item['success'] == true,
              'received_epoch_ms': _safeInt(item['receivedEpochMs']),
              'received_elapsed_ms': _safeInt(item['receivedElapsedMs']),
              'callback_latency_ms': _safeNum(item['callbackLatencyMs']),
              'strongest_rssi': _safeInt(item['strongestRssi']),
              'screen_interactive': item['screenInteractive'] != false,
              'result_count': _safeInt(item['resultCount']),
              'callback_type': _safeInt(item['callbackType']),
              'error_code': _safeInt(item['errorCode']),
            })
        .toList(growable: false);
  }

  int? _safeInt(Object? value) => value is num ? value.toInt() : null;
  num? _safeNum(Object? value) => value is num && value.isFinite ? value : null;

  String? _safeCode(Object? value) {
    final text = value?.toString().toUpperCase();
    if (text == null || !RegExp(r'^[A-Z0-9_-]{1,64}$').hasMatch(text)) {
      return null;
    }
    return text;
  }

  String? _safeOpaqueRef(Object? value, int length) {
    final text = value?.toString().toLowerCase();
    if (text == null || !RegExp('^[0-9a-f]{$length}\$').hasMatch(text)) {
      return null;
    }
    return text;
  }
}
