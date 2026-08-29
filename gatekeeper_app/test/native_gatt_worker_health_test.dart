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
        'latestDetection': <String, Object?>{
          'source': 'ble_scan',
          'success': true,
          'receivedEpochMs': 1724930000000,
          'callbackLatencyMs': 12.5,
          'strongestRssi': -54,
          'screenInteractive': false,
          'resultCount': 1,
          'errorCode': 0,
        },
        'lastSession': <String, Object?>{
          'state': 'SUCCEEDED',
          'updatedEpochMs': 1724930002000,
        },
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
    expect(health.latestDetection?.strongestRssi, -54);
    expect(health.latestDetection?.screenInteractive, isFalse);
    expect(
      health.detectionStageAt(
        DateTime.fromMillisecondsSinceEpoch(1724930003000),
      ),
      TargetDetectionStage.armed,
    );
    expect(health.updateManagerIndependent, isTrue);
    expect(health.networkRequired, isFalse);
  });

  test('detection stage distinguishes waiting, live authentication and failure',
      () {
    const detection = TargetDetectionSummary(
      source: 'ble_scan',
      success: true,
      receivedEpochMs: 1000,
      screenInteractive: true,
      resultCount: 1,
      errorCode: 0,
    );
    const base = NativeGattWorkerHealth(
      featureEnabled: true,
      featureStatus: 'enabled',
      bleOwner: 'native_gatt',
      localBootstrapAllowed: true,
      credentialProvisioned: true,
      localConsentValid: true,
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
    expect(base.detectionStage, TargetDetectionStage.waiting);

    final running = NativeGattWorkerHealth.fromMap(<Object?, Object?>{
      'latestDetection': <Object?, Object?>{
        'source': detection.source,
        'success': detection.success,
        'receivedEpochMs': detection.receivedEpochMs,
        'screenInteractive': detection.screenInteractive,
        'resultCount': detection.resultCount,
        'errorCode': detection.errorCode,
      },
      'lastSession': <Object?, Object?>{
        'state': 'RUNNING',
        'updatedEpochMs': 1001,
      },
    });
    expect(
      running.detectionStageAt(DateTime.fromMillisecondsSinceEpoch(1002)),
      TargetDetectionStage.authenticating,
    );

    final failed = NativeGattWorkerHealth.fromMap(<Object?, Object?>{
      'latestDetection': <Object?, Object?>{
        'source': 'ble_scan',
        'success': false,
        'receivedEpochMs': 2000,
        'screenInteractive': false,
        'resultCount': 0,
        'errorCode': 3,
      },
    });
    expect(
      failed.detectionStageAt(DateTime.fromMillisecondsSinceEpoch(2001)),
      TargetDetectionStage.failed,
    );

    final stale = NativeGattWorkerHealth.fromMap(<Object?, Object?>{
      'maxPresenceAgeMs': 45000,
      'latestDetection': <Object?, Object?>{
        'source': 'ble_scan',
        'success': true,
        'receivedEpochMs': 1000,
        'screenInteractive': true,
        'resultCount': 1,
        'errorCode': 0,
      },
    });
    expect(
      stale.detectionStageAt(DateTime.fromMillisecondsSinceEpoch(46001)),
      TargetDetectionStage.waiting,
    );
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

  test(
    'manual open bridge waits for terminal native action-2 result',
    () async {
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

      final result =
          await NativeGattWorkerHealthBridge().triggerLocalGattOpen();

      expect(observed?.method, 'triggerLocalGattOpen');
      expect(observed?.arguments, isNull);
      expect(result['accepted'], isTrue);
      expect(result['reason'], 'OPENED');
      expect(result['latencyMs'], 4585);
    },
  );
}
