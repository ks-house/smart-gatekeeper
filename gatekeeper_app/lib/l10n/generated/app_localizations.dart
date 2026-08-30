import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_ko.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'generated/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
      : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
    delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
  ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('ko')
  ];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'Smart Key'**
  String get appTitle;

  /// No description provided for @home.
  ///
  /// In en, this message translates to:
  /// **'Home'**
  String get home;

  /// No description provided for @activity.
  ///
  /// In en, this message translates to:
  /// **'Activity'**
  String get activity;

  /// No description provided for @settings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get settings;

  /// No description provided for @refresh.
  ///
  /// In en, this message translates to:
  /// **'Refresh'**
  String get refresh;

  /// No description provided for @statusCheckNeeded.
  ///
  /// In en, this message translates to:
  /// **'Status check needed'**
  String get statusCheckNeeded;

  /// No description provided for @smartKeyAvailable.
  ///
  /// In en, this message translates to:
  /// **'Smart Key ready'**
  String get smartKeyAvailable;

  /// No description provided for @setupCheckNeeded.
  ///
  /// In en, this message translates to:
  /// **'Check setup'**
  String get setupCheckNeeded;

  /// No description provided for @registrationPending.
  ///
  /// In en, this message translates to:
  /// **'Waiting for administrator approval'**
  String get registrationPending;

  /// No description provided for @readyToEnroll.
  ///
  /// In en, this message translates to:
  /// **'Ready to register this phone'**
  String get readyToEnroll;

  /// No description provided for @credentialRevoked.
  ///
  /// In en, this message translates to:
  /// **'Smart Key access revoked'**
  String get credentialRevoked;

  /// No description provided for @credentialExpired.
  ///
  /// In en, this message translates to:
  /// **'Smart Key access expired'**
  String get credentialExpired;

  /// No description provided for @registrationRequired.
  ///
  /// In en, this message translates to:
  /// **'Smart Key registration required'**
  String get registrationRequired;

  /// No description provided for @targetWaiting.
  ///
  /// In en, this message translates to:
  /// **'Waiting for Target'**
  String get targetWaiting;

  /// No description provided for @targetDetected.
  ///
  /// In en, this message translates to:
  /// **'Target detected'**
  String get targetDetected;

  /// No description provided for @targetAuthenticating.
  ///
  /// In en, this message translates to:
  /// **'Authenticating Smart Key'**
  String get targetAuthenticating;

  /// No description provided for @targetArmed.
  ///
  /// In en, this message translates to:
  /// **'Access ready - waiting for sensor approach'**
  String get targetArmed;

  /// No description provided for @targetFailed.
  ///
  /// In en, this message translates to:
  /// **'Target authentication failed'**
  String get targetFailed;

  /// No description provided for @automaticAccessDisabled.
  ///
  /// In en, this message translates to:
  /// **'Automatic access disabled'**
  String get automaticAccessDisabled;

  /// No description provided for @manualOpenRequesting.
  ///
  /// In en, this message translates to:
  /// **'Requesting a remote open command from the Backend.'**
  String get manualOpenRequesting;

  /// No description provided for @manualOpenCommandExecuted.
  ///
  /// In en, this message translates to:
  /// **'The Backend delivered the remote open command to MQTT. Physical door opening is not confirmed.'**
  String get manualOpenCommandExecuted;

  /// No description provided for @manualOpenOutcomeUnknown.
  ///
  /// In en, this message translates to:
  /// **'The remote delivery outcome is unknown. Do not retry automatically.'**
  String get manualOpenOutcomeUnknown;

  /// No description provided for @statusRefreshing.
  ///
  /// In en, this message translates to:
  /// **'Refreshing status.'**
  String get statusRefreshing;

  /// No description provided for @backendUnavailableRetry.
  ///
  /// In en, this message translates to:
  /// **'Could not reach the backend. Please try again shortly.'**
  String get backendUnavailableRetry;

  /// No description provided for @statusUpdated.
  ///
  /// In en, this message translates to:
  /// **'Latest status applied.'**
  String get statusUpdated;

  /// No description provided for @credentialEnrolling.
  ///
  /// In en, this message translates to:
  /// **'Registering this phone\'s Smart Key credential.'**
  String get credentialEnrolling;

  /// No description provided for @credentialEnrollmentComplete.
  ///
  /// In en, this message translates to:
  /// **'Smart Key registration completed.'**
  String get credentialEnrollmentComplete;

  /// No description provided for @bluetoothRequired.
  ///
  /// In en, this message translates to:
  /// **'Turn on Bluetooth and try again.'**
  String get bluetoothRequired;

  /// No description provided for @permissionsRequired.
  ///
  /// In en, this message translates to:
  /// **'Check the required permissions.'**
  String get permissionsRequired;

  /// No description provided for @batteryRestrictionRequired.
  ///
  /// In en, this message translates to:
  /// **'Remove the battery usage restriction.'**
  String get batteryRestrictionRequired;

  /// No description provided for @targetUnavailable.
  ///
  /// In en, this message translates to:
  /// **'No recently detected Target is available.'**
  String get targetUnavailable;

  /// No description provided for @smartKeyPermissionCheck.
  ///
  /// In en, this message translates to:
  /// **'Ask an administrator to check your Smart Key access.'**
  String get smartKeyPermissionCheck;

  /// No description provided for @targetResponseTimeout.
  ///
  /// In en, this message translates to:
  /// **'The Target response timed out.'**
  String get targetResponseTimeout;

  /// No description provided for @requestFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'The request did not complete. Check Advanced diagnostics.'**
  String get requestFailedGeneric;

  /// No description provided for @smartKeyAvailableDetail.
  ///
  /// In en, this message translates to:
  /// **'Keep this phone with you. Authentication starts automatically when you approach the Target.'**
  String get smartKeyAvailableDetail;

  /// No description provided for @backendStatusUnavailableDetail.
  ///
  /// In en, this message translates to:
  /// **'Backend status is unavailable. Local recovery and updates remain available.'**
  String get backendStatusUnavailableDetail;

  /// No description provided for @requestRegistrationDetail.
  ///
  /// In en, this message translates to:
  /// **'Enter registration details and request administrator approval.'**
  String get requestRegistrationDetail;

  /// No description provided for @waitForApprovalDetail.
  ///
  /// In en, this message translates to:
  /// **'This screen refreshes after approval.'**
  String get waitForApprovalDetail;

  /// No description provided for @enrollCredentialDetail.
  ///
  /// In en, this message translates to:
  /// **'Link this phone\'s secure key to the approved account.'**
  String get enrollCredentialDetail;

  /// No description provided for @waitForAclDetail.
  ///
  /// In en, this message translates to:
  /// **'Wait until the Target applies the latest access policy.'**
  String get waitForAclDetail;

  /// No description provided for @advancedDiagnosticsDetail.
  ///
  /// In en, this message translates to:
  /// **'Detailed status is available in Advanced diagnostics.'**
  String get advancedDiagnosticsDetail;

  /// No description provided for @requestRegistration.
  ///
  /// In en, this message translates to:
  /// **'Request registration'**
  String get requestRegistration;

  /// No description provided for @checkApprovalStatus.
  ///
  /// In en, this message translates to:
  /// **'Check approval'**
  String get checkApprovalStatus;

  /// No description provided for @registerThisPhone.
  ///
  /// In en, this message translates to:
  /// **'Register this phone'**
  String get registerThisPhone;

  /// No description provided for @checkRegistration.
  ///
  /// In en, this message translates to:
  /// **'Check registration'**
  String get checkRegistration;

  /// No description provided for @viewRenewalGuide.
  ///
  /// In en, this message translates to:
  /// **'View renewal guide'**
  String get viewRenewalGuide;

  /// No description provided for @refreshStatus.
  ///
  /// In en, this message translates to:
  /// **'Refresh status'**
  String get refreshStatus;

  /// No description provided for @requestOpenCommand.
  ///
  /// In en, this message translates to:
  /// **'Request open'**
  String get requestOpenCommand;

  /// No description provided for @checkAgain.
  ///
  /// In en, this message translates to:
  /// **'Check again'**
  String get checkAgain;

  /// No description provided for @processing.
  ///
  /// In en, this message translates to:
  /// **'Processing'**
  String get processing;

  /// No description provided for @noRecentDetection.
  ///
  /// In en, this message translates to:
  /// **'No recent detection'**
  String get noRecentDetection;

  /// No description provided for @recentDetection.
  ///
  /// In en, this message translates to:
  /// **'Last detected'**
  String get recentDetection;

  /// No description provided for @registrationInfo.
  ///
  /// In en, this message translates to:
  /// **'Registration information'**
  String get registrationInfo;

  /// No description provided for @registeredDoors.
  ///
  /// In en, this message translates to:
  /// **'Registered doors'**
  String get registeredDoors;

  /// No description provided for @checking.
  ///
  /// In en, this message translates to:
  /// **'Checking'**
  String get checking;

  /// No description provided for @currentVersion.
  ///
  /// In en, this message translates to:
  /// **'Installed version'**
  String get currentVersion;

  /// No description provided for @availableVersion.
  ///
  /// In en, this message translates to:
  /// **'Available version'**
  String get availableVersion;

  /// No description provided for @supportReport.
  ///
  /// In en, this message translates to:
  /// **'Support report'**
  String get supportReport;

  /// No description provided for @supportReportDescription.
  ///
  /// In en, this message translates to:
  /// **'Preview a bounded redacted report before copying it.'**
  String get supportReportDescription;

  /// No description provided for @advancedDiagnostics.
  ///
  /// In en, this message translates to:
  /// **'Advanced diagnostics'**
  String get advancedDiagnostics;

  /// No description provided for @copyConsent.
  ///
  /// In en, this message translates to:
  /// **'I reviewed this redacted report and consent to copy it.'**
  String get copyConsent;

  /// No description provided for @copyReport.
  ///
  /// In en, this message translates to:
  /// **'Copy report'**
  String get copyReport;

  /// No description provided for @reportCopied.
  ///
  /// In en, this message translates to:
  /// **'Redacted report copied'**
  String get reportCopied;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'ko'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'ko':
      return AppLocalizationsKo();
  }

  throw FlutterError(
      'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
      'an issue with the localizations generation tool. Please file an issue '
      'on GitHub with a reproducible sample app and the gen-l10n configuration '
      'that was used.');
}
