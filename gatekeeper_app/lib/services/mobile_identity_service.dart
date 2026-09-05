import 'dart:convert';

import 'package:http/http.dart' as http;

import 'commercial_models.dart';
import 'device_id_service.dart';
import 'native_gatt_worker_health.dart';

class MobileIdentityStatus {
  const MobileIdentityStatus({
    required this.enrollmentState,
    required this.accessReady,
    required this.nextAction,
    required this.doorCount,
    required this.targetSynced,
    this.tenantLabel,
    this.accountName,
    this.unitNumber,
    this.aclVersion,
    this.expiresAtEpoch,
    this.mobileRole = 'USER',
  });

  final EnrollmentState enrollmentState;
  final bool accessReady;
  final String nextAction;
  final int doorCount;
  final bool targetSynced;
  final String? tenantLabel;
  final String? accountName;
  final String? unitNumber;
  final int? aclVersion;
  final int? expiresAtEpoch;
  final String mobileRole;

  bool get isMobileAdmin => mobileRole == 'TENANT_ADMIN';

  factory MobileIdentityStatus.fromJson(Map<String, dynamic> value) {
    final accountName = value['account_name']?.toString().trim();
    final unitNumber = value['unit_number']?.toString().trim();
    final hasPrivateAccountLabel = accountName != null &&
        accountName.isNotEmpty &&
        unitNumber != null &&
        unitNumber.isNotEmpty;
    return MobileIdentityStatus(
      enrollmentState: enrollmentStateFromWire(
        value['enrollment_state']?.toString(),
        aclExpiresAtEpoch: (value['credential_expires_at'] as num?)?.toInt(),
      ),
      accessReady: value['access_ready'] == true,
      nextAction: value['next_action']?.toString() ?? 'retry',
      doorCount: (value['door_count'] as num?)?.toInt() ?? 0,
      targetSynced: value['target_synced'] == true,
      // Do not render the legacy shared tenant label as a person's identity.
      // Older Backends may populate it with the household owner's PII.
      tenantLabel: hasPrivateAccountLabel ? '$accountName $unitNumber' : null,
      accountName: hasPrivateAccountLabel ? accountName : null,
      unitNumber: hasPrivateAccountLabel ? unitNumber : null,
      aclVersion: (value['acl_version'] as num?)?.toInt(),
      expiresAtEpoch: (value['credential_expires_at'] as num?)?.toInt(),
      mobileRole:
          value['mobile_role'] == 'TENANT_ADMIN' ? 'TENANT_ADMIN' : 'USER',
    );
  }

  static const unavailable = MobileIdentityStatus(
    enrollmentState: EnrollmentState.unregistered,
    accessReady: false,
    nextAction: 'status_unavailable',
    doorCount: 0,
    targetSynced: false,
  );
}

class MobileLifecycleEvent {
  const MobileLifecycleEvent({
    required this.eventRef,
    required this.type,
    required this.createdAt,
  });

  final String eventRef;
  final String type;
  final DateTime createdAt;
}

enum MobileAccessSessionStatus {
  pending,
  armed,
  sensorDetected,
  relayActive,
  cooldown,
  complete,
  terminated,
}

class MobileAccessSession {
  const MobileAccessSession({
    required this.targetSessionId,
    required this.status,
    required this.targetFresh,
    required this.nextAuthReady,
    required this.backendTerminal,
    this.eventRef,
    this.occurredAt,
    this.targetState,
  });

  final String targetSessionId;
  final MobileAccessSessionStatus status;
  final String? eventRef;
  final DateTime? occurredAt;
  final String? targetState;
  final bool targetFresh;
  final bool nextAuthReady;
  final bool backendTerminal;

  bool get isReadyComplete =>
      backendTerminal &&
      status == MobileAccessSessionStatus.complete &&
      targetFresh &&
      nextAuthReady &&
      targetState == 'IDLE';

  bool get isTerminal =>
      (backendTerminal && status == MobileAccessSessionStatus.terminated) ||
      isReadyComplete;

  static MobileAccessSession? tryParse(
    Map<String, dynamic> value, {
    required String targetSessionId,
  }) {
    if (!isCanonicalTargetSessionId(targetSessionId)) return null;
    final status = switch (value['status']?.toString()) {
      'pending' => MobileAccessSessionStatus.pending,
      'armed' => MobileAccessSessionStatus.armed,
      'sensor_detected' => MobileAccessSessionStatus.sensorDetected,
      'relay_active' => MobileAccessSessionStatus.relayActive,
      'cooldown' => MobileAccessSessionStatus.cooldown,
      'complete' => MobileAccessSessionStatus.complete,
      'terminated' => MobileAccessSessionStatus.terminated,
      _ => null,
    };
    if (status == null) return null;
    final targetState = value['target_state']?.toString();
    const targetStates = <String>{
      'IDLE',
      'AUTH_PENDING',
      'ARMED',
      'RELAY_HOLD',
      'COOLDOWN',
    };
    final occurredAtSeconds = (value['occurred_at'] as num?)?.toInt();
    return MobileAccessSession(
      targetSessionId: targetSessionId.toLowerCase(),
      status: status,
      eventRef: value['event_ref']?.toString().trim().isNotEmpty == true
          ? value['event_ref'].toString()
          : null,
      occurredAt: occurredAtSeconds == null
          ? null
          : DateTime.fromMillisecondsSinceEpoch(
              occurredAtSeconds * 1000,
              isUtc: true,
            ),
      targetState: targetStates.contains(targetState) ? targetState : null,
      targetFresh: value['target_fresh'] == true,
      nextAuthReady: value['next_auth_ready'] == true,
      backendTerminal: value['terminal'] == true,
    );
  }
}

class MobilePersonalActivity {
  const MobilePersonalActivity({
    required this.lifecycleEvents,
    this.accessSession,
    this.accessLookupAuthorized = true,
    this.outcome = MobilePersonalActivityOutcome.success,
    this.retryAfter,
  });

  final List<MobileLifecycleEvent> lifecycleEvents;
  final MobileAccessSession? accessSession;
  final bool accessLookupAuthorized;
  final MobilePersonalActivityOutcome outcome;
  final Duration? retryAfter;

  static const empty = MobilePersonalActivity(lifecycleEvents: []);
}

enum MobilePersonalActivityOutcome {
  success,
  accessDenied,
  rateLimited,
  retryableFailure,
  terminalFailure,
}

class _PersonalActivityHttpResult {
  const _PersonalActivityHttpResult(
    this.outcome, {
    this.body,
    this.retryAfter,
  });

  final MobilePersonalActivityOutcome outcome;
  final Map<String, dynamic>? body;
  final Duration? retryAfter;
}

/// Reads the authenticated personal identity contract. The legacy device ID is
/// migration context only; `accessReady` is returned only for the exact native
/// credential and signed ACL entry.
class MobileIdentityService {
  MobileIdentityService({
    http.Client? client,
    NativeGattWorkerHealthBridge? nativeBridge,
    Future<String> Function()? deviceIdProvider,
    String? backendBaseUrl,
    String? apiKey,
  })  : _client = client ?? http.Client(),
        _native = nativeBridge ?? NativeGattWorkerHealthBridge(),
        _deviceIdProvider = deviceIdProvider ?? DeviceIdService.getDeviceId,
        _backendBaseUrl = backendBaseUrl ?? _configuredBackendBaseUrl,
        _apiKey = apiKey ?? _configuredApiKey;

  static const String _configuredBackendBaseUrl = String.fromEnvironment(
    'BACKEND_URL',
    defaultValue: 'https://tworimpa.synology.me:4442/api/v1',
  );
  static const String _configuredApiKey =
      String.fromEnvironment('GATEKEEPER_API_KEY');

  final http.Client _client;
  final NativeGattWorkerHealthBridge _native;
  final Future<String> Function() _deviceIdProvider;
  final String _backendBaseUrl;
  final String _apiKey;

  Future<Map<String, Object?>> _identityBody() async {
    final body = <String, Object?>{'device_id': await _deviceIdProvider()};
    try {
      final material = await _native.prepareLocalGattEnrollment();
      if (material['accepted'] == true) {
        final credentialId = material['credentialId']?.toString();
        final publicKey = material['publicKeySec1']?.toString();
        if (credentialId != null && publicKey != null) {
          body['credential_id'] = credentialId;
          body['public_key_sec1'] = publicKey;
        }
      }
    } catch (_) {}
    return body;
  }

  Future<MobileIdentityStatus> status() async {
    if (_apiKey.isEmpty) return MobileIdentityStatus.unavailable;
    final response = await _post('status', await _identityBody());
    if (response == null) return MobileIdentityStatus.unavailable;
    return MobileIdentityStatus.fromJson(response);
  }

  Future<MobilePersonalActivity> activity({String? targetSessionId}) async {
    if (_apiKey.isEmpty) {
      return MobilePersonalActivity(
        lifecycleEvents: const [],
        accessLookupAuthorized: targetSessionId == null,
        outcome: targetSessionId == null
            ? MobilePersonalActivityOutcome.terminalFailure
            : MobilePersonalActivityOutcome.accessDenied,
      );
    }
    final body = await _identityBody();
    if (!body.containsKey('credential_id')) {
      return MobilePersonalActivity(
        lifecycleEvents: const [],
        accessLookupAuthorized: targetSessionId == null,
        outcome: targetSessionId == null
            ? MobilePersonalActivityOutcome.terminalFailure
            : MobilePersonalActivityOutcome.accessDenied,
      );
    }
    final exactTargetSessionId = targetSessionId?.toLowerCase();
    var accessLookupAuthorized = exactTargetSessionId == null;
    if (exactTargetSessionId != null &&
        isCanonicalTargetSessionId(exactTargetSessionId)) {
      final proof = await _native.signAccessSessionRead(exactTargetSessionId);
      final nonce = proof['nonce']?.toString().toLowerCase();
      final expiresAt = (proof['expiresAt'] as num?)?.toInt();
      final signature = proof['signatureRaw64']?.toString().toLowerCase();
      accessLookupAuthorized = proof['accepted'] == true &&
          nonce != null &&
          _nonceHex.hasMatch(nonce) &&
          expiresAt != null &&
          expiresAt > 0 &&
          signature != null &&
          _signatureHex.hasMatch(signature);
      if (accessLookupAuthorized) {
        body['target_session_id'] = exactTargetSessionId;
        body['access_nonce'] = nonce;
        body['access_expires_at'] = expiresAt;
        body['access_signature_raw64'] = signature;
      }
    }
    final httpResult = await _postActivity(body);
    final effectiveOutcome =
        exactTargetSessionId != null && !accessLookupAuthorized
            ? MobilePersonalActivityOutcome.accessDenied
            : httpResult.outcome;
    if (httpResult.outcome == MobilePersonalActivityOutcome.accessDenied) {
      accessLookupAuthorized = false;
    }
    final response = httpResult.body;
    if (response == null) {
      return MobilePersonalActivity(
        lifecycleEvents: const [],
        accessLookupAuthorized: accessLookupAuthorized,
        outcome: effectiveOutcome,
        retryAfter: httpResult.retryAfter,
      );
    }
    final events = response['events'];
    final lifecycle = events is! List
        ? const <MobileLifecycleEvent>[]
        : events
            .whereType<Map>()
            .map((raw) {
              final value = raw.cast<String, dynamic>();
              return MobileLifecycleEvent(
                eventRef: value['event_ref']?.toString() ?? '',
                type: value['type']?.toString() ?? 'unknown',
                createdAt: DateTime.fromMillisecondsSinceEpoch(
                  ((value['created_at'] as num?)?.toInt() ?? 0) * 1000,
                  isUtc: true,
                ),
              );
            })
            .where((event) => event.eventRef.isNotEmpty)
            .toList(growable: false);
    final accessRaw = response['access_session'];
    final accessSession = accessLookupAuthorized &&
            exactTargetSessionId != null &&
            accessRaw is Map
        ? MobileAccessSession.tryParse(
            accessRaw.cast<String, dynamic>(),
            targetSessionId: exactTargetSessionId,
          )
        : null;
    return MobilePersonalActivity(
      lifecycleEvents: lifecycle,
      accessSession: accessSession,
      accessLookupAuthorized: accessLookupAuthorized,
      outcome: effectiveOutcome,
      retryAfter: httpResult.retryAfter,
    );
  }

  Future<bool> uploadDiagnostics(Map<String, Object?> bundle) async {
    if (_apiKey.isEmpty || bundle['schema'] != 'sgk-mobile-support-v2') {
      return false;
    }
    try {
      final body = await _identityBody();
      if (!body.containsKey('credential_id') ||
          !body.containsKey('public_key_sec1')) {
        return false;
      }
      body['bundle'] = bundle;
      final response = await _post('diagnostics', body);
      return response?['accepted'] == true &&
          response?['bundle_ref'] == bundle['bundle_ref'];
    } catch (_) {
      return false;
    }
  }

  Future<String> requestRegistration({
    required String name,
    required String unitNumber,
  }) async {
    if (_apiKey.isEmpty) return 'APP_AUTH_UNAVAILABLE';
    final base = _backendBaseUrl.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse('$base/user/request');
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) {
      return 'BACKEND_URL_INVALID';
    }
    try {
      final response = await _client
          .post(
            uri,
            headers: <String, String>{
              'Content-Type': 'application/json',
              'X-API-KEY': _apiKey,
            },
            body: jsonEncode(<String, Object?>{
              'name': name.trim(),
              'room_no': unitNumber.trim(),
              'device_id': await _deviceIdProvider(),
            }),
          )
          .timeout(const Duration(seconds: 10));
      return response.statusCode >= 200 && response.statusCode < 300
          ? 'REQUEST_ACCEPTED'
          : 'REQUEST_REJECTED_${response.statusCode}';
    } catch (_) {
      return 'REQUEST_UNAVAILABLE';
    }
  }

  Future<Map<String, dynamic>?> _post(
      String action, Map<String, Object?> body) async {
    final base = _backendBaseUrl.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse('$base/acl/personal/$action');
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty) {
      return null;
    }
    try {
      final response = await _client
          .post(
            uri,
            headers: <String, String>{
              'Content-Type': 'application/json',
              'X-API-KEY': _apiKey,
            },
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 10));
      if (response.statusCode < 200 || response.statusCode >= 300) return null;
      final decoded = jsonDecode(response.body);
      return decoded is Map<String, dynamic> ? decoded : null;
    } catch (_) {
      return null;
    }
  }

  Future<_PersonalActivityHttpResult> _postActivity(
    Map<String, Object?> body,
  ) async {
    final base = _backendBaseUrl.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse('$base/acl/personal/activity');
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty) {
      return const _PersonalActivityHttpResult(
        MobilePersonalActivityOutcome.terminalFailure,
      );
    }
    try {
      final response = await _client
          .post(
            uri,
            headers: <String, String>{
              'Content-Type': 'application/json',
              'X-API-KEY': _apiKey,
            },
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 10));
      if (response.statusCode >= 200 && response.statusCode < 300) {
        try {
          final decoded = jsonDecode(response.body);
          return decoded is Map<String, dynamic>
              ? _PersonalActivityHttpResult(
                  MobilePersonalActivityOutcome.success,
                  body: decoded,
                )
              : const _PersonalActivityHttpResult(
                  MobilePersonalActivityOutcome.terminalFailure,
                );
        } catch (_) {
          return const _PersonalActivityHttpResult(
            MobilePersonalActivityOutcome.terminalFailure,
          );
        }
      }
      if (const <int>{400, 401, 403, 422}.contains(response.statusCode)) {
        return const _PersonalActivityHttpResult(
          MobilePersonalActivityOutcome.accessDenied,
        );
      }
      if (response.statusCode == 429) {
        return _PersonalActivityHttpResult(
          MobilePersonalActivityOutcome.rateLimited,
          retryAfter: _parseRetryAfter(response.headers['retry-after']),
        );
      }
      if (response.statusCode >= 500 && response.statusCode < 600) {
        return const _PersonalActivityHttpResult(
          MobilePersonalActivityOutcome.retryableFailure,
        );
      }
      return const _PersonalActivityHttpResult(
        MobilePersonalActivityOutcome.terminalFailure,
      );
    } catch (_) {
      return const _PersonalActivityHttpResult(
        MobilePersonalActivityOutcome.retryableFailure,
      );
    }
  }
}

final RegExp _nonceHex = RegExp(r'^[0-9a-f]{64}$');
final RegExp _signatureHex = RegExp(r'^[0-9a-f]{128}$');

Duration? _parseRetryAfter(String? rawValue) {
  final value = rawValue?.trim();
  if (value == null || value.isEmpty) return null;
  final deltaSeconds = int.tryParse(value);
  if (deltaSeconds != null) {
    return deltaSeconds < 0 ? null : Duration(seconds: deltaSeconds);
  }
  final retryAt = DateTime.tryParse(value)?.toUtc();
  if (retryAt == null) return null;
  final delay = retryAt.difference(DateTime.now().toUtc());
  return delay.isNegative ? Duration.zero : delay;
}
