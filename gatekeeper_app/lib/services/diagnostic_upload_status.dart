/// Presentation only. A past ACK is not proof that today's evidence is stored.
class DiagnosticUploadStatus {
  DiagnosticUploadStatus(Map<Object?, Object?> values,
      {DateTime? now, bool? uploadEnabled})
      : values = {
          ...values,
          if (uploadEnabled != null) 'enabled': uploadEnabled,
        },
        now = now ?? DateTime.now();

  final Map<Object?, Object?> values;
  final DateTime now;
  int number(String key) => (values[key] as num?)?.toInt() ?? 0;
  DateTime? time(String key) =>
      number(key) > 0 ? DateTime.fromMillisecondsSinceEpoch(number(key)) : null;
  String get state => values['uploadState']?.toString() ?? 'UNKNOWN';
  bool get enabled => values['enabled'] == true;
  bool get queued =>
      number('pendingUploads') > 0 || number('pendingEvents') > 0;
  bool get acknowledged =>
      enabled &&
      !queued &&
      state == 'ACKNOWLEDGED' &&
      !(time('nextAttemptEpochMs')?.isAfter(now) ?? false) &&
      values['lastCode'] == 'ACCEPTED' &&
      number('quarantinedCount') == 0 &&
      time('lastSuccessEpochMs') != null &&
      !time('lastSuccessEpochMs')!.isAfter(now) &&
      now.difference(time('lastSuccessEpochMs')!) <= const Duration(minutes: 5);

  String get title {
    if (!enabled) return '진단 자동 업로드 꺼짐';
    if (state == 'UPLOADING') return '진단 자료 전송 중';
    if (state == 'AUTH_REQUIRED') return '진단 전송 권한 확인 필요';
    if (number('quarantinedCount') > 0) return '전송 거부된 진단 자료 있음';
    if (time('nextAttemptEpochMs')?.isAfter(now) ?? false) return '진단 재시도 대기';
    if (queued) return '미전송 진단 자료 있음';
    final last = time('lastSuccessEpochMs');
    if (last == null) return '아직 서버 저장 확인 없음';
    if (last.isAfter(now)) return '진단 기록 시각 확인 필요';
    return acknowledged ? '최근 서버 저장 확인됨' : '최근 진단 업데이트 없음';
  }

  String fieldTestReadiness(String markerRef, DateTime createdAt) {
    if (!enabled) return '로컬 표시만 활성 · 자동 업로드 꺼짐';
    final captured = time('lastAckCapturedEpochMs');
    if (values['lastAckFieldTestRef'] != markerRef ||
        captured == null ||
        captured.isBefore(createdAt) ||
        captured.isAfter(now)) {
      return '새 테스트 보고서 서버 저장 확인 대기';
    }
    final baseline = values['lastTargetBaseline'];
    if (baseline is! Map || baseline['fresh'] != true) {
      return '보고서 저장됨 · Target 최신 상태 확인 대기';
    }
    final observed = baseline['observedEpochMs'];
    if (observed is! num || observed <= 0) {
      return '보고서 저장됨 · Target 관측 시각 확인 필요';
    }
    final age = now.millisecondsSinceEpoch - observed.toInt();
    if (age < 0 ||
        age > 120000 ||
        now.difference(captured) > const Duration(minutes: 2)) {
      return '준비 관측 오래됨 · 새 상태 확인 대기';
    }
    if (baseline['state'] != 'IDLE' || baseline['relayCommandedOn'] != false) {
      return '보고서 저장됨 · Target 대기 상태 확인 필요';
    }
    return '수집 준비 확인 · 실제 출입 성공 확인은 아님';
  }

  List<String> get details => [
        '대기 보고서 ${number('pendingUploads')}건 · 사건 ${number('pendingEvents')}건',
        if (time('lastSuccessEpochMs') case final last?)
          '마지막 서버 저장: ${last.toLocal().toString().split('.').first}',
        if (time('oldestPendingEpochMs') case final oldest?)
          '가장 오래된 대기: ${oldest.toLocal().toString().split('.').first}',
        if (time('nextAttemptEpochMs') case final next?)
          '재시도 가능 시각: ${next.toLocal().toString().split('.').first} 이후',
        if (number('droppedEvents') > 0)
          '누적 기록 유실 ${number('droppedEvents')}건 · 전체 구간 보존 아님',
        if (number('quarantinedCount') > 0)
          '전송 거부 ${number('quarantinedCount')}건 별도 보존 · 저장 성공으로 처리하지 않음',
        if (values['lastCode'] != null && values['lastCode'] != 'ACCEPTED')
          '최근 전송 결과: ${values['lastCode']}',
      ];
}
