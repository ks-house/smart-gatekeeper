import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/l10n/generated/app_localizations.dart';
import 'package:gatekeeper_app/screens/support_report_screen.dart';
import 'package:gatekeeper_app/services/commercial_models.dart';
import 'package:gatekeeper_app/services/mobile_identity_service.dart';
import 'package:gatekeeper_app/services/native_gatt_worker_health.dart';
import 'package:gatekeeper_app/services/support_report_service.dart';
import 'package:package_info_plus/package_info_plus.dart';

void main() {
  setUp(() {
    PackageInfo.setMockInitialValues(
      appName: 'Smart Key',
      packageName: 'com.kshouse.gatekeeper_app',
      version: '1.2.3',
      buildNumber: '456',
      buildSignature: 'ignored',
    );
  });

  const identity = MobileIdentityStatus(
    enrollmentState: EnrollmentState.approved,
    accessReady: true,
    nextAction: 'none',
    doorCount: 1,
    targetSynced: true,
    tenantLabel: 'must-not-be-exported',
    aclVersion: 12,
  );

  test('support report is bounded and excludes personal and secret fields',
      () async {
    final health = NativeGattWorkerHealth.fromMap(<Object?, Object?>{
      'healthy': true,
      'handsFreeReady': true,
      'wakeRegistered': false,
      'wakeRegistrationRequested': true,
      'wakeRegistrationReconciled': false,
      'wakeRegistrationStatus': 'reconciling',
      'wakeRegistrationAttemptedAtEpochMs': 1724930000000,
      'lastReasonCode': 'NONE',
      'lastSession': <Object?, Object?>{
        'id': 'private-session-id',
        'state': 'SUCCEEDED',
      },
    });

    final report =
        await SupportReportService().build(identity: identity, health: health);

    expect(report, contains('sgk-mobile-support-v1'));
    expect(report, contains('event_ref'));
    expect(report, contains('"wake_registration_requested": true'));
    expect(report, contains('"wake_registration_reconciled": false'));
    expect(report, contains('"wake_registration_status": "reconciling"'));
    expect(report, isNot(contains('private-session-id')));
    expect(report, isNot(contains('must-not-be-exported')));
    for (final forbidden in <String>[
      'name',
      'unit',
      'mac',
      'token',
      'private_key',
      'public_key',
      'proof',
    ]) {
      expect(report.toLowerCase(), isNot(contains('"$forbidden"')));
    }
  });

  testWidgets('support copy requires explicit preview consent', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: Locale('ko'),
      home: SupportReportScreen(identity: identity, health: null),
    ));
    await tester.pumpAndSettle();

    await tester.drag(find.byType(ListView), const Offset(0, -800));
    await tester.pumpAndSettle();

    final copy = find.byKey(const Key('copy-redacted-support-report'));
    expect(copy, findsOneWidget);
    expect(tester.widget<FilledButton>(copy).onPressed, isNull);
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pump();
    expect(tester.widget<FilledButton>(copy).onPressed, isNotNull);
  });

  test('normal shell has generated ko and en resources plus accessible routes',
      () {
    final pubspec = File('pubspec.yaml').readAsStringSync();
    final home =
        File('lib/screens/smart_key_home_screen.dart').readAsStringSync();
    final english = File('lib/l10n/app_en.arb').readAsStringSync();
    final korean = File('lib/l10n/app_ko.arb').readAsStringSync();

    expect(pubspec, contains('generate: true'));
    expect(english, contains('"supportReport"'));
    expect(korean, contains('"supportReport"'));
    expect(home, contains('AppLocalizations.of(context)'));
    expect(home, contains('Semantics('));
    expect(home, contains('SupportReportScreen('));
    expect(home, contains('readExperience()'));
  });
}
