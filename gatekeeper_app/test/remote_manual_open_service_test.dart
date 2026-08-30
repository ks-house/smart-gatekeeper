import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:gatekeeper_app/services/remote_manual_open_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel(
    'com.kshouse.gatekeeper_app/ble_gatt_worker_health',
  );
  final credentialId = List<String>.filled(16, '33').join();
  final signature = List<String>.filled(64, '66').join();

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('credential proof requests Backend MQTT delivery without an API key',
      () async {
    MethodCall? observed;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      observed = call;
      return <String, Object?>{
        'accepted': true,
        'reason': 'SIGNED',
        'credentialId': credentialId,
        'signatureRaw64': signature,
      };
    });
    late http.Request request;
    final service = RemoteManualOpenService(
      backendBaseUrl: 'https://example.test/api/v1',
      clock: () =>
          DateTime.fromMillisecondsSinceEpoch(1900000000000, isUtc: true),
      randomBytes: (length) => List<int>.filled(length, 0x44),
      client: MockClient((incoming) async {
        request = incoming;
        return http.Response(
          jsonEncode(<String, Object?>{
            'result': 'requested',
            'delivery': 'broker-ack-only',
            'request_id': 'opaque-request',
          }),
          200,
        );
      }),
    );

    final outcome = await service.request();

    expect(outcome.state, RemoteManualOpenState.requested);
    expect(outcome.requestId, 'opaque-request');
    expect(observed?.method, 'signRemoteManualOpen');
    expect(request.url.path, '/api/v1/door/open');
    expect(request.headers, isNot(contains('X-API-KEY')));
    expect(request.headers['Idempotency-Key'], isNotEmpty);
    final body = jsonDecode(request.body) as Map<String, dynamic>;
    expect(body['credential_id'], credentialId);
    expect(body['reason'], 'mobile_manual_button');
    expect(body['signature_raw64'], signature);
  });

  test('network ambiguity never retries a physical-effect request', () async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            channel,
            (_) async => <String, Object?>{
                  'accepted': true,
                  'credentialId': credentialId,
                  'signatureRaw64': signature,
                });
    var calls = 0;
    final service = RemoteManualOpenService(
      backendBaseUrl: 'https://example.test/api/v1',
      randomBytes: (length) => List<int>.filled(length, 0x44),
      client: MockClient((_) async {
        calls += 1;
        throw Exception('transport unavailable');
      }),
    );

    final outcome = await service.request();

    expect(outcome.state, RemoteManualOpenState.outcomeUnknown);
    expect(calls, 1);
  });
}
