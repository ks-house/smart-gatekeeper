import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'mobile_identity_service.dart';
import 'native_gatt_worker_health.dart';

class SupportReportService {
  Future<String> build({
    required MobileIdentityStatus identity,
    required NativeGattWorkerHealth? health,
  }) async {
    final package = await PackageInfo.fromPlatform();
    final session = health?.lastSession;
    final rawSessionId = session?['id']?.toString();
    final eventRef = rawSessionId == null || rawSessionId.isEmpty
        ? null
        : sha256
            .convert(utf8.encode('support:$rawSessionId'))
            .toString()
            .substring(0, 16);
    final report = <String, Object?>{
      'schema': 'sgk-mobile-support-v1',
      'created_at': DateTime.now().toUtc().toIso8601String(),
      'app': <String, Object?>{
        'version': package.version,
        'build': package.buildNumber,
      },
      'identity': <String, Object?>{
        'enrollment_state': identity.enrollmentState.name,
        'access_ready': identity.accessReady,
        'door_count': identity.doorCount,
        'target_synced': identity.targetSynced,
        'acl_version': identity.aclVersion,
      },
      'native': <String, Object?>{
        'healthy': health?.healthy,
        'hands_free_ready': health?.handsFreeReady,
        'wake_registered': health?.wakeRegistered,
        'wake_registration_requested': health?.wakeRegistrationRequested,
        'wake_registration_reconciled': health?.wakeRegistrationReconciled,
        'wake_registration_status': health?.wakeRegistrationStatus,
        'wake_registration_attempted_at_epoch_ms':
            health?.wakeRegistrationAttemptedAtEpochMs,
        'wake_registration_reconciled_at_epoch_ms':
            health?.wakeRegistrationReconciledAtEpochMs,
        'wake_registration_last_callback_at_epoch_ms':
            health?.wakeRegistrationLastCallbackAtEpochMs,
        'stage': health?.detectionStage.name,
        'reason': health?.currentBlockingReasonCode ?? health?.lastReasonCode,
        'presence_to_dispatch_ms': health?.lastPresenceToDispatchMs,
        'presence_to_armed_ms': health?.lastPresenceToArmedMs,
        'event_ref': eventRef,
      },
    };
    return const JsonEncoder.withIndent('  ').convert(report);
  }
}
