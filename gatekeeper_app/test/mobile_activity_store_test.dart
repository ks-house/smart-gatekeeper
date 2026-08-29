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
}
