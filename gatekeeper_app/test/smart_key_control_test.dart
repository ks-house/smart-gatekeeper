import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:gatekeeper_app/services/feature_flag_service.dart';
import 'package:gatekeeper_app/services/credential_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('FeatureFlagService Unit Tests', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('interlock prevents simultaneous hardwareless and legacy prearm', () async {
      final flagService = FeatureFlagService();
      await flagService.updateFlags(
        hardwarelessRc: true,
        legacyPrearm: true, // Should be forced false by interlock
        killSwitch: false,
      );

      expect(flagService.enableHardwarelessRc, isTrue);
      expect(flagService.enableLegacyPrearm, isFalse);
      expect(flagService.remoteKillSwitch, isFalse);
    });

    test('rollback to legacy sets legacyPrearm to true and hardwareless to false', () async {
      final flagService = FeatureFlagService();
      await flagService.rollbackToLegacy();

      expect(flagService.enableHardwarelessRc, isFalse);
      expect(flagService.enableLegacyPrearm, isTrue);
      expect(flagService.remoteKillSwitch, isFalse);
    });

    test('trigger kill switch disables hardwareless and legacy prearm', () async {
      final flagService = FeatureFlagService();
      await flagService.triggerKillSwitch();

      expect(flagService.enableHardwarelessRc, isFalse);
      expect(flagService.enableLegacyPrearm, isFalse);
      expect(flagService.remoteKillSwitch, isTrue);
    });
  });

  group('CredentialService Unit Tests', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('saveRegistrationRequest sets status to pending', () async {
      final service = CredentialService();
      await service.saveRegistrationRequest('Hong Gildong', '101');

      expect(service.tenantName, equals('Hong Gildong'));
      expect(service.roomNumber, equals('101'));
      expect(service.approvalStatus, equals(TenantApprovalStatus.pending));
    });

    test('updateStatus updates status correctly', () async {
      final service = CredentialService();
      await service.updateStatus(TenantApprovalStatus.approved);

      expect(service.approvalStatus, equals(TenantApprovalStatus.approved));
    });
  });
}
