import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/native_gatt_worker_health.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel(
    'com.kshouse.gatekeeper_app/ble_gatt_worker_health',
  );

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('bridge exposes redacted authoritative native health fields', () async {
    MethodCall? observed;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      observed = call;
      return <String, Object?>{
        'featureEnabled': true,
        'featureStatus': 'remote_enabled',
        'bleOwner': 'native_gatt',
        'localBootstrapAllowed': true,
        'credentialProvisioned': true,
        'localConsentValid': true,
        'healthy': false,
        'lastReasonCode': 'GATT_TIMEOUT',
        'lastTargetReasonCode': 9,
        'lastTargetReasonName': 'RATE_LIMITED',
        'lastTransportReason': 'DISCONNECTED',
        'lastRetryAfterMs': 9000,
        'lastScheduledRetryDelayMs': 9000,
        'lastLatencyMs': 15000,
        'handsFreeReady': true,
        'wakeRegistered': true,
        'wakeRegistrationStatus': 'registered',
        'initialWorkExpedited': true,
        'maxPresenceAgeMs': 45000,
        'lastPresenceToDispatchMs': 320,
        'lastPresenceToArmedMs': 1840,
        'updateManagerIndependent': true,
        'networkRequired': false,
      };
    });

    final health = await NativeGattWorkerHealthBridge().read();

    expect(observed?.method, 'getHealth');
    expect(observed?.arguments, isNull);
    expect(health.featureEnabled, isTrue);
    expect(health.bleOwner, 'native_gatt');
    expect(health.localBootstrapAllowed, isTrue);
    expect(health.credentialProvisioned, isTrue);
    expect(health.localConsentValid, isTrue);
    expect(health.lastReasonCode, 'GATT_TIMEOUT');
    expect(health.lastTargetReasonCode, 9);
    expect(health.lastTargetReasonName, 'RATE_LIMITED');
    expect(health.lastTransportReason, 'DISCONNECTED');
    expect(health.lastRetryAfterMs, 9000);
    expect(health.lastScheduledRetryDelayMs, 9000);
    expect(health.lastLatencyMs, 15000);
    expect(health.handsFreeReady, isTrue);
    expect(health.wakeRegistered, isTrue);
    expect(health.wakeRegistrationStatus, 'registered');
    expect(health.initialWorkExpedited, isTrue);
    expect(health.maxPresenceAgeMs, 45000);
    expect(health.lastPresenceToDispatchMs, 320);
    expect(health.lastPresenceToArmedMs, 1840);
    expect(health.updateManagerIndependent, isTrue);
    expect(health.networkRequired, isFalse);
  });

  test('local GATT toggle delegates to native authoritative control', () async {
    MethodCall? observed;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      observed = call;
      return <String, Object?>{
        'accepted': true,
        'reason': 'local_keystore_authenticated',
        'featureEnabled': true,
      };
    });

    final result =
        await NativeGattWorkerHealthBridge().setLocalGattEnabled(true);

    expect(observed?.method, 'setLocalGattEnabled');
    expect(observed?.arguments, <String, Object?>{'enabled': true});
    expect(result['accepted'], isTrue);
    expect(result['featureEnabled'], isTrue);
  });

  test('manual open bridge waits for terminal native action-2 result', () async {
    MethodCall? observed;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      observed = call;
      return <String, Object?>{
        'accepted': true,
        'reason': 'OPENED',
        'sessionId': 'redacted-session',
        'latencyMs': 4585,
      };
    });

    final result = await NativeGattWorkerHealthBridge().triggerLocalGattOpen();

    expect(observed?.method, 'triggerLocalGattOpen');
    expect(observed?.arguments, isNull);
    expect(result['accepted'], isTrue);
    expect(result['reason'], 'OPENED');
    expect(result['latencyMs'], 4585);
  });
}
