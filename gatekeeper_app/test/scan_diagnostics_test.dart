import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/scan_diagnostics.dart';

void main() {
  const targetUuid = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';

  ScanDiagnostics buildDiagnostics({
    bool locationAlways = true,
    bool batteryExempt = true,
    bool bluetoothConnect = true,
    bool notification = true,
    ScanMode mode = ScanMode.active,
  }) {
    return ScanDiagnostics(
      locationWhenInUse: true,
      locationAlways: locationAlways,
      bluetoothScan: true,
      bluetoothConnect: bluetoothConnect,
      notification: notification,
      bluetoothOn: true,
      locationServicesOn: true,
      ignoringBatteryOptimizations: batteryExempt,
      foregroundServiceRunning: true,
      mode: mode,
      debugForced: false,
      monitoringSubscribed: true,
      rangingSubscribed: mode == ScanMode.active,
      backgroundScanTuningApplied: true,
      targetBeaconUuid: targetUuid,
      androidSdkInt: 34,
      updatedAt: DateTime.utc(2026, 7, 30, 1, 2, 3),
      lastEnterRegionAt: DateTime.utc(2026, 7, 30, 1),
      rangingCallbackCount: 12,
      lastPrearmStatusCode: 200,
      lastPrearmAt: DateTime.utc(2026, 7, 30, 1, 2),
      lastPrearmMessage: '승인 완료 · MQTT 발행 확인',
    );
  }

  test('service diagnostics survive isolate map round trip', () {
    final original = buildDiagnostics();
    final restored = ScanDiagnostics.fromMap(original.toMap(), targetUuid);

    expect(restored.mode, ScanMode.active);
    expect(restored.monitoringSubscribed, isTrue);
    expect(restored.rangingSubscribed, isTrue);
    expect(restored.rangingCallbackCount, 12);
    expect(restored.lastPrearmStatusCode, 200);
    expect(restored.lastPrearmMessage, contains('MQTT'));
    expect(restored.canScan, isTrue);
  });

  test('Android 10+ background location is a blocking requirement', () {
    final diagnostics = buildDiagnostics(locationAlways: false);

    expect(diagnostics.canScan, isFalse);
    expect(
      diagnostics.blockingReasons,
      contains('백그라운드 위치 권한(항상 허용)이 없습니다'),
    );
  });

  test('battery optimization exemption is required for reliable scanning', () {
    final diagnostics = buildDiagnostics(batteryExempt: false);

    expect(diagnostics.canScan, isFalse);
    expect(
      diagnostics.blockingReasons,
      contains('배터리 최적화 예외가 적용되지 않았습니다'),
    );
  });

  test('Android 12+ Bluetooth connect permission is blocking', () {
    final diagnostics = buildDiagnostics(bluetoothConnect: false);

    expect(diagnostics.canScan, isFalse);
    expect(
      diagnostics.blockingReasons,
      contains('BLUETOOTH_CONNECT 권한이 없습니다'),
    );
  });

  test('Android 13+ notification permission is blocking', () {
    final diagnostics = buildDiagnostics(notification: false);

    expect(diagnostics.canScan, isFalse);
    expect(
      diagnostics.blockingReasons,
      contains('알림 권한이 없습니다'),
    );
  });
}
