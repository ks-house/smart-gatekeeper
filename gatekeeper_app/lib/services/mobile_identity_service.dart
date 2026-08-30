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

  Future<List<MobileLifecycleEvent>> activity() async {
    if (_apiKey.isEmpty) return const [];
    final body = await _identityBody();
    if (!body.containsKey('credential_id')) return const [];
    final response = await _post('activity', body);
    final events = response?['events'];
    if (events is! List) return const [];
    return events
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
}
