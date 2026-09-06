import 'dart:io';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/l10n/generated/app_localizations.dart';
import 'package:gatekeeper_app/screens/support_report_screen.dart';
import 'package:gatekeeper_app/services/commercial_models.dart';
import 'package:gatekeeper_app/services/field_diagnostics_service.dart';
import 'package:gatekeeper_app/services/mobile_identity_service.dart';
import 'package:gatekeeper_app/services/native_gatt_worker_health.dart';
import 'package:gatekeeper_app/services/support_report_service.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
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

    expect(report, contains('sgk-mobile-support-v2'));
    expect(report, contains('bundle_ref'));
    expect(report, contains('"wake_registration_requested": true'));
    expect(report, contains('"wake_registration_reconciled": false'));
    expect(report, contains('"wake_registration_status": "RECONCILING"'));
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

  test('field diagnostics stay opt-in and markers clear only by matching ref',
      () async {
    final store = FieldDiagnosticsStore();
    expect(await store.uploadEnabled(), isFalse);
    final marker = await store.startMarker(
      now: DateTime.utc(2026, 9, 5, 1),
      duration: const Duration(minutes: 10),
    );
    expect(marker.ref, matches(RegExp(r'^[0-9a-f]{16}$')));
    await store.clearMarker('0000000000000000');
    expect((await store.readMarker())?.ref, marker.ref);
    await store.clearMarker(marker.ref);
    expect(await store.readMarker(), isNull);
    await store.recordUploadError('HTTP_422');
    expect(await store.lastUploadError(), 'HTTP_422');
    expect(await store.lastUploadSuccess(), isNull);
    await store.markUploaded('a' * 32);
    expect(await store.lastUploadError(), isNull);
    expect(await store.lastUploadSuccess(), isNotNull);
  });

  test('real report producer agrees with shared backend fixture', () async {
    final fixture = jsonDecode(
        File('test/fixtures/mobile_support_v2.json').readAsStringSync()) as Map;
    final report = await SupportReportService(nativeBridge: _ContractBridge())
        .buildMap(identity: identity, health: null);
    final native = report['native'] as Map;
    for (final entry in (fixture['native'] as Map).entries) {
      expect(native[entry.key], entry.value, reason: '${entry.key}');
    }
    expect(report['app'], fixture['app']);
    expect(report['identity'], fixture['identity']);
    expect(report['wake_events'], fixture['wake_events']);
    expect(report['sessions'], fixture['sessions']);
  });

  test('dense full report fits ingest byte budget and keeps newest evidence',
      () async {
    final report = await SupportReportService(nativeBridge: _DenseBridge())
        .buildMap(identity: identity, health: null);
    expect(utf8.encode(jsonEncode(report)).length, lessThan(64 * 1024));
    final sessions = report['sessions'] as List;
    final wakes = report['wake_events'] as List;
    expect(sessions.length + wakes.length, lessThan(150));
    expect(wakes.first['received_epoch_ms'], 1788676100099);
    expect(wakes, hasLength(100)); // Older sessions are removed first.
  });

  testWidgets('support copy requires explicit preview consent', (tester) async {
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('ko'),
      home: SupportReportScreen(
        identity: identity,
        health: null,
        service: _SupportReportServiceFake(),
      ),
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

  test(
      'clear hides old diagnostics but preserves consent and operational ledger',
      () async {
    final store = FieldDiagnosticsStore();
    final bridge = _DiagnosticsBridgeFake();
    final service =
        SupportReportService(nativeBridge: bridge, diagnosticsStore: store);
    await store.setUploadEnabled(true);
    await store.startMarker();
    final before = await service.buildMap(identity: identity, health: null);
    expect((before['sessions'] as List).length, 50);
    final compact =
        jsonDecode(await service.build(identity: identity, health: null))
            as Map;
    expect((compact['sessions'] as List).length, 10);
    expect((compact['wake_events'] as List).length, 20);
    expect((compact['sessions'] as List).first['updated_epoch_ms'],
        bridge.now + 50);

    await store.clearReportHistory(
        now: DateTime.fromMillisecondsSinceEpoch(bridge.now + 100));
    final cleared = await service.buildMap(identity: identity, health: null);
    expect(cleared['sessions'], isEmpty);
    expect(cleared['wake_events'], isEmpty);
    expect(cleared['field_test'], isNull);
    expect(await store.uploadEnabled(), isTrue);
    // The source ledger is untouched, including an unresolved proof row.
    expect((await bridge.readRecentDiagnostics())['sessions'], hasLength(50));
    bridge.now += 1000;
    expect(
        (await service.buildMap(identity: identity, health: null))['sessions'],
        hasLength(50));
  });

  testWidgets(
      'report actions stay above Android navigation with long content and clear requires confirmation',
      (tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    tester.view.padding = const FakeViewPadding(bottom: 48);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPadding);
    final service = _SupportReportServiceFake();
    await tester.pumpWidget(MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('ko'),
      home: SupportReportScreen(
          identity: identity, health: null, service: service),
    ));
    await tester.pumpAndSettle();
    final copy = find.byKey(const Key('copy-redacted-support-report'));
    final clear = find.byKey(const Key('clear-support-report'));
    expect(tester.getBottomRight(copy).dy, lessThanOrEqualTo(592));
    expect(tester.getBottomRight(clear).dy, lessThanOrEqualTo(592));
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pump();
    await tester.tap(clear);
    await tester.pumpAndSettle();
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();
    expect(service.clears, 0);
    await tester.tap(clear);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('confirm-clear-support-report')));
    await tester.pumpAndSettle();
    expect(service.clears, 1);
    expect(tester.widget<FilledButton>(copy).onPressed, isNull);
    expect(tester.takeException(), isNull);
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

class _ContractBridge extends NativeGattWorkerHealthBridge {
  @override
  Future<NativeGattWorkerHealth> read() async =>
      NativeGattWorkerHealth.fromMap({
        'healthy': false,
        'handsFreeReady': true,
        'wakeRegistered': true,
        'wakeRegistrationRequested': true,
        'wakeRegistrationReconciled': true,
        'wakeRegistrationStatus': 'registered',
        'lastReasonCode': 'GATT_DISCONNECTED',
      });
  @override
  Future<Map<Object?, Object?>> readRecentDiagnostics() async => {
        'androidSdk': 36,
        'sessions': [],
        'wakeEvents': [
          {
            'source': 'BLE_SCAN',
            'success': true,
            'receivedEpochMs': 1788676102363,
            'strongestRssi': 127,
            'screenInteractive': false,
          }
        ],
      };
}

class _DenseBridge extends _ContractBridge {
  @override
  Future<Map<Object?, Object?>> readRecentDiagnostics() async => {
        'androidSdk': 36,
        'sessions': List.generate(
            50,
            (i) => {
                  'sessionId': 'session-$i',
                  'createdEpochMs': 1788676000000 + i,
                  'updatedEpochMs': 1788676000000 + i,
                  'state': 'FAILED',
                  'reasonCode': 'GATT_DISCONNECTED',
                  'targetReasonName': 'A' * 64,
                  'transportReason': 'B' * 64,
                  'latencyMs': 10000,
                  'targetSessionId': 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
                  'gattPerformance': {
                    'connectSetupMs': 10000,
                    'negotiatedMtu': 256,
                    'mtuStatus': 'ACCEPTED',
                    'highPriorityRequested': true
                  },
                }),
        'wakeEvents': List.generate(
            100,
            (i) => {
                  'source': 'BLE_SCAN',
                  'processRef': 'a' * 16,
                  'success': true,
                  'receivedEpochMs': 1788676100000 + i,
                  'receivedElapsedMs': 2214801056,
                  'callbackLatencyMs': 12.345678,
                  'strongestRssi': -95,
                  'screenInteractive': false,
                  'resultCount': 1,
                  'callbackType': 2,
                  'errorCode': 0,
                }),
      };
}

class _SupportReportServiceFake extends SupportReportService {
  int clears = 0;
  @override
  Future<void> clearHistory() async {
    clears++;
  }

  @override
  Future<String> build({
    required MobileIdentityStatus identity,
    required NativeGattWorkerHealth? health,
    bool fullHistory = false,
  }) async =>
      List.filled(100, '{"schema":"sgk-mobile-support-v2"}').join('\n');
}

class _DiagnosticsBridgeFake extends NativeGattWorkerHealthBridge {
  int now = DateTime.now().millisecondsSinceEpoch;
  @override
  Future<Map<Object?, Object?>> readRecentDiagnostics() async => {
        'sessions': List.generate(
            50,
            (index) => {
                  'sessionId': 'fixture-$index',
                  'updatedEpochMs': now + index + 1,
                  'state': 'PROOF_UNCERTAIN',
                }),
        'wakeEvents': List.generate(
            100,
            (index) => {
                  'receivedEpochMs': now + index + 1,
                  'source': 'BLE_SCAN',
                }),
      };
}
