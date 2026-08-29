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
