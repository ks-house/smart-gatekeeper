import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/mobile_activity_store.dart';
import 'package:gatekeeper_app/services/mobile_identity_service.dart';
import 'package:gatekeeper_app/services/native_gatt_worker_health.dart';
import 'package:gatekeeper_app/services/remote_manual_open_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  test('success activity says armed and does not claim the door opened',
      () async {
    final store = MobileActivityStore();
    final health = NativeGattWorkerHealth.fromMap(<Object?, Object?>{
      'lastSession': <Object?, Object?>{
        'state': 'SUCCEEDED',
        'updatedEpochMs': 1000,
      },
    });

    final items = await store.ingest(health);

    expect(items, hasLength(1));
    expect(items.single.title, '출입 준비 완료');
    expect(items.single.detail, contains('문 열림 확인은 아닙니다'));
  });

  test('activity is deduplicated by durable terminal session', () async {
    final store = MobileActivityStore();
    final health = NativeGattWorkerHealth.fromMap(<Object?, Object?>{
      'lastSession': <Object?, Object?>{
        'state': 'FAILED',
        'updatedEpochMs': 2000,
      },
      'lastReasonCode': 'TARGET_UNAVAILABLE',
    });

    await store.ingest(health);
    final items = await store.ingest(health);

    expect(items, hasLength(1));
    expect(items.single.isFailure, isTrue);
  });

  test('access phases are persisted once per Backend event reference',
      () async {
    final store = MobileActivityStore();
    const sensor = MobileAccessSession(
      targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
      status: MobileAccessSessionStatus.sensorDetected,
      eventRef: 'sensor-event',
      targetState: 'RELAY_HOLD',
      targetFresh: true,
      nextAuthReady: false,
      backendTerminal: false,
    );

    await store.recordAccessSession(sensor, observedAt: DateTime.utc(2026));
    final items = await store.recordAccessSession(
      sensor,
      observedAt: DateTime.utc(2026, 1, 1, 0, 0, 2),
    );

    expect(items, hasLength(1));
    expect(items.single.title, '센서 감지 · 개방 동작 중');
    expect(items.single.detail, isNot(contains('문이 열렸')));
  });

  test('only fresh IDLE completion records next authentication ready',
      () async {
    final store = MobileActivityStore();
    const notReady = MobileAccessSession(
      targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
      status: MobileAccessSessionStatus.complete,
      eventRef: 'premature-complete',
      targetState: 'COOLDOWN',
      targetFresh: true,
      nextAuthReady: true,
      backendTerminal: true,
    );
    const ready = MobileAccessSession(
      targetSessionId: '10213243-5465-4687-98a9-bacbdcedfe0f',
      status: MobileAccessSessionStatus.complete,
      eventRef: 'ready-complete',
      targetState: 'IDLE',
      targetFresh: true,
      nextAuthReady: true,
      backendTerminal: true,
    );

    await store.recordAccessSession(notReady, observedAt: DateTime.utc(2026));
    final items = await store.recordAccessSession(
      ready,
      observedAt: DateTime.utc(2026, 1, 1, 0, 0, 1),
    );

    expect(items, hasLength(2));
    expect(items.first.title, '출입 동작 완료 · 다음 인증 가능');
    expect(items.last.title, '개방 동작 완료 · 다음 출입 준비 중');
    expect(items.first.detail, contains('문 개폐 자체를 확정하지 않습니다'));
  });

  test('manual command success is persisted without physical-open claim',
      () async {
    final store = MobileActivityStore();
    final items = await store.recordManualOpenResult(
      <Object?, Object?>{
        'accepted': true,
        'reason': 'OPENED',
        'latencyMs': 1846,
        'sessionId': 'opaque-success',
      },
      occurredAt: DateTime.utc(2026, 8, 30),
    );

    expect(items, hasLength(1));
    expect(items.single.type, 'manual_command_executed');
    expect(items.single.title, '개방 명령 실행 완료');
    expect(items.single.detail, contains('1846ms'));
    expect(items.single.detail, contains('실제 문 열림은 별도 확인'));
    expect(items.single.detail, isNot(contains('문이 열렸습니다')));
    expect(items.single.isFailure, isFalse);
  });

  test('remote broker acknowledgement is not physical-open confirmation',
      () async {
    final store = MobileActivityStore();
    final items = await store.recordRemoteOpenResult(
      const RemoteManualOpenOutcome(
        state: RemoteManualOpenState.requested,
        reason: 'BROKER_ACKNOWLEDGED',
        requestId: 'opaque-request',
      ),
      occurredAt: DateTime.utc(2026, 8, 30),
    );

    expect(items.single.type, 'manual_remote_requested');
    expect(items.single.detail, contains('MQTT broker 전달'));
    expect(items.single.detail, contains('실제 문 열림은 별도 확인'));
    expect(items.single.isFailure, isFalse);
  });

  test('manual proof uncertainty is terminal and prohibits automatic retry',
      () async {
    final store = MobileActivityStore();
    final items = await store.recordManualOpenResult(
      <Object?, Object?>{
        'accepted': false,
        'reason': 'PROOF_UNCERTAIN',
        'sessionId': 'opaque-unknown',
      },
      occurredAt: DateTime.utc(2026, 8, 30),
    );

    expect(items.single.type, 'manual_command_unknown');
    expect(items.single.title, '개방 결과 확인 필요');
    expect(items.single.detail, contains('자동 재시도하지 마세요'));
    expect(items.single.isFailure, isTrue);
  });

  test('manual failure stores only a bounded reason and deduplicates session',
      () async {
    final store = MobileActivityStore();
    final result = <Object?, Object?>{
      'accepted': false,
      'reason': 'target unavailable: private detail',
      'sessionId': 'opaque-failure',
    };

    await store.recordManualOpenResult(
      result,
      occurredAt: DateTime.utc(2026, 8, 30),
    );
    final items = await store.recordManualOpenResult(
      result,
      occurredAt: DateTime.utc(2026, 8, 30, 0, 1),
    );

    expect(items, hasLength(1));
    expect(items.single.type, 'manual_command_failed');
    expect(items.single.title, '개방 명령 실패');
    expect(items.single.detail, contains('TARGET_UNAVAILABLE_PRIVATE_DETAIL'));
    expect(items.single.detail, isNot(contains(':')));
  });
}
