import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:http/http.dart' as http;
import 'device_id_service.dart';
import 'update_checker.dart';


/// Smart Gatekeeper BLE Beacon Background Scanner Singleton
class BleScanner {
  static final BleScanner _instance = BleScanner._internal();
  factory BleScanner() => _instance;
  BleScanner._internal();

  // 환경변수(--dart-define=BACKEND_URL=...)로부터 백엔드 주소 동적 로드 (하드코딩 방지)
  static const String backendUrlFromEnv = String.fromEnvironment('BACKEND_URL');
  String backendBaseUrl = backendUrlFromEnv.isNotEmpty 
      ? backendUrlFromEnv 
      : 'https://tworimpa.synology.me:4442/api/v1';

  String targetBeaconUuid = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';

  int cooldownSeconds = 30;

  DateTime? _lastPrearmTime;
  bool _isScanning = false;
  StreamSubscription<List<ScanResult>>? _scanSubscription;

  bool get isScanning => _isScanning;

  /// 초기화 및 Remote Config 동기화 / 버전 검사
  Future<void> initialize() async {
    await fetchRemoteConfig();
    await UpdateChecker().checkForUpdates();
    startScanning();
  }

  /// 백엔드로부터 동적 설정 (/api/v1/config) 로드
  Future<void> fetchRemoteConfig() async {
    try {
      final response = await http
          .get(Uri.parse('$backendBaseUrl/config'))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['beacon_uuid'] != null) {
          targetBeaconUuid = data['beacon_uuid'].toString().toLowerCase();
        }
        if (data['cooldown_sec'] != null) {
          cooldownSeconds = data['cooldown_sec'];
        }

        // 백엔드 Remote Config에 포함된 APK 버전/다운로드 URL 전달
        final apkVersionUrl = data['apk_version_url']?.toString();
        final apkDownloadUrl = data['apk_download_url']?.toString();
        if (apkVersionUrl != null && apkVersionUrl.isNotEmpty) {
          await UpdateChecker().checkForUpdates(
            customVersionUrl: apkVersionUrl,
            customDownloadUrl: apkDownloadUrl,
          );
        }

        debugPrint('[BleScanner] Remote Config 로드 성공: UUID=$targetBeaconUuid, Cooldown=${cooldownSeconds}s');
      }
    } catch (e) {
      debugPrint('[BleScanner] Remote Config 로드 실패 (기본값 사용): $e');
    }
  }


  /// 백그라운드 BLE 비콘 스캐닝 시작
  Future<void> startScanning() async {
    if (_isScanning) return;

    // 블루투스 지원 및 활성화 여부 확인
    if (await FlutterBluePlus.isSupported == false) {
      debugPrint('[BleScanner] 이 기기는 블루투스를 지원하지 않습니다.');
      return;
    }

    _isScanning = true;
    debugPrint('[BleScanner] 비콘 스캐닝 시작... (Target UUID: $targetBeaconUuid)');

    // 스캔 결과 리스너 등록
    _scanSubscription = FlutterBluePlus.scanResults.listen((results) {
      for (ScanResult r in results) {
        _checkAndProcessBeacon(r);
      }
    }, onError: (e) {
      debugPrint('[BleScanner] Scan Error: $e');
    });

    // 지속적 비콘 감지를 위해 androidUsesFineLocation=true 옵션 적용
    try {
      await FlutterBluePlus.startScan(
        timeout: null, // continuous scan
        androidUsesFineLocation: true,
      );
    } catch (e) {
      debugPrint('[BleScanner] startScan 실패: $e');
      _isScanning = false;
    }
  }

  /// 감지된 비콘 검증 및 Pre-arm API 호출
  void _checkAndProcessBeacon(ScanResult result) {
    final advertisementData = result.advertisementData;
    final String deviceName = advertisementData.advName;
    final int rssi = result.rssi;

    // 비콘 UUID 또는 Device Name / Service UUID 매칭 확인
    bool isMatch = false;

    if (deviceName.contains('SmartGatekeeper')) {
      isMatch = true;
    }

    // Service UUIDs 매칭 확인
    for (var uuid in advertisementData.serviceUuids) {
      if (uuid.toString().toLowerCase() == targetBeaconUuid.toLowerCase()) {
        isMatch = true;
        break;
      }
    }

    if (!isMatch) return;

    debugPrint('[BleScanner] Target Gatekeeper 비콘 감지! RSSI: $rssi dBm');

    // 쿨다운 검증 (중복 API 호출 방지)
    final now = DateTime.now();
    if (_lastPrearmTime != null) {
      final difference = now.difference(_lastPrearmTime!).inSeconds;
      if (difference < cooldownSeconds) {
        debugPrint('[BleScanner] 쿨다운 대기 중... ($difference초 경과 / $cooldownSeconds초)');

        return;
      }
    }

    // Pre-arming API 호출
    _lastPrearmTime = now;
    _sendPrearmRequest(rssi);
  }

  /// 백엔드 Pre-arm REST API 호출
  Future<void> _sendPrearmRequest(int rssi) async {
    try {
      final deviceId = await DeviceIdService.getDeviceId();
      debugPrint('[BleScanner] Pre-arm REST API 호출 중... (DeviceId: $deviceId)');
      final response = await http.post(
        Uri.parse('$backendBaseUrl/door/prearm'),
        headers: {
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'beacon_uuid': targetBeaconUuid,
          'device_id': deviceId,
          'rssi': rssi,
          'timestamp': DateTime.now().toIso8601String(),
        }),
      );

      if (response.statusCode == 200) {
        debugPrint('[BleScanner] ✅ Pre-arm 성공! (Status: 200 OK)');
      } else if (response.statusCode == 403) {
        debugPrint('[BleScanner] 🚨 권한 미승인/거부됨 (Status: 403 Forbidden)');
      } else {
        debugPrint('[BleScanner] Pre-arm 실패: HTTP ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('[BleScanner] Pre-arm API 통신 오류: $e');
    }
  }


  /// 스캐닝 중지
  Future<void> stopScanning() async {
    _isScanning = false;
    await _scanSubscription?.cancel();
    await FlutterBluePlus.stopScan();
    debugPrint('[BleScanner] 비콘 스캐닝 중지됨.');
  }
}
