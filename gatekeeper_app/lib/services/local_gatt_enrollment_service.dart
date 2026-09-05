import 'dart:convert';

import 'package:http/http.dart' as http;

import 'device_id_service.dart';
import 'native_gatt_worker_health.dart';

class LocalGattEnrollmentOutcome {
  const LocalGattEnrollmentOutcome({
    required this.accepted,
    required this.reason,
    this.aclVersion,
  });

  final bool accepted;
  final String reason;
  final int? aclVersion;
}

typedef DeviceIdProvider = Future<String> Function();

/// Enrolls only public P-256 material, then enables native GATT after the
/// authenticated HTTPS backend confirms that the exact credential was added
/// to a signed Target ACL. Private key bytes never leave AndroidKeyStore.
class LocalGattEnrollmentService {
  LocalGattEnrollmentService({
    http.Client? client,
    NativeGattWorkerHealthBridge? nativeBridge,
    DeviceIdProvider? deviceIdProvider,
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
  final DeviceIdProvider _deviceIdProvider;
  final String _backendBaseUrl;
  final String _apiKey;

  Future<LocalGattEnrollmentOutcome> ensureEnrolledAndEnabled() async {
    try {
      final health = await _native.read();
      if (health.featureEnabled &&
          health.credentialProvisioned &&
          health.localConsentValid) {
        return const LocalGattEnrollmentOutcome(
          accepted: true,
          reason: 'already_enabled',
        );
      }
      if (!health.localBootstrapAllowed) {
        return const LocalGattEnrollmentOutcome(
          accepted: false,
          reason: 'apk_policy_disabled',
        );
      }
      if (_apiKey.isEmpty) {
        return const LocalGattEnrollmentOutcome(
          accepted: false,
          reason: 'enrollment_auth_unavailable',
        );
      }

      final endpoint = _personalEnrollmentUri();
      if (endpoint == null) {
        return const LocalGattEnrollmentOutcome(
          accepted: false,
          reason: 'enrollment_endpoint_invalid',
        );
      }

      final material = await _native.prepareLocalGattEnrollment();
      if (material['accepted'] != true) {
        return LocalGattEnrollmentOutcome(
          accepted: false,
          reason: material['reason']?.toString() ??
              'enrollment_material_unavailable',
        );
      }
      final credentialId = material['credentialId']?.toString() ?? '';
      final publicKey = material['publicKeySec1']?.toString() ?? '';
      final minProtocol = (material['minProtocol'] as num?)?.toInt() ?? 2;
      final maxProtocol = (material['maxProtocol'] as num?)?.toInt() ?? 2;
      if (!RegExp(r'^[0-9a-f]{32}$').hasMatch(credentialId) ||
          !RegExp(r'^04[0-9a-f]{128}$').hasMatch(publicKey) ||
          minProtocol != 2 ||
          maxProtocol != 2) {
        return const LocalGattEnrollmentOutcome(
          accepted: false,
          reason: 'enrollment_material_invalid',
        );
      }

      final response = await _client
          .post(
            endpoint,
            headers: <String, String>{
              'Content-Type': 'application/json',
              'X-API-KEY': _apiKey,
            },
            body: jsonEncode(<String, Object?>{
              'device_id': await _deviceIdProvider(),
              'credential_id': credentialId,
              'public_key_sec1': publicKey,
              'min_protocol': minProtocol,
              'max_protocol': maxProtocol,
            }),
          )
          .timeout(const Duration(seconds: 15));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        return LocalGattEnrollmentOutcome(
          accepted: false,
          reason: 'enrollment_http_${response.statusCode}',
        );
      }

      final body = jsonDecode(response.body);
      if (body is! Map<String, dynamic> ||
          body['accepted'] != true ||
          body['credential_id']?.toString() != credentialId) {
        return const LocalGattEnrollmentOutcome(
          accepted: false,
          reason: 'enrollment_response_invalid',
        );
      }
      final aclVersion = (body['acl_version'] as num?)?.toInt();
      if (aclVersion == null || aclVersion < 1) {
        return const LocalGattEnrollmentOutcome(
          accepted: false,
          reason: 'acl_not_published',
        );
      }

      final enabled = await _native.setLocalGattEnabled(true);
      if (enabled['accepted'] != true || enabled['featureEnabled'] != true) {
        return LocalGattEnrollmentOutcome(
          accepted: false,
          reason: enabled['reason']?.toString() ?? 'native_enable_failed',
        );
      }
      return LocalGattEnrollmentOutcome(
        accepted: true,
        reason: 'enrolled_and_enabled',
        aclVersion: aclVersion,
      );
    } catch (_) {
      return const LocalGattEnrollmentOutcome(
        accepted: false,
        reason: 'enrollment_unavailable',
      );
    }
  }

  Uri? _personalEnrollmentUri() {
    final value = _backendBaseUrl.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse('$value/acl/personal/enroll');
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty) {
      return null;
    }
    return uri;
  }
}
