import 'package:shared_preferences/shared_preferences.dart';

class FeatureFlagService {
  static const String keyEnableHardwarelessRc = 'ENABLE_HARDWARELESS_RC';
  static const String keyEnableLegacyPrearm = 'ENABLE_LEGACY_PREARM';
  static const String keyRemoteKillSwitch = 'REMOTE_KILL_SWITCH';

  static final FeatureFlagService _instance = FeatureFlagService._internal();
  factory FeatureFlagService() => _instance;
  FeatureFlagService._internal();

  bool enableHardwarelessRc = true;
  bool enableLegacyPrearm = false; // Interlocked: OFF when Hardwareless is ON to prevent dual ARM
  bool remoteKillSwitch = false;

  Future<void> loadFlags() async {
    final prefs = await SharedPreferences.getInstance();
    enableHardwarelessRc = prefs.getBool(keyEnableHardwarelessRc) ?? true;
    enableLegacyPrearm = prefs.getBool(keyEnableLegacyPrearm) ?? false;
    remoteKillSwitch = prefs.getBool(keyRemoteKillSwitch) ?? false;

    // Enforce strict interlock on load: dual ARM is forbidden
    if (enableHardwarelessRc && enableLegacyPrearm) {
      enableLegacyPrearm = false;
    }
  }

  Future<void> updateFlags({
    required bool hardwarelessRc,
    required bool legacyPrearm,
    required bool killSwitch,
  }) async {
    // Interlock: enforce legacy OR hardwareless, preventing dual/duplicate ARM triggers
    if (hardwarelessRc && legacyPrearm) {
      legacyPrearm = false;
    }

    enableHardwarelessRc = hardwarelessRc;
    enableLegacyPrearm = legacyPrearm;
    remoteKillSwitch = killSwitch;

    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(keyEnableHardwarelessRc, enableHardwarelessRc);
    await prefs.setBool(keyEnableLegacyPrearm, enableLegacyPrearm);
    await prefs.setBool(keyRemoteKillSwitch, remoteKillSwitch);
  }

  Future<void> rollbackToLegacy() async {
    await updateFlags(
      hardwarelessRc: false,
      legacyPrearm: true,
      killSwitch: false,
    );
  }

  Future<void> triggerKillSwitch() async {
    await updateFlags(
      hardwarelessRc: false,
      legacyPrearm: false,
      killSwitch: true,
    );
  }
}
