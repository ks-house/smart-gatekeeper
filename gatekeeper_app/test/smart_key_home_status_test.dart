import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/l10n/generated/app_localizations.dart';
import 'package:gatekeeper_app/screens/smart_key_home_screen.dart';
import 'package:gatekeeper_app/services/commercial_models.dart';
import 'package:gatekeeper_app/services/mobile_identity_service.dart';
import 'package:gatekeeper_app/services/update_checker.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

class FakeIdentity extends MobileIdentityService {
  Future<MobileIdentityStatus> Function()? readStatus;
  Future<MobilePersonalActivity> Function()? readActivity;

  MobileIdentityStatus value = const MobileIdentityStatus(
    enrollmentState: EnrollmentState.approved,
    accessReady: true,
    nextAction: 'none',
    doorCount: 1,
    targetSynced: true,
    aclVersion: 1,
  );

  @override
  Future<MobileIdentityStatus> status() async =>
      readStatus == null ? value : await readStatus!();
  @override
  Future<MobilePersonalActivity> activity({String? targetSessionId}) async =>
      readActivity == null
          ? MobilePersonalActivity.empty
          : await readActivity!();
  @override
  Future<Map<Object?, Object?>?> configureNativeDiagnostics({
    required bool enabled,
    required MobileIdentityStatus identity,
    required int sinceEpochMs,
    Map<String, Object?>? fieldTest,
  }) async =>
      null;
}

class FakeUpdates implements UpdateChecker {
  @override
  final downloadProgress = ValueNotifier<double?>(null);
  @override
  final stateNotifier = ValueNotifier<UpdateState>(UpdateState.idle);
  @override
  String? remoteVersion;
  @override
  String? lastFailureReason;
  @override
  UpdateState state = UpdateState.idle;
  @override
  bool updateMandatory = false;
  @override
  Future<UpdateExperience> readExperience() async => const UpdateExperience(
      installedVersion: 'test', installedBuild: '1', firstRunHealthy: true);
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
  @override
  Future<bool> checkForUpdates(
          {String? customVersionUrl, String? customDownloadUrl}) async =>
      false;
}

void main() {
  const channel =
      MethodChannel('com.kshouse.gatekeeper_app/ble_gatt_worker_health');
  late Map<String, Object?> health;
  late FakeIdentity identity;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    PackageInfo.setMockInitialValues(
        appName: 'Smart Key',
        packageName: 'com.kshouse.gatekeeper_app',
        version: 'test',
        buildNumber: '1',
        buildSignature: 'test');
    identity = FakeIdentity();
    health = {
      'featureEnabled': true,
      'credentialProvisioned': true,
      'localConsentValid': true,
      'wakeRegistrationRequested': true,
      'wakeRegistrationStatus': 'FOREGROUND_DISCOVERY',
      'locationServicesEnabled': true,
      'scanDiagnostics': {'alternativeStage': 'SCANNING'},
    };
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async => health);
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  Future<void> showHome(WidgetTester tester) async {
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    });
    await tester.pumpWidget(MaterialApp(
      locale: const Locale('ko'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      home: SmartKeyHomeScreen(
          identityService: identity, updateChecker: FakeUpdates()),
    ));
    await tester.pumpAndSettle();
  }

  Future<void> disposeHome(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
  }

  Icon headlineIcon(WidgetTester tester) => tester
      .widgetList<Icon>(find.byType(Icon))
      .singleWhere((icon) => icon.size == 48);

  testWidgets('actual home and settings show informational alternative scan',
      (tester) async {
    await showHome(tester);
    expect(find.text('Target 신호 확인 중'), findsOneWidget);
    expect(find.text('설정 확인 필요'), findsNothing);
    expect(find.textContaining('스캔 등록 확인 필요'), findsNothing);
    expect(find.textContaining('대체 스캔 중 · 기본 스캔 일시 전환'), findsOneWidget);
    expect(headlineIcon(tester).color, Colors.lightBlueAccent);
    await tester.tap(find.byIcon(Icons.settings));
    await tester.pumpAndSettle();
    expect(find.textContaining('Target 신호 확인 중'), findsOneWidget);
    expect(find.text('설정 확인 필요'), findsNothing);
    await disposeHome(tester);
  });

  testWidgets('home timer reflects restoration without stale scan warning',
      (tester) async {
    await showHome(tester);
    health.addAll({
      'handsFreeReady': true,
      'wakeRegistered': true,
      'wakeRegistrationStatus': 'REGISTERED'
    });
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(find.text('스마트키 설정 준비됨'), findsOneWidget);
    expect(find.textContaining('전면 대체 발견 확인 중'), findsNothing);
    expect(headlineIcon(tester).color, Colors.greenAccent);
    await disposeHome(tester);
  });

  testWidgets('real blocker stays amber even during alternative scan',
      (tester) async {
    health['currentBlockingReasonCode'] = 'LOCATION_SERVICES_DISABLED';
    health['locationServicesEnabled'] = false;
    await showHome(tester);
    expect(find.text('설정 확인 필요'), findsOneWidget);
    expect(headlineIcon(tester).color, Colors.amberAccent);
    expect(find.text('Target 신호 확인 중'), findsNothing);
    await disposeHome(tester);
  });

  testWidgets(
      'cleanup failure is distinct and restored history is not actionable',
      (tester) async {
    health['scanDiagnostics'] = {
      'alternativeStage': 'STOP_FAILED',
      'alternativeRestoreStatus': 'RESTORE_PENDING'
    };
    await showHome(tester);
    expect(find.text('기본 스캔 복원 확인 필요'), findsOneWidget);
    expect(headlineIcon(tester).color, Colors.amberAccent);
    health.addAll({
      'handsFreeReady': true,
      'wakeRegistered': true,
      'wakeRegistrationStatus': 'REGISTERED'
    });
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();
    expect(find.text('스마트키 설정 준비됨'), findsOneWidget);
    expect(find.textContaining('Bluetooth를 껐다 켜서 복구 필요'), findsNothing);
    await disposeHome(tester);
  });

  testWidgets('approved phone waits for ACL without asking to enroll again',
      (tester) async {
    identity.value = const MobileIdentityStatus(
      enrollmentState: EnrollmentState.approved,
      accessReady: false,
      nextAction: 'wait_for_acl',
      doorCount: 1,
      targetSynced: false,
      aclVersion: 7,
    );
    await showHome(tester);
    expect(find.text('출입 권한 동기화 대기'), findsOneWidget);
    expect(find.text('스마트키 등록 필요'), findsNothing);
    expect(find.text('상태 새로고침'), findsOneWidget);
    expect(headlineIcon(tester).color, Colors.amberAccent);
    await disposeHome(tester);
  });

  testWidgets('unavailable identity is not hidden by scan state',
      (tester) async {
    identity.value = MobileIdentityStatus.unavailable;
    await showHome(tester);
    expect(find.text('Target 신호 확인 중'), findsNothing);
    expect(headlineIcon(tester).color, Colors.amberAccent);
    await disposeHome(tester);
  });

  testWidgets('initial pending identity is checking rather than unavailable',
      (tester) async {
    final status = Completer<MobileIdentityStatus>();
    identity.readStatus = () => status.future;
    await showHome(tester);
    expect(find.text('상태 확인 중'), findsOneWidget);
    expect(find.text('상태 확인 필요'), findsNothing);
    expect(headlineIcon(tester).color, Colors.lightBlueAccent);

    status.complete(MobileIdentityStatus.unavailable);
    await tester.pumpAndSettle();
    expect(find.text('상태 확인 필요'), findsOneWidget);
    expect(headlineIcon(tester).color, Colors.amberAccent);
    await disposeHome(tester);
  });

  testWidgets('ready identity is visible while activity is still pending',
      (tester) async {
    final activity = Completer<MobilePersonalActivity>();
    identity.readActivity = () => activity.future;
    await showHome(tester);
    expect(find.text('Target 신호 확인 중'), findsOneWidget);
    expect(find.text('상태 확인 필요'), findsNothing);
    expect(find.text('문 열기'), findsOneWidget);

    var refreshFinished = false;
    final refresh = tester
        .widget<RefreshIndicator>(find.byType(RefreshIndicator).first)
        .onRefresh();
    unawaited(refresh.then((_) => refreshFinished = true));
    await tester.pumpAndSettle();
    expect(refreshFinished, isTrue);

    activity.completeError(StateError('activity unavailable'));
    await tester.pumpAndSettle();
    expect(find.text('Target 신호 확인 중'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeHome(tester);
  });

  testWidgets('late older status cannot replace a newer identity response',
      (tester) async {
    final older = Completer<MobileIdentityStatus>();
    identity.readStatus = () => older.future;
    await showHome(tester);

    identity.readStatus = null;
    await tester.pump(const Duration(seconds: 30));
    await tester.pumpAndSettle();
    expect(find.text('Target 신호 확인 중'), findsOneWidget);

    older.complete(MobileIdentityStatus.unavailable);
    await tester.pumpAndSettle();
    expect(find.text('Target 신호 확인 중'), findsOneWidget);
    expect(find.text('상태 확인 필요'), findsNothing);
    await disposeHome(tester);
  });

  testWidgets('identity completion after disposal is ignored', (tester) async {
    final status = Completer<MobileIdentityStatus>();
    identity.readStatus = () => status.future;
    await showHome(tester);
    await disposeHome(tester);
    status.complete(identity.value);
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('late older activity cannot replace newer lifecycle history',
      (tester) async {
    final older = Completer<MobilePersonalActivity>();
    identity.readActivity = () => older.future;
    await showHome(tester);

    identity.readActivity =
        () async => MobilePersonalActivity(lifecycleEvents: [
              MobileLifecycleEvent(
                eventRef: 'new-revocation',
                type: 'credential_revoked',
                createdAt: DateTime.utc(2026, 11, 4),
              ),
            ]);
    await tester.tap(find.byIcon(Icons.refresh));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.history));
    await tester.pumpAndSettle();
    expect(find.text('스마트키 권한 해제'), findsOneWidget);

    older.complete(MobilePersonalActivity(lifecycleEvents: [
      MobileLifecycleEvent(
        eventRef: 'old-approval',
        type: 'credential_approved',
        createdAt: DateTime.utc(2026, 11, 3),
      ),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('스마트키 권한 해제'), findsOneWidget);
    expect(find.text('스마트키 승인 완료'), findsNothing);
    await disposeHome(tester);
  });
}
