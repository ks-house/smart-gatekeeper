import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/mobile_activity_store.dart';
import 'package:gatekeeper_app/services/native_gatt_worker_health.dart';
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
