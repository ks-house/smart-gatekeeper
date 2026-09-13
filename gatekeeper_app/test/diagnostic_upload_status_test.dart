import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/diagnostic_upload_status.dart';

void main() {
  final now = DateTime.utc(2026, 9, 13, 12);
  Map<Object?, Object?> status() => {
        'enabled': true,
        'uploadState': 'ACKNOWLEDGED',
        'lastCode': 'ACCEPTED',
        'lastSuccessEpochMs':
            now.subtract(const Duration(seconds: 10)).millisecondsSinceEpoch,
        'pendingUploads': 0,
        'pendingEvents': 0,
      };
  test('past ACK does not hide pending events or stale report', () {
    final pending =
        DiagnosticUploadStatus({...status(), 'pendingEvents': 64}, now: now);
    expect(pending.acknowledged, isFalse);
    expect(pending.title, '미전송 진단 자료 있음');
    final stale = DiagnosticUploadStatus({
      ...status(),
      'lastSuccessEpochMs':
          now.subtract(const Duration(hours: 5)).millisecondsSinceEpoch
    }, now: now);
    expect(stale.title, '최근 진단 업데이트 없음');
    expect(stale.acknowledged, isFalse);
  });
  test('no success and disabled never show completed', () {
    expect(DiagnosticUploadStatus({'enabled': true}, now: now).title,
        '아직 서버 저장 확인 없음');
    expect(
        DiagnosticUploadStatus({...status(), 'enabled': false}, now: now)
            .acknowledged,
        isFalse);
  });
  test('quarantine and retry-after remain explicit', () {
    final rejected =
        DiagnosticUploadStatus({...status(), 'quarantinedCount': 1}, now: now);
    expect(rejected.acknowledged, isFalse);
    expect(rejected.title, '전송 거부된 진단 자료 있음');
    final retry = DiagnosticUploadStatus({
      ...status(),
      'nextAttemptEpochMs':
          now.add(const Duration(minutes: 1)).millisecondsSinceEpoch
    }, now: now);
    expect(retry.title, '진단 재시도 대기');
    expect(retry.acknowledged, isFalse);
    expect(
        DiagnosticUploadStatus({...status(), 'uploadState': 'UPLOADING'},
                now: now)
            .acknowledged,
        isFalse);
  });
  test('marker alone is not server storage or Target readiness', () {
    final created = now.subtract(const Duration(seconds: 30));
    final marker = 'a' * 16;
    expect(
        DiagnosticUploadStatus(status(), now: now)
            .fieldTestReadiness(marker, created),
        contains('서버 저장 확인 대기'));
    final saved = {
      ...status(),
      'lastAckFieldTestRef': marker,
      'lastAckCapturedEpochMs': now.millisecondsSinceEpoch
    };
    expect(
        DiagnosticUploadStatus(saved, now: now)
            .fieldTestReadiness(marker, created),
        contains('Target 최신 상태 확인 대기'));
    final ready = {
      ...saved,
      'lastTargetBaseline': {
        'fresh': true,
        'observedEpochMs': now.millisecondsSinceEpoch - 1000,
        'state': 'IDLE',
        'relayCommandedOn': false
      }
    };
    expect(
        DiagnosticUploadStatus(ready, now: now)
            .fieldTestReadiness(marker, created),
        startsWith('수집 준비 확인'));
    // A late native callback may contain enabled=true after consent is revoked.
    // The current UI preference must take precedence over that cached snapshot.
    final disabled =
        DiagnosticUploadStatus(ready, now: now, uploadEnabled: false);
    expect(disabled.fieldTestReadiness(marker, created), contains('자동 업로드 꺼짐'));
    expect(disabled.acknowledged, isFalse);
    expect(
        DiagnosticUploadStatus(ready, now: now.add(const Duration(minutes: 3)))
            .fieldTestReadiness(marker, created),
        contains('오래됨'));
    expect(
        DiagnosticUploadStatus({...ready, 'lastAckFieldTestRef': 'b' * 16},
                now: now)
            .fieldTestReadiness(marker, created),
        contains('서버 저장 확인 대기'));
  });
  test('fresh ACK is a server storage observation, never a physical door claim',
      () {
    final current = DiagnosticUploadStatus(status(), now: now);
    expect(current.title, '최근 서버 저장 확인됨');
    expect(current.acknowledged, isTrue);
    expect(current.details.join(), isNot(contains('문 열림')));
  });
}
