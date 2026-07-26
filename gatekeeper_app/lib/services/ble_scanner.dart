import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
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

  int cooldownSeconds = 10;

  // ─── 엔지니어 원격 튜닝용 파라미터 (DebugScreen 연동) ────────────
  int rssiThreshold = -75;       // 동적 RSSI Threshold (-90 ~ -30 dBm)
  bool ignoreCooldown = false;    // 쿨다운 무시 모드 (테스트용)
  final ValueNotifier<int?> liveRssi = ValueNotifier<int?>(null);
  final ValueNotifier<DateTime?> lastRssiUpdateTime = ValueNotifier<DateTime?>(null);
  final ValueNotifier<int> packetCount = ValueNotifier<int>(0);
  final ValueNotifier<bool> isBeaconConnected = ValueNotifier<bool>(false);

  DateTime? _lastPrearmTime;
  DateTime? _lastArmSuccessTime;
  Timer? _timeoutTimer;
  bool _isPrearmInProgress = false;

  bool _isScanning = false;
  StreamSubscription<List<ScanResult>>? _scanSubscription;

  bool get isScanning => _isScanning;

  void _updateNotification({required String title, required String text}) {
    try {
      FlutterForegroundTask.updateService(
        notificationTitle: title,
        notificationText: text,
      );
    } catch (e) {
      debugPrint('[BleScanner] Notification update error: $e');
    }
  }

  Future<void> loadSavedPreferences() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      ignoreCooldown = prefs.getBool('ignore_cooldown') ?? false;
      rssiThreshold = prefs.getInt('rssi_threshold') ?? -75;
      cooldownSeconds = prefs.getInt('cooldown_seconds') ?? 10;
    } catch (e) {
      debugPrint('[BleScanner] SharedPreferences 로드 실패: $e');
    }
  }

  Future<void> setCooldownSeconds(int value) async {
    cooldownSeconds = value;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('cooldown_seconds', value);
    } catch (_) {}
    debugPrint('[BleScanner] cooldownSeconds 변경: $value초');
  }

  Future<void> setIgnoreCooldown(bool value) async {
    ignoreCooldown = value;
    _lastPrearmTime = DateTime.now(); // 체크 해제 즉시 현재 시각으로 쿨다운 타이머 리셋!
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool('ignore_cooldown', value);
    } catch (_) {}
    debugPrint('[BleScanner] ignoreCooldown 변경: $value (쿨다운 리셋 완료)');
  }

  Future<void> setRssiThreshold(int value) async {
    rssiThreshold = value;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('rssi_threshold', value);
    } catch (_) {}
  }



  void _startTimeoutCheckTimer() {
    _timeoutTimer?.cancel();
    _timeoutTimer = Timer.periodic(const Duration(milliseconds: 1000), (timer) {
      if (lastRssiUpdateTime.value != null) {
        final elapsedMs = DateTime.now().difference(lastRssiUpdateTime.value!).inMilliseconds;
        if (elapsedMs > 2500) { // 2.5초 동안 비콘 UUID 미수신 시
          if (isBeaconConnected.value || liveRssi.value != null) {
            liveRssi.value = null;
            isBeaconConnected.value = false;
            debugPrint('[BleScanner] ⚠️ Target 비콘 신호 미수신 (2.5초 초과) -> "연결 안됨" 전환');
            _updateNotification(
              title: '🔴 Target 비콘 연결 안됨 (탐색 중)',
              text: 'SmartGatekeeper 비콘 신호를 찾는 중입니다...',
            );
          }
        }
      } else {
        if (isBeaconConnected.value) {
          isBeaconConnected.value = false;
          _updateNotification(
            title: '🔴 Target 비콘 연결 안됨 (탐색 중)',
            text: 'SmartGatekeeper 비콘 신호를 찾는 중입니다...',
          );
        }
      }
    });
  }



  /// 초기화 및 Remote Config 동기화 / 버전 검사
  Future<void> initialize() async {
    await loadSavedPreferences();
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
  Future<void> startScanning({bool forceRestart = false}) async {
    if (_isScanning && !forceRestart) return;

    if (forceRestart) {
      await stopScanning();
    }

    // 블루투스 지원 및 활성화 여부 확인
    if (await FlutterBluePlus.isSupported == false) {
      debugPrint('[BleScanner] 이 기기는 블루투스를 지원하지 않습니다.');
      return;
    }

    _isScanning = true;
    debugPrint('[BleScanner] 비콘 실시간 고속 스캐닝 시작... (Target UUID: $targetBeaconUuid)');
    _updateNotification(
      title: '🔴 Target 비콘 연결 안됨 (탐색 중)',
      text: 'SmartGatekeeper 비콘 신호를 찾는 중입니다...',
    );

    // 스캔 결과 리스너 등록
    _scanSubscription?.cancel();
    _scanSubscription = FlutterBluePlus.scanResults.listen((results) {
      for (ScanResult r in results) {
        _checkAndProcessBeacon(r);
      }
    }, onError: (e) {
      debugPrint('[BleScanner] Scan Error: $e');
    });

    // 실시간 연속 RSSI 감지를 위해 continuousUpdates 및 Low Latency 모드 적용
    try {
      _startTimeoutCheckTimer();
      await FlutterBluePlus.startScan(
        timeout: null, // continuous scan
        continuousUpdates: true, // 수신될 때마다 RSSI 패킷 갱신 허용
        androidScanMode: AndroidScanMode.lowLatency, // 고속 감지 모드
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

    // 실시간 RSSI 모니터링 업데이트 (Target UUID 매칭 성공 시에만 활성화)
    liveRssi.value = rssi;
    lastRssiUpdateTime.value = DateTime.now();
    isBeaconConnected.value = true;
    packetCount.value++;



    // 진행 중인 Pre-arm HTTP 요청이 있으면 수신 중복 요청 차단
    if (_isPrearmInProgress) {
      return;
    }

    final isRecentArm = _lastArmSuccessTime != null &&
        DateTime.now().difference(_lastArmSuccessTime!).inSeconds < 4;

    // 동적 RSSI 임계치 필터링
    if (rssi < rssiThreshold) {
      debugPrint('[BleScanner] 비콘 감지되었으나 RSSI 기준 미달: $rssi dBm < $rssiThreshold dBm (무시)');
      if (!isRecentArm) {
        _updateNotification(
          title: '🟡 Target 비콘 신호 약함 ($rssi dBm)',
          text: '센서 근접 필요 (현재: $rssi dBm / 기준: $rssiThreshold dBm)',
        );
      }
      return;
    }

    debugPrint('[BleScanner] Target Gatekeeper 비콘 감지! RSSI: $rssi dBm (Threshold: $rssiThreshold dBm)');

    // 쿨다운 검증 (중복 API 호출 방지 — ignoreCooldown 선택 시 패스)
    final now = DateTime.now();
    if (!ignoreCooldown && _lastPrearmTime != null) {
      final difference = now.difference(_lastPrearmTime!).inSeconds;
      if (difference < cooldownSeconds) {
        final remainSec = cooldownSeconds - difference;
        debugPrint('[BleScanner] 쿨다운 대기 중... ($difference초 경과 / $cooldownSeconds초)');
        if (!isRecentArm) {
          _updateNotification(
            title: '⏳ 출입 쿨다운 대기 중 ($remainSec초)',
            text: 'Target 비콘 감지됨 ($rssi dBm) — 연속 개방 방지 대기 중',
          );
        }
        return;
      }
    }

    // Pre-arming API 호출
    _lastPrearmTime = now;
    _sendPrearmRequest(rssi);
  }


  /// 백엔드 Pre-arm REST API 호출
  Future<void> _sendPrearmRequest(int rssi) async {
    if (_isPrearmInProgress) return;
    _isPrearmInProgress = true;

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
        _lastArmSuccessTime = DateTime.now();
        _updateNotification(
          title: '🟢 Smart Key 출입문 승인 완료!',
          text: 'Target 비콘 감지 ($rssi dBm) → ToF 센서로 다가가면 문이 열립니다!',
        );
      } else if (response.statusCode == 403) {
        debugPrint('[BleScanner] 🚨 권한 미승인/거부됨 (Status: 403 Forbidden)');
        _updateNotification(
          title: '⛔ 출입 권한 거부/미승인',
          text: '관리자 승인이 필요한 세입자 기기입니다.',
        );
      } else {
        debugPrint('[BleScanner] Pre-arm 실패: HTTP ${response.statusCode}');
        _updateNotification(
          title: '⚠️ 출입 승인 실패 (HTTP ${response.statusCode})',
          text: '서버 통신 오류가 발생했습니다.',
        );
      }
    } catch (e) {
      debugPrint('[BleScanner] Pre-arm API 통신 오류: $e');
    } finally {
      _isPrearmInProgress = false;
    }
  }



  /// 스캐닝 중지
  Future<void> stopScanning() async {
    _isScanning = false;
    _timeoutTimer?.cancel();
    liveRssi.value = null;
    isBeaconConnected.value = false;
    await _scanSubscription?.cancel();
    await FlutterBluePlus.stopScan();
    debugPrint('[BleScanner] 비콘 스캐닝 중지됨.');
    _updateNotification(
      title: '⏹️ Target 비콘 감지 중지됨',
      text: '스캔 서비스가 일시 정지되었습니다.',
    );
  }

}

