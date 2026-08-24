import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:gatekeeper_app/services/local_gatt_enrollment_service.dart';
import 'package:gatekeeper_app/services/native_gatt_worker_health.dart';

final String _credentialId = List<String>.filled(16, 'aa').join();
final String _publicKey = '04${List<String>.filled(64, '11').join()}';

void main() {
  test('enrolls exact public material before enabling native GATT', () async {
    final native = _FakeNativeBridge();
    late http.Request observed;
    final client = MockClient((request) async {
      observed = request;
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body, <String, Object?>{
        'device_id': 'device-1',
        'credential_id': _credentialId,
        'public_key_sec1': _publicKey,
        'min_protocol': 1,
        'max_protocol': 1,
      });
      return http.Response(
        jsonEncode(<String, Object?>{
          'accepted': true,
          'credential_id': body['credential_id'],
          'acl_version': 7,
        }),
        200,
      );
    });
    final service = LocalGattEnrollmentService(
      client: client,
      nativeBridge: native,
      deviceIdProvider: () async => 'device-1',
      backendBaseUrl: 'https://gate.example/api/v1',
      apiKey: 'test-api-key',
    );

    final result = await service.ensureEnrolledAndEnabled();

    expect(result.accepted, isTrue);
    expect(result.aclVersion, 7);
    expect(observed.url.toString(),
        'https://gate.example/api/v1/acl/personal/enroll');
    expect(observed.headers['X-API-KEY'], 'test-api-key');
    expect(native.enableCalls, <bool>[true]);
  });

  test('mismatched backend credential fails closed before native enable',
      () async {
    final native = _FakeNativeBridge();
    final service = LocalGattEnrollmentService(
      client: MockClient((_) async => http.Response(
            jsonEncode(<String, Object?>{
              'accepted': true,
              'credential_id': List<String>.filled(16, 'bb').join(),
              'acl_version': 1,
            }),
            200,
          )),
      nativeBridge: native,
      deviceIdProvider: () async => 'device-1',
      backendBaseUrl: 'https://gate.example/api/v1',
      apiKey: 'test-api-key',
    );

    final result = await service.ensureEnrolledAndEnabled();

    expect(result.accepted, isFalse);
    expect(result.reason, 'enrollment_response_invalid');
    expect(native.enableCalls, isEmpty);
  });
}

class _FakeNativeBridge extends NativeGattWorkerHealthBridge {
  final List<bool> enableCalls = <bool>[];

  @override
  Future<NativeGattWorkerHealth> read() async => const NativeGattWorkerHealth(
        featureEnabled: false,
        featureStatus: 'local_bootstrap_pending',
        bleOwner: 'legacy',
        localBootstrapAllowed: true,
        credentialProvisioned: false,
        localConsentValid: false,
        healthy: true,
        lastReasonCode: null,
        lastTargetReasonCode: null,
        lastTargetReasonName: null,
        lastTransportReason: null,
        lastRetryAfterMs: null,
        lastScheduledRetryDelayMs: null,
        lastLatencyMs: null,
        updateManagerIndependent: true,
        networkRequired: false,
      );

  @override
  Future<Map<Object?, Object?>> prepareLocalGattEnrollment() async =>
      <Object?, Object?>{
        'accepted': true,
        'reason': 'enrollment_material_ready',
        'credentialId': _credentialId,
        'publicKeySec1': _publicKey,
        'minProtocol': 1,
        'maxProtocol': 1,
      };

  @override
  Future<Map<Object?, Object?>> setLocalGattEnabled(bool enabled) async {
    enableCalls.add(enabled);
    return <Object?, Object?>{
      'accepted': true,
      'reason': 'local_keystore_authenticated',
      'featureEnabled': enabled,
    };
  }
}
