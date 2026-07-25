import 'dart:io';
import 'package:device_info_plus/device_info_plus';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class DeviceIdService {
  static String? _cachedDeviceId;

  /// 영구 기기 고유 식별 코드 (ANDROID_ID / Hardware ID 기반)
  static Future<String> getDeviceId() async {
    if (_cachedDeviceId != null && _cachedDeviceId!.isNotEmpty) {
      return _cachedDeviceId!;
    }

    try {
      final prefs = await SharedPreferences.getInstance();
      String? storedId = prefs.getString('gatekeeper_persistent_device_id');

      if (storedId != null && storedId.isNotEmpty) {
        _cachedDeviceId = storedId;
        return storedId;
      }
    } catch (e) {
      debugPrint('[DeviceIdService] SharedPreferences 읽기 예외: $e');
    }

    // 안드로이드/iOS 하드웨어 고유 ID 추출
    String hardwareId = '';
    try {
      final deviceInfo = DeviceInfoPlugin();
      if (Platform.isAndroid) {
        final androidInfo = await deviceInfo.androidInfo;
        final rawId = androidInfo.id.replaceAll(RegExp(r'[^a-zA-Z0-9]'), '').toUpperCase();
        hardwareId = 'DEV-${rawId.length > 12 ? rawId.substring(0, 12) : rawId}';
      } else if (Platform.isIOS) {
        final iosInfo = await deviceInfo.iosInfo;
        final rawId = (iosInfo.identifierForVendor ?? '').replaceAll(RegExp(r'[^a-zA-Z0-9]'), '').toUpperCase();
        hardwareId = 'DEV-${rawId.length > 12 ? rawId.substring(0, 12) : rawId}';
      }
    } catch (e) {
      debugPrint('[DeviceIdService] 하드웨어 ID 읽기 실패: $e');
    }

    if (hardwareId.isEmpty || hardwareId == 'DEV-') {
      final randomId = DateTime.now().millisecondsSinceEpoch.toRadixString(36).toUpperCase();
      hardwareId = 'DEV-$randomId';
    }

    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('gatekeeper_persistent_device_id', hardwareId);
    } catch (e) {
      debugPrint('[DeviceIdService] SharedPreferences 저장 예외: $e');
    }

    _cachedDeviceId = hardwareId;
    debugPrint('[DeviceIdService] 🛡️ 영구 기기 고유 ID 확정: $hardwareId');
    return hardwareId;
  }
}
