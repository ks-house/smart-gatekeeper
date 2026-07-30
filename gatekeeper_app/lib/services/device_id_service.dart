import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class DeviceIdService {
  static String? _cachedDeviceId;

  /// 앱 설치별 영구 식별 코드.
  ///
  /// 기존 설치에 저장된 `DEV-*` 값은 서버 등록 호환성을 위해 그대로 유지한다.
  /// 신규 설치는 OS build ID가 아닌 랜덤 UUID를 생성해 같은 펌웨어 빌드의 여러
  /// 휴대폰이 같은 ID를 갖는 문제를 방지한다.
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

    final hardwareId = _generateInstallId();

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

  static String _generateInstallId() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final hex =
        bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
    final installId = 'GK-${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-${hex.substring(16, 20)}-'
        '${hex.substring(20)}';
    return installId.toUpperCase();
  }
}
