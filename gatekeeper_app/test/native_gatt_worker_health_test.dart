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

  test('bridge is read-only and exposes redacted health fields', () async {
    MethodCall? observed;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      observed = call;
      return <String, Object?>{
        'featureEnabled': true,
        'featureStatus': 'remote_enabled',
        'bleOwner': 'native_gatt',
        'healthy': false,
        'lastReasonCode': 'GATT_TIMEOUT',
        'lastTargetReasonCode': 9,
        'lastTargetReasonName': 'RATE_LIMITED',
        'lastTransportReason': 'DISCONNECTED',
        'lastRetryAfterMs': 9000,
        'lastScheduledRetryDelayMs': 9000,
        'lastLatencyMs': 15000,
        'updateManagerIndependent': true,
        'networkRequired': false,
      };
    });

    final health = await NativeGattWorkerHealthBridge().read();

    expect(observed?.method, 'getHealth');
    expect(observed?.arguments, isNull);
    expect(health.featureEnabled, isTrue);
    expect(health.bleOwner, 'native_gatt');
    expect(health.lastReasonCode, 'GATT_TIMEOUT');
    expect(health.lastTargetReasonCode, 9);
    expect(health.lastTargetReasonName, 'RATE_LIMITED');
    expect(health.lastTransportReason, 'DISCONNECTED');
    expect(health.lastRetryAfterMs, 9000);
    expect(health.lastScheduledRetryDelayMs, 9000);
    expect(health.lastLatencyMs, 15000);
    expect(health.updateManagerIndependent, isTrue);
    expect(health.networkRequired, isFalse);
  });
}
