// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'Smart Key';

  @override
  String get home => 'Home';

  @override
  String get activity => 'Activity';

  @override
  String get settings => 'Settings';

  @override
  String get refresh => 'Refresh';

  @override
  String get statusCheckNeeded => 'Status check needed';

  @override
  String get smartKeyAvailable => 'Smart Key ready';

  @override
  String get setupCheckNeeded => 'Check setup';

  @override
  String get registrationPending => 'Waiting for administrator approval';

  @override
  String get readyToEnroll => 'Ready to register this phone';

  @override
  String get credentialRevoked => 'Smart Key access revoked';

  @override
  String get credentialExpired => 'Smart Key access expired';

  @override
  String get registrationRequired => 'Smart Key registration required';

  @override
  String get targetWaiting => 'Waiting for Target';

  @override
  String get targetDetected => 'Target detected';

  @override
  String get targetAuthenticating => 'Authenticating Smart Key';

  @override
  String get targetArmed => 'Access ready - waiting for sensor approach';

  @override
  String get targetFailed => 'Target authentication failed';

  @override
  String get automaticAccessDisabled => 'Automatic access disabled';

  @override
  String get manualOpenRequesting => 'Requesting an open command from Target.';

  @override
  String get manualOpenCommandExecuted =>
      'Target executed the open command. Physical door opening is not confirmed.';

  @override
  String get manualOpenOutcomeUnknown =>
      'The open-command outcome is unknown. Do not retry automatically.';

  @override
  String get statusRefreshing => 'Refreshing status.';

  @override
  String get backendUnavailableRetry =>
      'Could not reach the backend. Please try again shortly.';

  @override
  String get statusUpdated => 'Latest status applied.';

  @override
  String get credentialEnrolling =>
      'Registering this phone\'s Smart Key credential.';

  @override
  String get credentialEnrollmentComplete =>
      'Smart Key registration completed.';

  @override
  String get bluetoothRequired => 'Turn on Bluetooth and try again.';

  @override
  String get permissionsRequired => 'Check the required permissions.';

  @override
  String get batteryRestrictionRequired =>
      'Remove the battery usage restriction.';

  @override
  String get targetUnavailable => 'No recently detected Target is available.';

  @override
  String get smartKeyPermissionCheck =>
      'Ask an administrator to check your Smart Key access.';

  @override
  String get targetResponseTimeout => 'The Target response timed out.';

  @override
  String get requestFailedGeneric =>
      'The request did not complete. Check Advanced diagnostics.';

  @override
  String get smartKeyAvailableDetail =>
      'Keep this phone with you. Authentication starts automatically when you approach the Target.';

  @override
  String get backendStatusUnavailableDetail =>
      'Backend status is unavailable. Local recovery and updates remain available.';

  @override
  String get requestRegistrationDetail =>
      'Enter registration details and request administrator approval.';

  @override
  String get waitForApprovalDetail => 'This screen refreshes after approval.';

  @override
  String get enrollCredentialDetail =>
      'Link this phone\'s secure key to the approved account.';

  @override
  String get waitForAclDetail =>
      'Wait until the Target applies the latest access policy.';

  @override
  String get advancedDiagnosticsDetail =>
      'Detailed status is available in Advanced diagnostics.';

  @override
  String get requestRegistration => 'Request registration';

  @override
  String get checkApprovalStatus => 'Check approval';

  @override
  String get registerThisPhone => 'Register this phone';

  @override
  String get checkRegistration => 'Check registration';

  @override
  String get viewRenewalGuide => 'View renewal guide';

  @override
  String get refreshStatus => 'Refresh status';

  @override
  String get requestOpenCommand => 'Request open';

  @override
  String get checkAgain => 'Check again';

  @override
  String get processing => 'Processing';

  @override
  String get noRecentDetection => 'No recent detection';

  @override
  String get recentDetection => 'Last detected';

  @override
  String get registrationInfo => 'Registration information';

  @override
  String get registeredDoors => 'Registered doors';

  @override
  String get checking => 'Checking';

  @override
  String get currentVersion => 'Installed version';

  @override
  String get availableVersion => 'Available version';

  @override
  String get supportReport => 'Support report';

  @override
  String get supportReportDescription =>
      'Preview a bounded redacted report before copying it.';

  @override
  String get advancedDiagnostics => 'Advanced diagnostics';

  @override
  String get copyConsent =>
      'I reviewed this redacted report and consent to copy it.';

  @override
  String get copyReport => 'Copy report';

  @override
  String get reportCopied => 'Redacted report copied';
}
