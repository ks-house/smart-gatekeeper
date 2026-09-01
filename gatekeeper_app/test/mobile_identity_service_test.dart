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
          'tenant_label': 'Household Owner 401',
          'account_name': 'Resident A',
          'unit_number': '401',
          'acl_version': 42,
          'credential_expires_at': 4102444800,
          'mobile_role': 'TENANT_ADMIN',
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
    expect(status.accountName, 'Resident A');
    expect(status.unitNumber, '401');
    expect(status.tenantLabel, 'Resident A 401');
    expect(status.isMobileAdmin, isTrue);
  });

  test('shared legacy tenant label is never rendered as phone identity',
      () async {
    final service = MobileIdentityService(
      client: MockClient((_) async => http.Response(
            jsonEncode(<String, Object?>{
              'enrollment_state': 'approved',
              'access_ready': true,
              'next_action': 'open_door',
              'door_count': 1,
              'target_synced': true,
              'tenant_label': 'Household Owner 401',
            }),
            200,
          )),
      nativeBridge: _IdentityNativeBridge(),
      deviceIdProvider: () async => 'legacy-device',
      backendBaseUrl: 'https://example.test/api/v1',
      apiKey: 'test-key',
    );

    final status = await service.status();

    expect(status.tenantLabel, isNull);
    expect(status.accountName, isNull);
    expect(status.unitNumber, isNull);
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

  test('activity keeps lifecycle events and requests one exact access session',
      () async {
    late http.Request captured;
    final service = MobileIdentityService(
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode(<String, Object?>{
            'events': <Object?>[
              <String, Object?>{
                'event_ref': 'lifecycle-1',
                'type': 'credential_approved',
                'created_at': 1724930000,
              },
            ],
            'access_session': <String, Object?>{
              'status': 'complete',
              'event_ref': 'access-1',
              'occurred_at': 1724930010,
              'target_state': 'IDLE',
              'target_fresh': true,
              'next_auth_ready': true,
              'terminal': true,
            },
          }),
          200,
        );
      }),
      nativeBridge: _IdentityNativeBridge(),
      deviceIdProvider: () async => 'legacy-device',
      backendBaseUrl: 'https://example.test/api/v1',
      apiKey: 'test-key',
    );

    final activity = await service.activity(
      targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
    );
    final body = jsonDecode(captured.body) as Map<String, dynamic>;

    expect(captured.url.path, '/api/v1/acl/personal/activity');
    expect(
      body['target_session_id'],
      '10213243-5465-4687-98a9-bacbdcedfe0f',
    );
    expect(body['access_nonce'], List<String>.filled(32, 'ab').join());
    expect(body['access_expires_at'], 1724930020);
    expect(
      body['access_signature_raw64'],
      List<String>.filled(64, 'cd').join(),
    );
    expect(activity.lifecycleEvents.single.type, 'credential_approved');
    expect(activity.accessSession?.status, MobileAccessSessionStatus.complete);
    expect(activity.accessSession?.targetState, 'IDLE');
    expect(activity.accessSession?.isReadyComplete, isTrue);
    expect(activity.accessSession?.isTerminal, isTrue);
    expect(activity.outcome, MobilePersonalActivityOutcome.success);
  });

  test('activity remains compatible with lifecycle-only Backend response',
      () async {
    late http.Request captured;
    final service = MobileIdentityService(
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          '{"events":[{"event_ref":"legacy-1","type":"door_granted","created_at":1}]}',
          200,
        );
      }),
      nativeBridge: _IdentityNativeBridge(),
      deviceIdProvider: () async => 'legacy-device',
      backendBaseUrl: 'https://example.test/api/v1',
      apiKey: 'test-key',
    );

    final activity = await service.activity(targetSessionId: 'not-a-uuid');
    final body = jsonDecode(captured.body) as Map<String, dynamic>;

    expect(body, isNot(contains('target_session_id')));
    expect(activity.lifecycleEvents.single.eventRef, 'legacy-1');
    expect(activity.accessSession, isNull);
  });

  test('complete status cannot claim next authentication without fresh IDLE',
      () {
    final session = MobileAccessSession.tryParse(
      <String, dynamic>{
        'status': 'complete',
        'target_state': 'COOLDOWN',
        'target_fresh': true,
        'next_auth_ready': true,
        'terminal': true,
      },
      targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
    );

    expect(session, isNotNull);
    expect(session?.isReadyComplete, isFalse);
    expect(session?.isTerminal, isFalse);
  });

  test('failed terminal never becomes successful when next auth is ready', () {
    final session = MobileAccessSession.tryParse(
      <String, dynamic>{
        'status': 'terminated',
        'target_state': 'IDLE',
        'target_fresh': true,
        'next_auth_ready': true,
        'terminal': true,
      },
      targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
    );

    expect(session, isNotNull);
    expect(session?.isReadyComplete, isFalse);
    expect(session?.isTerminal, isTrue);
    expect(session?.status, MobileAccessSessionStatus.terminated);
  });

  test('Keystore proof failure omits only exact access lookup fields',
      () async {
    late http.Request captured;
    final service = MobileIdentityService(
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          '{"events":[],"access_session":{"status":"complete",'
          '"target_state":"IDLE","target_fresh":true,'
          '"next_auth_ready":true,"terminal":true}}',
          200,
        );
      }),
      nativeBridge: _FailingIdentityNativeBridge(),
      deviceIdProvider: () async => 'legacy-device',
      backendBaseUrl: 'https://example.test/api/v1',
      apiKey: 'test-key',
    );

    final activity = await service.activity(
      targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
    );
    final body = jsonDecode(captured.body) as Map<String, dynamic>;

    expect(activity.accessLookupAuthorized, isFalse);
    expect(activity.accessSession, isNull);
    expect(body, isNot(contains('target_session_id')));
    expect(body, isNot(contains('access_nonce')));
    expect(body['credential_id'], 'credential-1');
  });

  test('400, 401, 403, and 422 revoke access lookup authorization', () async {
    for (final statusCode in <int>[400, 401, 403, 422]) {
      final service = MobileIdentityService(
        client: MockClient((_) async => http.Response('{}', statusCode)),
        nativeBridge: _IdentityNativeBridge(),
        deviceIdProvider: () async => 'legacy-device',
        backendBaseUrl: 'https://example.test/api/v1',
        apiKey: 'test-key',
      );

      final activity = await service.activity(
        targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
      );

      expect(activity.accessLookupAuthorized, isFalse, reason: '$statusCode');
      expect(
        activity.outcome,
        MobilePersonalActivityOutcome.accessDenied,
        reason: '$statusCode',
      );
    }
  });

  test('429 returns typed Retry-After while keeping valid local proof',
      () async {
    final service = MobileIdentityService(
      client: MockClient((_) async => http.Response(
            '{}',
            429,
            headers: <String, String>{'retry-after': '17'},
          )),
      nativeBridge: _IdentityNativeBridge(),
      deviceIdProvider: () async => 'legacy-device',
      backendBaseUrl: 'https://example.test/api/v1',
      apiKey: 'test-key',
    );

    final activity = await service.activity(
      targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
    );

    expect(activity.accessLookupAuthorized, isTrue);
    expect(activity.outcome, MobilePersonalActivityOutcome.rateLimited);
    expect(activity.retryAfter, const Duration(seconds: 17));
  });

  test('only network and 5xx failures produce bounded-retry outcome', () async {
    Future<MobilePersonalActivity> activityFor(
      Future<http.Response> Function(http.Request) handler,
    ) {
      return MobileIdentityService(
        client: MockClient(handler),
        nativeBridge: _IdentityNativeBridge(),
        deviceIdProvider: () async => 'legacy-device',
        backendBaseUrl: 'https://example.test/api/v1',
        apiKey: 'test-key',
      ).activity(
        targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
      );
    }

    final serverFailure = await activityFor(
      (_) async => http.Response('{}', 503),
    );
    final networkFailure = await activityFor(
      (_) => Future<http.Response>.error(Exception('offline')),
    );
    final otherFailure = await activityFor(
      (_) async => http.Response('{}', 404),
    );

    expect(
      serverFailure.outcome,
      MobilePersonalActivityOutcome.retryableFailure,
    );
    expect(
      networkFailure.outcome,
      MobilePersonalActivityOutcome.retryableFailure,
    );
    expect(otherFailure.outcome, MobilePersonalActivityOutcome.terminalFailure);
  });

  test('native registration request contains only supervised profile fields',
      () async {
    late http.Request captured;
    final service = MobileIdentityService(
      client: MockClient((request) async {
        captured = request;
        return http.Response('{"status":"pending"}', 200);
      }),
      nativeBridge: _IdentityNativeBridge(),
      deviceIdProvider: () async => 'GK-12345678-1234-1234-1234-123456789012',
      backendBaseUrl: 'https://example.test/api/v1',
      apiKey: 'test-key',
    );

    final outcome = await service.requestRegistration(
      name: ' Resident B ',
      unitNumber: ' 402 ',
    );
    final body = jsonDecode(captured.body) as Map<String, dynamic>;

    expect(outcome, 'REQUEST_ACCEPTED');
    expect(captured.url.path, '/api/v1/user/request');
    expect(body, <String, dynamic>{
      'name': 'Resident B',
      'room_no': '402',
      'device_id': 'GK-12345678-1234-1234-1234-123456789012',
    });
    expect(body, isNot(contains('open_door')));
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

  @override
  Future<Map<Object?, Object?>> signAccessSessionRead(
    String targetSessionId,
  ) async =>
      <Object?, Object?>{
        'accepted': true,
        'reason': 'SIGNED',
        'nonce': List<String>.filled(32, 'ab').join(),
        'expiresAt': 1724930020,
        'signatureRaw64': List<String>.filled(64, 'cd').join(),
      };
}

class _FailingIdentityNativeBridge extends _IdentityNativeBridge {
  @override
  Future<Map<Object?, Object?>> signAccessSessionRead(
    String targetSessionId,
  ) async =>
      const <Object?, Object?>{
        'accepted': false,
        'reason': 'ACCESS_SESSION_PROOF_UNAVAILABLE',
      };
}
