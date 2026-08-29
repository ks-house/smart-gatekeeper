import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/commercial_models.dart';
import 'package:gatekeeper_app/services/mobile_identity_service.dart';
import 'package:gatekeeper_app/services/native_gatt_worker_health.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('status sends exact native credential identity to personal endpoint',
      () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response(
        jsonEncode(<String, Object?>{
          'enrollment_state': 'approved',
          'access_ready': true,
          'next_action': 'open_door',
          'door_count': 1,
          'target_synced': true,
          'tenant_label': 'Tenant A',
          'acl_version': 42,
          'credential_expires_at': 4102444800,
        }),
        200,
      );
    });
    final service = MobileIdentityService(
      client: client,
      nativeBridge: _IdentityNativeBridge(),
      deviceIdProvider: () async => 'legacy-device',
      backendBaseUrl: 'https://example.test/api/v1',
      apiKey: 'test-key',
    );

    final status = await service.status();
    final body = jsonDecode(captured.body) as Map<String, dynamic>;

    expect(captured.url.path, '/api/v1/acl/personal/status');
    expect(body['device_id'], 'legacy-device');
    expect(body['credential_id'], 'credential-1');
    expect(body['public_key_sec1'], '04abc');
    expect(status.enrollmentState, EnrollmentState.approved);
    expect(status.accessReady, isTrue);
    expect(status.targetSynced, isTrue);
  });

  test('invalid or unavailable response stays explicitly unavailable',
      () async {
    final service = MobileIdentityService(
      client: MockClient((_) async => http.Response('unavailable', 503)),
      nativeBridge: _IdentityNativeBridge(),
      deviceIdProvider: () async => 'legacy-device',
      backendBaseUrl: 'https://example.test/api/v1',
      apiKey: 'test-key',
    );

    final status = await service.status();

    expect(status.accessReady, isFalse);
    expect(status.nextAction, 'status_unavailable');
  });
}

class _IdentityNativeBridge extends NativeGattWorkerHealthBridge {
  @override
  Future<Map<Object?, Object?>> prepareLocalGattEnrollment() async =>
      <Object?, Object?>{
        'accepted': true,
        'credentialId': 'credential-1',
        'publicKeySec1': '04abc',
      };
}
