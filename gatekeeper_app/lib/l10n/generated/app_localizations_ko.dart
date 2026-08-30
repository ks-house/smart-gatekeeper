// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Korean (`ko`).
class AppLocalizationsKo extends AppLocalizations {
  AppLocalizationsKo([String locale = 'ko']) : super(locale);

  @override
  String get appTitle => 'Smart Key';

  @override
  String get home => '홈';

  @override
  String get activity => '활동';

  @override
  String get settings => '설정';

  @override
  String get refresh => '새로고침';

  @override
  String get statusCheckNeeded => '상태 확인 필요';

  @override
  String get smartKeyAvailable => '스마트키 사용 가능';

  @override
  String get setupCheckNeeded => '설정 확인 필요';

  @override
  String get registrationPending => '관리자 승인 대기 중';

  @override
  String get readyToEnroll => '스마트키 등록 준비 완료';

  @override
  String get credentialRevoked => '스마트키 권한이 해제됨';

  @override
  String get credentialExpired => '스마트키 권한이 만료됨';

  @override
  String get registrationRequired => '스마트키 등록 필요';

  @override
  String get targetWaiting => 'Target 감지 대기 중';

  @override
  String get targetDetected => 'Target 감지됨';

  @override
  String get targetAuthenticating => '스마트키 인증 중';

  @override
  String get targetArmed => '출입 준비 완료 · 센서 접근 대기';

  @override
  String get targetFailed => 'Target 인증 실패';

  @override
  String get automaticAccessDisabled => '자동 출입 비활성';

  @override
  String get manualOpenRequesting => 'Target에 개방 명령을 요청하고 있습니다.';

  @override
  String get manualOpenCommandExecuted =>
      'Target이 개방 명령을 실행했습니다. 실제 문 열림은 별도 확인이 필요합니다.';

  @override
  String get manualOpenOutcomeUnknown => '개방 결과를 확인할 수 없습니다. 자동 재시도하지 마세요.';

  @override
  String get currentVersion => '설치된 버전';

  @override
  String get availableVersion => '설치 가능 버전';

  @override
  String get supportReport => '지원 보고서';

  @override
  String get supportReportDescription => '제한된 익명 보고서를 복사하기 전에 미리 확인합니다.';

  @override
  String get advancedDiagnostics => '고급 진단';

  @override
  String get copyConsent => '익명 처리된 내용을 확인했으며 복사에 동의합니다.';

  @override
  String get copyReport => '보고서 복사';

  @override
  String get reportCopied => '익명 보고서를 복사했습니다';
}
