import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/screens/background_disclosure_screen.dart';
import 'package:gatekeeper_app/screens/recovery_shell_screen.dart';
import 'package:gatekeeper_app/services/background_setup.dart';

class FakeBackgroundRequirementGateway implements BackgroundRequirementGateway {
  FakeBackgroundRequirementGateway({
    this.requiresBackgroundLocation = true,
    this.locationWhenInUse = false,
    bool? foregroundPermissionsGranted,
    this.locationAlways = false,
    this.batteryExempt = false,
    this.grantForegroundOnRequest = false,
    this.grantAlwaysOnRequest = false,
    this.grantBatteryOnRequest = false,
  }) : foregroundPermissionsGranted =
            foregroundPermissionsGranted ?? locationWhenInUse;

  @override
  final bool requiresBackgroundLocation;
  bool locationWhenInUse;
  bool foregroundPermissionsGranted;
  bool locationAlways;
  bool batteryExempt;
  bool grantForegroundOnRequest;
  bool grantAlwaysOnRequest;
  bool grantBatteryOnRequest;
  int foregroundRequests = 0;
  int alwaysRequests = 0;
  int batteryRequests = 0;

  @override
  Future<bool> areForegroundPermissionsGranted() async =>
      foregroundPermissionsGranted;

  @override
  Future<bool> isBatteryOptimizationExempt() async => batteryExempt;

  @override
  Future<bool> isLocationAlwaysGranted() async => locationAlways;

  @override
  Future<bool> isLocationWhenInUseGranted() async => locationWhenInUse;

  @override
  Future<void> requestBatteryOptimizationExemption() async {
    batteryRequests++;
    if (grantBatteryOnRequest) batteryExempt = true;
  }

  @override
  Future<void> requestForegroundPermissions() async {
    foregroundRequests++;
    if (grantForegroundOnRequest) {
      foregroundPermissionsGranted = true;
      locationWhenInUse = true;
    }
  }

  @override
  Future<void> requestLocationAlways() async {
    alwaysRequests++;
    if (grantAlwaysOnRequest) locationAlways = true;
  }
}

void main() {
  test('consent gate performs zero requests before explicit consent', () async {
    final gateway = FakeBackgroundRequirementGateway();
    final controller = BackgroundSetupController(gateway);

    final snapshot = await controller.evaluate(requestMissing: true);

    expect(snapshot.locationWhenInUseGranted, isFalse);
    expect(gateway.foregroundRequests, 0);
    expect(gateway.alwaysRequests, 0);
    expect(gateway.batteryRequests, 0);
  });

  test('consent requests each missing Android requirement exactly once',
      () async {
    final gateway = FakeBackgroundRequirementGateway(
      grantForegroundOnRequest: true,
      grantAlwaysOnRequest: true,
      grantBatteryOnRequest: true,
    );
    final controller = BackgroundSetupController(gateway)..grantConsent();

    final snapshot = await controller.evaluate(requestMissing: true);

    expect(snapshot.locationWhenInUseGranted, isTrue);
    expect(snapshot.locationAlwaysGranted, isTrue);
    expect(snapshot.batteryOptimizationExempt, isTrue);
    expect(gateway.foregroundRequests, 1);
    expect(gateway.alwaysRequests, 1);
    expect(gateway.batteryRequests, 1);
  });

  test('denied background requirements remain retryable', () async {
    final gateway = FakeBackgroundRequirementGateway(
      locationWhenInUse: true,
      locationAlways: false,
      batteryExempt: false,
    );
    final controller = BackgroundSetupController(gateway)..grantConsent();

    final first = await controller.evaluate(requestMissing: true);
    expect(first.locationAlwaysGranted, isFalse);
    expect(first.batteryOptimizationExempt, isFalse);
    expect(gateway.alwaysRequests, 1);
    expect(gateway.batteryRequests, 1);

    gateway.grantAlwaysOnRequest = true;
    gateway.grantBatteryOnRequest = true;
    final retry = await controller.evaluate(requestMissing: true);
    expect(retry.locationAlwaysGranted, isTrue);
    expect(retry.batteryOptimizationExempt, isTrue);
    expect(gateway.alwaysRequests, 2);
    expect(gateway.batteryRequests, 2);
  });

  test('already granted requirements are idempotent and never re-requested',
      () async {
    final gateway = FakeBackgroundRequirementGateway(
      locationWhenInUse: true,
      locationAlways: true,
      batteryExempt: true,
    );
    final controller = BackgroundSetupController(gateway)..grantConsent();

    await controller.evaluate(requestMissing: true);
    await controller.evaluate(requestMissing: true);

    expect(gateway.foregroundRequests, 0);
    expect(gateway.alwaysRequests, 0);
    expect(gateway.batteryRequests, 0);
  });

  testWidgets('disclosure requires an explicit action and supports deferral',
      (tester) async {
    var consentCalls = 0;
    var deferCalls = 0;
    await tester.pumpWidget(MaterialApp(
      home: BackgroundDisclosureScreen(
        onConsent: () async {
          consentCalls++;
        },
        onDefer: () => deferCalls++,
      ),
    ));

    expect(find.text('동의 후에만 시스템 요청을 시작합니다'), findsOneWidget);
    expect(consentCalls, 0);
    expect(deferCalls, 0);

    final deferButton = find.byKey(const Key('background-consent-defer'));
    await tester.ensureVisible(deferButton);
    await tester.tap(deferButton);
    await tester.pump();
    expect(deferCalls, 1);
    expect(consentCalls, 0);

    final acceptButton = find.byKey(const Key('background-consent-accept'));
    await tester.ensureVisible(acceptButton);
    await tester.tap(acceptButton);
    await tester.pump();
    expect(consentCalls, 1);
  });

  testWidgets(
      'recovery shell keeps manual update diagnostics settings and retry reachable',
      (tester) async {
    var retries = 0;
    await tester.pumpWidget(MaterialApp(
      home: RecoveryShellScreen(
        status: 'Blocked',
        missing: const <String>['Bluetooth permission'],
        onRetrySetup: () async {
          retries++;
        },
      ),
    ));
    await tester.pump();

    expect(find.text('Smart Key 설정 및 진단'), findsOneWidget);
    expect(find.text('Check verified app update'), findsOneWidget);
    expect(find.text('Open Android settings'), findsOneWidget);
    final retry = find.byKey(const Key('retry-background-setup'));
    expect(retry, findsOneWidget);
    await tester.tap(retry);
    await tester.pump();
    expect(retries, 1);
  });

  test('battery request seam uses the dedicated exemption intent API', () {
    final source =
        File('lib/services/foreground_service.dart').readAsStringSync();
    expect(source, contains("'requestIgnoreBatteryOptimizations'"));
    expect(
      source.substring(
        source.indexOf('requestBatteryOptimizationExemption()'),
        source.indexOf('static Future<void> stopService()'),
      ),
      isNot(contains('openAppSettings')),
    );
  });
}
