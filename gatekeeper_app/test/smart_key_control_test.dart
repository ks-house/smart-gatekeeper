import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:gatekeeper_app/services/feature_flag_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('1-Tap local control awaits terminal action-2 open result', () {
    final source =
        File('lib/screens/smart_key_control_screen.dart').readAsStringSync();

    expect(
      source,
      contains('final result = await _healthBridge.triggerLocalGattOpen();'),
    );
    expect(source, contains('ManualOpenOutcome.fromNative(result)'));
    expect(source, contains('✅ 개방 명령 실행 완료'));
    expect(source, contains('실제 문 열림은 별도 확인'));
    expect(source, isNot(contains('문이 열렸습니다')));
    expect(source, isNot(contains('_healthBridge.triggerLocalGattRetry();')));
    expect(source, isNot(contains('durable queue에 등록되었습니다')));
  });

  test('all manual action entry points use the truthful outcome projection',
      () {
    final home =
        File('lib/screens/smart_key_home_screen.dart').readAsStringSync();
    final web = File('lib/screens/web_view_screen.dart').readAsStringSync();

    expect(home, contains('ManualOpenOutcome.fromNative(result)'));
    expect(home, contains('manualOpenCommandExecuted'));
    expect(home, contains('manualOpenOutcomeUnknown'));
    expect(home, contains('recordManualOpenResult(result)'));
    expect(web, contains('ManualOpenOutcome.fromNative(result)'));
    expect(web, contains('outcome.commandExecuted'));
    expect(web, contains('recordManualOpenResult(result)'));
    expect(home, isNot(contains('문 열림을 Target에서 확인했습니다')));
    expect(web, isNot(contains('문이 열렸습니다')));
  });

  test('credential card uses native authority without local tenant fiction',
      () {
    final source =
        File('lib/screens/smart_key_control_screen.dart').readAsStringSync();

    expect(source, contains('health.credentialProvisioned'));
    expect(source, contains('health.localConsentValid'));
    expect(source, contains('health.lastActiveAclVersion'));
    expect(source, contains('Tenant 승인은 Backend가 관리합니다.'));
    expect(source, isNot(contains('_credentialService.approvalStatus')));
    expect(source, isNot(contains('ACL Lease Version')));
    expect(source, isNot(contains('Tenant 승인 요청 제출')));
    expect(source, isNot(contains('saveRegistrationRequest')));
  });

  group('FeatureFlagService Unit Tests', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('obsolete Flutter hardwareless flag is removed on load', () async {
      SharedPreferences.setMockInitialValues({
        'ENABLE_HARDWARELESS_RC': true,
        FeatureFlagService.keyEnableLegacyPrearm: true,
      });
      final flagService = FeatureFlagService();
      await flagService.loadFlags();
      final prefs = await SharedPreferences.getInstance();

      expect(prefs.containsKey('ENABLE_HARDWARELESS_RC'), isFalse);
      expect(flagService.enableLegacyPrearm, isTrue);
      expect(flagService.remoteKillSwitch, isFalse);
    });

    test('rollback to legacy sets legacyPrearm to true', () async {
      final flagService = FeatureFlagService();
      await flagService.rollbackToLegacy();

      expect(flagService.enableLegacyPrearm, isTrue);
      expect(flagService.remoteKillSwitch, isFalse);
    });

    test('trigger kill switch disables legacy prearm', () async {
      final flagService = FeatureFlagService();
      await flagService.triggerKillSwitch();

      expect(flagService.enableLegacyPrearm, isFalse);
      expect(flagService.remoteKillSwitch, isTrue);
    });
  });
}
