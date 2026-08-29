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
