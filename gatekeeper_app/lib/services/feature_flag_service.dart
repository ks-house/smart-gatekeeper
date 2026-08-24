import 'package:shared_preferences/shared_preferences.dart';

class FeatureFlagService {
  static const String keyEnableLegacyPrearm = 'ENABLE_LEGACY_PREARM';
  static const String keyRemoteKillSwitch = 'REMOTE_KILL_SWITCH';

  static final FeatureFlagService _instance = FeatureFlagService._internal();
  factory FeatureFlagService() => _instance;
  FeatureFlagService._internal();

  bool enableLegacyPrearm = false;
  bool remoteKillSwitch = false;

  Future<void> loadFlags() async {
    final prefs = await SharedPreferences.getInstance();
    enableLegacyPrearm = prefs.getBool(keyEnableLegacyPrearm) ?? false;
    remoteKillSwitch = prefs.getBool(keyRemoteKillSwitch) ?? false;

    // Native GATT ownership is authoritative. Remove the obsolete Flutter-only
    // flag so it can no longer disagree with native health/consent state.
    await prefs.remove('ENABLE_HARDWARELESS_RC');
  }

  Future<void> updateFlags({
    required bool legacyPrearm,
    required bool killSwitch,
  }) async {
    enableLegacyPrearm = legacyPrearm;
    remoteKillSwitch = killSwitch;

    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(keyEnableLegacyPrearm, enableLegacyPrearm);
    await prefs.setBool(keyRemoteKillSwitch, remoteKillSwitch);
  }

  Future<void> rollbackToLegacy() async {
    await updateFlags(
      legacyPrearm: true,
      killSwitch: false,
    );
  }

  Future<void> triggerKillSwitch() async {
    await updateFlags(
      legacyPrearm: false,
      killSwitch: true,
    );
  }
}
