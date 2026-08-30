enum DoorState {
  detecting,
  authorizing,
  armed,
  opening,
  confirmed,
  unknown,
  failed
}

extension DoorStateText on DoorState {
  String get wireName => name;

  String label({bool korean = true}) {
    if (!korean) {
      return switch (this) {
        DoorState.detecting => 'Detecting target',
        DoorState.authorizing => 'Authorizing',
        DoorState.armed => 'Armed; waiting for approach',
        DoorState.opening => 'Executing open command',
        DoorState.confirmed => 'Physical door open confirmed',
        DoorState.unknown => 'Outcome unknown; do not retry automatically',
        DoorState.failed => 'Open command failed',
      };
    }
    return switch (this) {
      DoorState.detecting => 'Target 감지 중',
      DoorState.authorizing => '인증 중',
      DoorState.armed => '무장됨 · 접근 대기',
      DoorState.opening => '개방 명령 실행 중',
      DoorState.confirmed => '실제 문 열림 확인',
      DoorState.unknown => '결과 불명 · 자동 재시도 안 함',
      DoorState.failed => '개방 명령 실패',
    };
  }
}

DoorState doorStateFromNative(Map<Object?, Object?>? session) {
  final state = session?['state']?.toString();
  return switch (state) {
    'QUEUED' || 'RUNNING' || 'RETRY_PENDING' => DoorState.authorizing,
    'SUCCEEDED' => DoorState.armed,
    'PROOF_UNCERTAIN' => DoorState.unknown,
    'FAILED' || 'DISABLED' => DoorState.failed,
    _ => DoorState.detecting,
  };
}

enum ManualOpenState { commandExecuted, outcomeUnknown, failed }

class ManualOpenOutcome {
  const ManualOpenOutcome({
    required this.state,
    required this.reason,
    this.latencyMs,
    this.sessionId,
  });

  factory ManualOpenOutcome.fromNative(Map<Object?, Object?> result) {
    final accepted = result['accepted'] == true;
    final reason = result['reason']?.toString() ?? 'NATIVE_UNAVAILABLE';
    final latencyMs = (result['latencyMs'] as num?)?.toInt();
    final sessionId = result['sessionId']?.toString();
    final uncertain = reason.contains('PROOF') || reason.contains('UNCERTAIN');
    return ManualOpenOutcome(
      state: accepted && reason == 'OPENED'
          ? ManualOpenState.commandExecuted
          : (accepted || uncertain
              ? ManualOpenState.outcomeUnknown
              : ManualOpenState.failed),
      reason: reason,
      latencyMs: latencyMs,
      sessionId: sessionId == null || sessionId.isEmpty ? null : sessionId,
    );
  }

  final ManualOpenState state;
  final String reason;
  final int? latencyMs;
  final String? sessionId;

  bool get commandExecuted => state == ManualOpenState.commandExecuted;
}

enum EnrollmentState {
  unregistered,
  pending,
  readyToEnroll,
  approved,
  revoked,
  expired
}

EnrollmentState enrollmentStateFromWire(String? value,
    {int? aclExpiresAtEpoch}) {
  if (value == 'approved' &&
      aclExpiresAtEpoch != null &&
      aclExpiresAtEpoch <= DateTime.now().millisecondsSinceEpoch ~/ 1000) {
    return EnrollmentState.expired;
  }
  return switch (value) {
    'pending' => EnrollmentState.pending,
    'ready_to_enroll' => EnrollmentState.readyToEnroll,
    'approved' => EnrollmentState.approved,
    'revoked' => EnrollmentState.revoked,
    _ => EnrollmentState.unregistered,
  };
}
