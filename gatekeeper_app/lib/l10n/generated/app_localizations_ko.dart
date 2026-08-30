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
  String get manualOpenRequesting => '백엔드에 원격 개방 명령을 요청하고 있습니다.';

  @override
  String get manualOpenCommandExecuted =>
      '백엔드가 원격 개방 명령을 MQTT로 전달했습니다. 실제 문 열림은 별도 확인이 필요합니다.';

  @override
  String get manualOpenOutcomeUnknown =>
      '원격 명령 전달 결과를 확인할 수 없습니다. 자동 재시도하지 마세요.';

  @override
  String get statusRefreshing => '상태를 다시 확인하고 있습니다.';

  @override
  String get backendUnavailableRetry => '백엔드에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.';

  @override
  String get statusUpdated => '최신 상태를 반영했습니다.';

  @override
  String get credentialEnrolling => '이 휴대폰의 스마트키 자격을 등록하고 있습니다.';

  @override
  String get credentialEnrollmentComplete => '스마트키 등록이 완료되었습니다.';

  @override
  String get bluetoothRequired => 'Bluetooth를 켠 뒤 다시 시도해주세요.';

  @override
  String get permissionsRequired => '필수 권한을 확인해주세요.';

  @override
  String get batteryRestrictionRequired => '배터리 사용 제한을 해제해주세요.';

  @override
  String get targetUnavailable => '최근 감지된 Target이 없습니다.';

  @override
  String get smartKeyPermissionCheck => '스마트키 권한을 관리자에게 확인해주세요.';

  @override
  String get targetResponseTimeout => 'Target 응답 시간이 초과되었습니다.';

  @override
  String get requestFailedGeneric => '요청을 완료하지 못했습니다. 고급 진단에서 상태를 확인해주세요.';

  @override
  String get smartKeyAvailableDetail => '휴대폰을 소지하고 Target에 접근하면 자동 인증을 시작합니다.';

  @override
  String get backendStatusUnavailableDetail =>
      '백엔드 상태를 확인할 수 없습니다. 로컬 복구와 업데이트는 계속 사용할 수 있습니다.';

  @override
  String get requestRegistrationDetail => '등록 정보를 입력하고 관리자 승인을 요청해주세요.';

  @override
  String get waitForApprovalDetail => '승인 후 이 화면이 자동으로 갱신됩니다.';

  @override
  String get enrollCredentialDetail => '승인된 계정에 이 휴대폰의 보안 키를 연결해주세요.';

  @override
  String get waitForAclDetail => 'Target이 최신 출입 권한을 적용할 때까지 기다려주세요.';

  @override
  String get advancedDiagnosticsDetail => '고급 진단에서 상세 상태를 확인할 수 있습니다.';

  @override
  String get requestRegistration => '등록 요청';

  @override
  String get checkApprovalStatus => '승인 상태 확인';

  @override
  String get registerThisPhone => '이 휴대폰 등록';

  @override
  String get checkRegistration => '등록 정보 확인';

  @override
  String get viewRenewalGuide => '갱신 안내 확인';

  @override
  String get refreshStatus => '상태 새로고침';

  @override
  String get requestOpenCommand => '문 열기';

  @override
  String get checkAgain => '다시 확인';

  @override
  String get processing => '처리 중';

  @override
  String get noRecentDetection => '최근 감지 없음';

  @override
  String get recentDetection => '최근 감지';

  @override
  String get registrationInfo => '등록 정보';

  @override
  String get registeredDoors => '등록 출입문';

  @override
  String get checking => '확인 중';

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
