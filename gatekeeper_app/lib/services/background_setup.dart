import 'dart:io';

import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'foreground_service.dart';

abstract class BackgroundRequirementGateway {
  bool get requiresBackgroundLocation;

  Future<bool> areForegroundPermissionsGranted();
  Future<void> requestForegroundPermissions();
  Future<bool> isLocationWhenInUseGranted();
  Future<bool> isLocationAlwaysGranted();
  Future<void> requestLocationAlways();
  Future<bool> isBatteryOptimizationExempt();
  Future<void> requestBatteryOptimizationExemption();
}

class BackgroundSetupSnapshot {
  const BackgroundSetupSnapshot({
    required this.locationWhenInUseGranted,
    required this.locationAlwaysGranted,
    required this.batteryOptimizationExempt,
  });

  final bool locationWhenInUseGranted;
  final bool locationAlwaysGranted;
  final bool batteryOptimizationExempt;
}

class BackgroundSetupController {
  BackgroundSetupController(this.gateway);

  final BackgroundRequirementGateway gateway;
  bool _consentGranted = false;

  bool get consentGranted => _consentGranted;

  void grantConsent() {
    _consentGranted = true;
  }

  Future<BackgroundSetupSnapshot> evaluate({
    required bool requestMissing,
  }) async {
    var locationWhenInUse = await gateway.isLocationWhenInUseGranted();
    final foregroundPermissionsGranted =
        await gateway.areForegroundPermissionsGranted();
    var locationAlways = await gateway.isLocationAlwaysGranted();
    var batteryExempt = await gateway.isBatteryOptimizationExempt();

    if (!_consentGranted || !requestMissing) {
      return BackgroundSetupSnapshot(
        locationWhenInUseGranted: locationWhenInUse,
        locationAlwaysGranted: locationAlways,
        batteryOptimizationExempt: batteryExempt,
      );
    }

    if (!foregroundPermissionsGranted) {
      await gateway.requestForegroundPermissions();
      locationWhenInUse = await gateway.isLocationWhenInUseGranted();
    }
    if (locationWhenInUse &&
        gateway.requiresBackgroundLocation &&
        !locationAlways) {
      await gateway.requestLocationAlways();
      locationAlways = await gateway.isLocationAlwaysGranted();
    }
    if (!batteryExempt) {
      await gateway.requestBatteryOptimizationExemption();
      batteryExempt = await gateway.isBatteryOptimizationExempt();
    }

    return BackgroundSetupSnapshot(
      locationWhenInUseGranted: locationWhenInUse,
      locationAlwaysGranted: locationAlways,
      batteryOptimizationExempt: batteryExempt,
    );
  }
}

class PermissionBackgroundRequirementGateway
    implements BackgroundRequirementGateway {
  PermissionBackgroundRequirementGateway({required this.androidSdkInt});

  final int androidSdkInt;

  @override
  bool get requiresBackgroundLocation =>
      !Platform.isAndroid || androidSdkInt >= 29;

  @override
  Future<bool> areForegroundPermissionsGranted() async {
    if (!await Permission.locationWhenInUse.isGranted) return false;
    if ((!Platform.isAndroid || androidSdkInt >= 31) &&
        (!await Permission.bluetoothScan.isGranted ||
            !await Permission.bluetoothConnect.isGranted)) {
      return false;
    }
    if ((!Platform.isAndroid || androidSdkInt >= 33) &&
        !await Permission.notification.isGranted) {
      return false;
    }
    return true;
  }

  @override
  Future<bool> isBatteryOptimizationExempt() =>
      ForegroundServiceManager.ensureBatteryOptimizationExemption(
        requestIfMissing: false,
      );

  @override
  Future<bool> isLocationAlwaysGranted() => Permission.locationAlways.isGranted;

  @override
  Future<bool> isLocationWhenInUseGranted() =>
      Permission.locationWhenInUse.isGranted;

  @override
  Future<void> requestBatteryOptimizationExemption() =>
      ForegroundServiceManager.requestBatteryOptimizationExemption();

  @override
  Future<void> requestForegroundPermissions() async {
    final permissions = <Permission>[Permission.locationWhenInUse];
    if (!Platform.isAndroid || androidSdkInt >= 31) {
      permissions.addAll([
        Permission.bluetoothScan,
        Permission.bluetoothConnect,
      ]);
    }
    if (!Platform.isAndroid || androidSdkInt >= 33) {
      permissions.add(Permission.notification);
    }
    await permissions.request();
  }

  @override
  Future<void> requestLocationAlways() async {
    await Permission.locationAlways.request();
  }
}

class BackgroundConsentStore {
  static const _key = 'background_requirements_consent_v1';

  Future<bool> isGranted() async {
    final preferences = await SharedPreferences.getInstance();
    return preferences.getBool(_key) == true;
  }

  Future<void> grant() async {
    final preferences = await SharedPreferences.getInstance();
    final stored = await preferences.setBool(_key, true);
    if (!stored) {
      throw StateError('BACKGROUND_CONSENT_STORAGE_FAILED');
    }
  }
}
