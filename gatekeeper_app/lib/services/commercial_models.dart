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
        DoorState.opening => 'Opening; waiting for Target confirmation',
        DoorState.confirmed => 'Door open confirmed',
        DoorState.unknown => 'Outcome unknown; do not retry automatically',
        DoorState.failed => 'Door open failed',
      };
    }
    return switch (this) {
      DoorState.detecting => 'Target 감지 중',
      DoorState.authorizing => '인증 중',
      DoorState.armed => '무장됨 · 접근 대기',
      DoorState.opening => '문 여는 중 · Target 확인 대기',
      DoorState.confirmed => '문 열림 확인',
      DoorState.unknown => '결과 불명 · 자동 재시도 안 함',
      DoorState.failed => '문 열기 실패',
    };
  }
}

DoorState doorStateFromNative(Map<Object?, Object?>? session) {
  final state = session?['state']?.toString();
  return switch (state) {
    'QUEUED' => DoorState.authorizing,
    'RUNNING' => DoorState.opening,
    'SUCCEEDED' => DoorState.confirmed,
    'PROOF_UNCERTAIN' => DoorState.unknown,
    'FAILED' || 'DISABLED' => DoorState.failed,
    _ => DoorState.detecting,
  };
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
